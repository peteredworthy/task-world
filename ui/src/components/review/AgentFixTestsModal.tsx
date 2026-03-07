import { useState, useEffect, useRef } from 'react';
import { useAgents } from '../../hooks/useApi';
import { useAgentFixTests } from '../../hooks/useReview';
import { Spinner } from '../Spinner';
import { AgentIcon } from '../AgentIcon';
import { AgentConfigForm } from '../AgentConfigForm';
import { buildDefaultAgentConfig } from '../agentRunnerConfigUtils';
import { ApiError } from '../../api/client';
import type { RunResponse } from '../../types';
import type { TestRunResult } from '../../types/review';
import { useFocusTrap } from '../../hooks/useFocusTrap';

interface AgentFixTestsModalProps {
  isOpen: boolean;
  onClose: () => void;
  runId: string;
  run: RunResponse;
  testResult: TestRunResult;
}

/** Extract a list of failing test names from raw log output. */
function extractFailingTests(logOutput: string): string[] {
  const failing: string[] = [];

  // pytest FAILED lines: "FAILED path/to/test.py::test_name - ..."
  const pytestPattern = /^FAILED\s+(\S+)/gm;
  let m: RegExpExecArray | null;
  while ((m = pytestPattern.exec(logOutput)) !== null) {
    failing.push(m[1]);
  }
  if (failing.length > 0) return failing;

  // Lines starting with ✗ or ×
  const symbolPattern = /^[✗×]\s+(.+)$/gm;
  while ((m = symbolPattern.exec(logOutput)) !== null) {
    failing.push(m[1].trim());
  }
  return failing;
}

/** Map agent_type to a visual style */
function agentVisual(agentType: string): { tintBg: string; tintText: string; icon: string } {
  const lower = agentType.toLowerCase();
  if (lower.includes('openhands')) {
    return { icon: '🤚', tintBg: 'bg-orange-500/10', tintText: 'text-orange-400' };
  }
  if (lower.includes('cli')) {
    return { icon: '💻', tintBg: 'bg-cyan-500/10', tintText: 'text-cyan-400' };
  }
  if (lower.includes('mcp')) {
    return { icon: '🔗', tintBg: 'bg-violet-500/10', tintText: 'text-violet-400' };
  }
  if (lower.includes('user') || lower.includes('managed')) {
    return { icon: '👤', tintBg: 'bg-bg-elevated', tintText: 'text-text-muted' };
  }
  return { icon: '🤖', tintBg: 'bg-purple-500/10', tintText: 'text-purple-400' };
}

export function AgentFixTestsModal({
  isOpen,
  onClose,
  runId,
  run,
  testResult,
}: AgentFixTestsModalProps) {
  const { data: agents, isLoading: loadingAgents } = useAgents();
  const agentFixTests = useAgentFixTests(runId);
  const dialogRef = useRef<HTMLDivElement>(null);

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [selectedAgentIndex, setSelectedAgentIndex] = useState<string>('');
  const [agentConfigValues, setAgentConfigValues] = useState<Record<string, unknown>>({});

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setShowAdvanced(false);
      setSelectedAgentIndex('');
      setAgentConfigValues({});
      agentFixTests.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // Escape key to close (unless running)
  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && !agentFixTests.isPending) onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose, agentFixTests.isPending]);

  // Scroll lock
  useEffect(() => {
    if (!isOpen) return;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  useFocusTrap(dialogRef, isOpen);

  if (!isOpen) return null;

  const allAgents = agents ?? [];
  const selectedAgent =
    selectedAgentIndex !== '' ? allAgents[Number(selectedAgentIndex)] : null;

  const failingTests = extractFailingTests(testResult.log_output ?? '');
  const summary = testResult.summary;
  const failedCount = summary?.failed ?? 0;

  async function handleConfirm() {
    try {
      if (showAdvanced && selectedAgent) {
        await agentFixTests.mutateAsync({
          agentType: selectedAgent.agent_type,
          agentConfig: agentConfigValues,
        });
      } else {
        await agentFixTests.mutateAsync({});
      }
      onClose();
    } catch {
      // Error handled by mutation state
    }
  }

  const submitting = agentFixTests.isPending;
  const fixError =
    agentFixTests.error instanceof ApiError
      ? agentFixTests.error.message
      : agentFixTests.error
        ? 'Failed to dispatch agent. Please try again.'
        : null;

  const titleId = 'agent-fix-tests-title';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={() => {
        if (!submitting) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-bg-primary border border-border rounded-xl shadow-2xl w-full max-w-[540px] mx-4 max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-border shrink-0">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-text-primary">
              Fix Failing Tests with Agent
            </h2>
            <p className="text-text-muted text-[13px] mt-0.5">
              Dispatch an agent to investigate and fix the failing tests.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              if (!submitting) onClose();
            }}
            disabled={submitting}
            className="text-text-muted hover:text-text-primary transition-colors p-1 -mr-1 -mt-0.5 rounded-md hover:bg-bg-hover disabled:opacity-40"
            aria-label="Close"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5 min-h-0">
          {/* Scope: failing test summary */}
          <div className="rounded-lg border border-status-failed/30 bg-status-failed/8 px-4 py-3">
            <p className="text-sm font-medium text-status-failed mb-1">
              {failedCount > 0
                ? `${failedCount} test${failedCount === 1 ? '' : 's'} failed`
                : 'Tests failed'}
              {summary && summary.total > 0 && (
                <span className="font-normal text-text-muted ml-1">
                  ({summary.passed}/{summary.total} passed)
                </span>
              )}
            </p>
            {failingTests.length > 0 && (
              <ul className="mt-2 space-y-0.5">
                {failingTests.slice(0, 5).map((t) => (
                  <li key={t} className="text-xs font-mono text-text-secondary truncate">
                    {t}
                  </li>
                ))}
                {failingTests.length > 5 && (
                  <li className="text-xs text-text-muted italic">
                    …and {failingTests.length - 5} more
                  </li>
                )}
              </ul>
            )}
          </div>

          {/* Default agent display */}
          <div>
            <label className="flex items-center gap-1.5 text-sm font-medium text-text-secondary mb-2">
              Agent
            </label>
            {!showAdvanced ? (
              <div className="flex items-center gap-3 px-4 py-3 bg-bg-card border border-border rounded-lg">
                <AgentIcon icon={run.agent_icon} className="h-5 w-5" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-text-primary truncate">
                    {run.agent_type_display}
                  </div>
                  {run.agent_type && (
                    <div className="text-xs text-text-muted truncate">{run.agent_type}</div>
                  )}
                </div>
                <span className="text-xs text-text-muted shrink-0">run default</span>
              </div>
            ) : (
              /* Advanced: agent picker grid */
              loadingAgents ? (
                <div className="flex items-center justify-center py-8">
                  <Spinner className="h-5 w-5" />
                </div>
              ) : allAgents.length === 0 ? (
                <p className="text-sm text-text-muted py-2">
                  No agents detected. Check server configuration.
                </p>
              ) : (
                <div className="grid grid-cols-3 gap-2.5">
                  {allAgents.map((agent, idx) => {
                    const isSelected = selectedAgentIndex === String(idx);
                    const visual = agentVisual(agent.agent_type);
                    const unavailable = !agent.available;

                    return (
                      <button
                        key={`${agent.agent_type}:${agent.name}`}
                        type="button"
                        disabled={unavailable || submitting}
                        onClick={() => {
                          if (unavailable) return;
                          const newIdx = isSelected ? '' : String(idx);
                          setSelectedAgentIndex(newIdx);
                          setAgentConfigValues(
                            !isSelected ? buildDefaultAgentConfig(agent) : {},
                          );
                        }}
                        className={`
                          relative rounded-lg p-3.5 text-left transition-all
                          ${unavailable || submitting
                            ? 'opacity-50 cursor-not-allowed bg-bg-card border border-border'
                            : isSelected
                              ? 'bg-bg-card border-2 border-accent-purple shadow-[0_0_12px_rgba(139,92,246,0.15)]'
                              : 'bg-bg-card border border-border hover:border-border-hover cursor-pointer'
                          }
                        `}
                      >
                        {/* Radio indicator */}
                        <div className="absolute top-2.5 right-2.5">
                          <div
                            className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                              isSelected ? 'border-accent-purple' : 'border-border-hover'
                            }`}
                          >
                            {isSelected && (
                              <div className="w-2 h-2 rounded-full bg-accent-purple" />
                            )}
                          </div>
                        </div>

                        {/* Agent icon */}
                        <div
                          className={`w-9 h-9 rounded-lg flex items-center justify-center text-lg mb-2 ${visual.tintBg}`}
                        >
                          <span className={visual.tintText}>{visual.icon}</span>
                        </div>

                        {/* Name + availability */}
                        <div className="flex items-center gap-1.5">
                          <span className="text-[13px] font-medium text-text-primary truncate">
                            {agent.name}
                          </span>
                          <span
                            className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                              agent.available ? 'bg-status-active' : 'bg-status-failed'
                            }`}
                            title={agent.available ? 'Available' : 'Unavailable'}
                          />
                        </div>

                        {/* Type subtitle */}
                        <span className="text-[11px] text-text-muted mt-0.5 block truncate">
                          {agent.agent_type}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )
            )}
          </div>

          {/* Advanced config form when agent is selected */}
          {showAdvanced && selectedAgent && (
            <div>
              <label className="flex items-center gap-1.5 text-sm font-medium text-text-secondary mb-2">
                Agent Configuration
              </label>
              <AgentConfigForm
                agent={selectedAgent}
                values={agentConfigValues}
                onChange={setAgentConfigValues}
                disabled={submitting}
              />
            </div>
          )}

          {/* Progress indicator */}
          {submitting && (
            <div className="flex items-center gap-3 rounded-lg border border-accent-purple/30 bg-accent-purple/8 px-4 py-3">
              <Spinner className="h-4 w-4 shrink-0" />
              <p className="text-sm text-text-secondary">
                Agent is working on the failing tests…
              </p>
            </div>
          )}

          {/* Error state */}
          {fixError && (
            <div className="rounded-md bg-status-failed/10 border border-status-failed/20 px-3 py-2">
              <p className="text-sm text-status-failed">{fixError}</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="shrink-0 px-6 py-4 border-t border-border flex items-center justify-between gap-3">
          {/* Advanced toggle */}
          <button
            type="button"
            onClick={() => {
              setShowAdvanced((v) => !v);
              setSelectedAgentIndex('');
              setAgentConfigValues({});
            }}
            disabled={submitting}
            className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text-secondary transition-colors disabled:opacity-40"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={`transition-transform ${showAdvanced ? 'rotate-90' : ''}`}
            >
              <polyline points="9 18 15 12 9 6" />
            </svg>
            Advanced
          </button>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-2 text-sm font-medium text-text-secondary bg-transparent border border-border-hover rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void handleConfirm()}
              disabled={submitting || (showAdvanced && !selectedAgent)}
              className="px-5 py-2 text-sm font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              {submitting ? (
                <>
                  <Spinner className="h-4 w-4" />
                  <span>Running…</span>
                </>
              ) : (
                <span>Fix with Agent</span>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
