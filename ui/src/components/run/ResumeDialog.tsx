import { useState, useEffect, useRef } from 'react';
import { useAgents, useResumeRun } from '../../hooks/useApi';
import { Spinner } from '../Spinner';
import { AgentIcon } from '../AgentIcon';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import type { RunResponse, AgentOption } from '../../types';

interface ResumeDialogProps {
  open: boolean;
  run: RunResponse | null;
  onClose: () => void;
}

interface DialogState {
  showAgentPicker: boolean;
  selectedAgentIndex: string;
  agentConfigJson: string;
  agentConfigError: string;
  prevOpen: boolean;
}

/** Map agent_type to a display icon and tint color */
function agentVisual(agentType: string): { icon: string; tintBg: string; tintText: string } {
  const lower = agentType.toLowerCase();
  if (lower.includes('openhands')) {
    return { icon: '\u{1F91A}', tintBg: 'bg-orange-500/10', tintText: 'text-orange-400' };
  }
  if (lower.includes('cli')) {
    return { icon: '\u{1F4BB}', tintBg: 'bg-cyan-500/10', tintText: 'text-cyan-400' };
  }
  if (lower.includes('mcp')) {
    return { icon: '\u{1F517}', tintBg: 'bg-violet-500/10', tintText: 'text-violet-400' };
  }
  if (lower.includes('user') || lower.includes('managed')) {
    return { icon: '\u{1F464}', tintBg: 'bg-bg-elevated', tintText: 'text-text-muted' };
  }
  return { icon: '\u{1F916}', tintBg: 'bg-purple-500/10', tintText: 'text-purple-400' };
}

function buildDefaultAgentConfig(agent: AgentOption): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const field of agent.config_schema) {
    if (field.default !== null && field.default !== undefined) {
      config[field.name] = field.default;
    }
  }
  return config;
}

const INITIAL_STATE: DialogState = {
  showAgentPicker: false,
  selectedAgentIndex: '',
  agentConfigJson: '{}',
  agentConfigError: '',
  prevOpen: false,
};

export function ResumeDialog({ open, run, onClose }: ResumeDialogProps) {
  const { data: agents, isLoading: loadingAgents } = useAgents();
  const resumeRun = useResumeRun();
  const dialogRef = useRef<HTMLDivElement>(null);

  const [state, setState] = useState<DialogState>(INITIAL_STATE);

  // Reset state when dialog opens (detect open transition)
  if (open && !state.prevOpen) {
    setState({ ...INITIAL_STATE, prevOpen: true });
  } else if (!open && state.prevOpen) {
    setState(prev => ({ ...prev, prevOpen: false }));
  }

  // Escape key to close
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  // Scroll lock
  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  useFocusTrap(dialogRef, open);

  if (!open || !run) return null;

  const allAgents = agents ?? [];
  const selectedAgent = state.selectedAgentIndex !== '' ? allAgents[Number(state.selectedAgentIndex)] : null;
  const titleId = 'resume-dialog-title';

  async function handleResumeWithCurrentAgent() {
    if (!run) return;
    try {
      await resumeRun.mutateAsync({ runId: run.id });
      onClose();
    } catch {
      // Error handled by mutation state
    }
  }

  async function handleResumeWithNewAgent() {
    if (!run || !selectedAgent) return;

    let agentConfig: Record<string, unknown>;
    try {
      agentConfig = JSON.parse(state.agentConfigJson);
      setState(prev => ({ ...prev, agentConfigError: '' }));
    } catch {
      setState(prev => ({ ...prev, agentConfigError: 'Invalid JSON' }));
      return;
    }

    try {
      await resumeRun.mutateAsync({
        runId: run.id,
        agentType: selectedAgent.agent_type,
        agentConfig,
      });
      onClose();
    } catch {
      // Error handled by mutation state
    }
  }

  const submitting = resumeRun.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="bg-bg-primary border border-border rounded-xl shadow-2xl w-full max-w-[520px] mx-4 max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-border">
          <div>
            <h2
              id={titleId}
              className="text-lg font-semibold text-text-primary"
            >
              Resume Run
            </h2>
            <p className="text-text-muted text-[13px] mt-0.5">
              Continue the paused run with the same or a different agent.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-text-muted hover:text-text-primary transition-colors p-1 -mr-1 -mt-0.5 rounded-md hover:bg-bg-hover"
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

        {loadingAgents ? (
          <div className="flex items-center justify-center py-16">
            <Spinner />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
            {/* Current Agent Info */}
            <div>
              <label className="flex items-center gap-1.5 text-sm font-medium text-text-secondary mb-2">
                Current Agent
              </label>
              <div className="flex items-center gap-3 px-4 py-3 bg-bg-card border border-border rounded-lg">
                <AgentIcon icon={run.agent_icon} className="h-5 w-5" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-text-primary truncate">
                    {run.agent_type_display}
                  </div>
                  {run.agent_type && (
                    <div className="text-xs text-text-muted truncate">
                      {run.agent_type}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Action Selection */}
            {!state.showAgentPicker ? (
              <div className="space-y-3">
                <button
                  onClick={handleResumeWithCurrentAgent}
                  disabled={submitting}
                  className="w-full px-4 py-3 text-sm font-medium text-white bg-accent-purple rounded-lg hover:bg-accent-purple/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
                >
                  {submitting ? (
                    <>
                      <Spinner />
                      <span>Resuming...</span>
                    </>
                  ) : (
                    <>
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="currentColor"
                      >
                        <path d="M8 5v14l11-7z" />
                      </svg>
                      <span>Resume with Current Agent</span>
                    </>
                  )}
                </button>

                <button
                  onClick={() => setState(prev => ({ ...prev, showAgentPicker: true }))}
                  disabled={submitting}
                  className="w-full px-4 py-3 text-sm font-medium text-text-primary bg-bg-card border border-border rounded-lg hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
                  </svg>
                  <span>Change Agent...</span>
                </button>
              </div>
            ) : (
              <>
                {/* Agent Selection */}
                <div>
                  <label className="flex items-center gap-1.5 text-sm font-medium text-text-secondary mb-2">
                    <span className="text-base leading-none">{'\u{1F916}'}</span>
                    Select New Agent
                  </label>
                  {allAgents.length === 0 ? (
                    <p className="text-sm text-text-muted py-2">
                      No agents detected. Check server configuration.
                    </p>
                  ) : (
                    <div className="grid grid-cols-3 gap-2.5">
                      {allAgents.map((agent, idx) => {
                        const isSelected = state.selectedAgentIndex === String(idx);
                        const visual = agentVisual(agent.agent_type);
                        const disabled = !agent.available;

                        return (
                          <button
                            key={`${agent.agent_type}:${agent.name}`}
                            type="button"
                            disabled={disabled}
                            onClick={() => {
                              if (disabled) return;
                              const newIdx = isSelected ? '' : String(idx);
                              const newAgentConfigJson = !isSelected
                                ? JSON.stringify(buildDefaultAgentConfig(agent), null, 2)
                                : '{}';
                              setState(prev => ({
                                ...prev,
                                selectedAgentIndex: newIdx,
                                agentConfigJson: newAgentConfigJson,
                                agentConfigError: '',
                              }));
                            }}
                            className={`
                              relative rounded-lg p-3.5 text-left transition-all
                              ${disabled
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
                                className={`
                                  w-4 h-4 rounded-full border-2 flex items-center justify-center
                                  ${isSelected
                                    ? 'border-accent-purple'
                                    : 'border-border-hover'
                                  }
                                `}
                              >
                                {isSelected && (
                                  <div className="w-2 h-2 rounded-full bg-accent-purple" />
                                )}
                              </div>
                            </div>

                            {/* Agent icon */}
                            <div
                              className={`
                                w-9 h-9 rounded-lg flex items-center justify-center text-lg mb-2
                                ${visual.tintBg}
                              `}
                            >
                              <span className={visual.tintText}>{visual.icon}</span>
                            </div>

                            {/* Name + availability */}
                            <div className="flex items-center gap-1.5">
                              <span className="text-[13px] font-medium text-text-primary truncate">
                                {agent.name}
                              </span>
                              <span
                                className={`
                                  inline-block w-1.5 h-1.5 rounded-full flex-shrink-0
                                  ${agent.available
                                    ? 'bg-status-active'
                                    : 'bg-status-failed'
                                  }
                                `}
                                title={agent.available ? 'Available' : 'Unavailable'}
                              />
                            </div>

                            {/* Agent type subtitle */}
                            <span className="text-[11px] text-text-muted mt-0.5 block truncate">
                              {agent.agent_type}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* Agent Configuration */}
                {selectedAgent && (
                  <div>
                    <label className="flex items-center gap-1.5 text-sm font-medium text-text-secondary mb-2">
                      <span className="text-base leading-none">{'\u{1F527}'}</span>
                      Agent Configuration
                    </label>
                    <textarea
                      rows={3}
                      value={state.agentConfigJson}
                      onChange={e => setState(prev => ({
                        ...prev,
                        agentConfigJson: e.target.value,
                        agentConfigError: '',
                      }))}
                      className="w-full rounded-md border border-border bg-bg-card px-3 py-2.5 text-sm font-mono text-text-primary shadow-sm focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 resize-none"
                    />
                    {state.agentConfigError && (
                      <p className="mt-1 text-xs text-status-failed">{state.agentConfigError}</p>
                    )}
                    <p className="mt-1 text-xs text-text-muted">{selectedAgent.detail}</p>
                  </div>
                )}

                {/* Error state */}
                {resumeRun.isError && (
                  <div className="rounded-md bg-status-failed/10 border border-status-failed/20 px-3 py-2">
                    <p className="text-sm text-status-failed">Failed to resume run. Please try again.</p>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Footer */}
        {state.showAgentPicker && (
          <div className="px-6 py-4 border-t border-border flex justify-end gap-3">
            <button
              type="button"
              onClick={() => setState(prev => ({ ...prev, showAgentPicker: false }))}
              className="px-4 py-2 text-sm font-medium text-text-secondary bg-transparent border border-border-hover rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors"
            >
              Back
            </button>
            <button
              onClick={handleResumeWithNewAgent}
              disabled={!selectedAgent || submitting}
              className="px-5 py-2 text-sm font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              {submitting ? (
                <>
                  <Spinner />
                  <span>Resuming...</span>
                </>
              ) : (
                <>
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="currentColor"
                  >
                    <path d="M8 5v14l11-7z" />
                  </svg>
                  <span>Resume with New Agent</span>
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
