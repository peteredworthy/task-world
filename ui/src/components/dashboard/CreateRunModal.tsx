import { useState, useEffect, useRef, useMemo } from 'react';
import { useRepos, useAgents, useCreateRun, useStartRun, useRoutine } from '../../hooks/useApi';
import { Spinner } from '../Spinner';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useCreateRunModal } from '../../hooks/useCreateRunModal';
import { BranchSelector } from '../BranchSelector';
import { RoutineSelector } from '../RoutineSelector';
import { RoutineValidatorModal } from '../RoutineValidatorModal';
import { AgentRunnerConfigForm } from '../AgentRunnerConfigForm';
import { buildDefaultAgentConfig } from '../agentRunnerConfigUtils';
import type { RoutineSelection } from '../RoutineSelector';

interface CreateRunModalProps {
  open: boolean;
  onClose: () => void;
}

interface RoutineInput {
  name: string;
  required: boolean;
  default: string | null;
  description: string | null;
}

interface FormState {
  selectedRoutine: string;
  routineYaml: string;
  repoName: string;
  inputValues: Record<string, string>;
  targetBranch: string;
  selectedAgentIndex: string; // index into allAgents array, '' means none
  autoStart: boolean;
  configJson: string;
  /** Structured agent config values (field name → value), updated by AgentRunnerConfigForm */
  agentConfigValues: Record<string, unknown>;
  configError: string;
  prevOpen: boolean;
}

const INITIAL_FORM: FormState = {
  selectedRoutine: '',
  routineYaml: '',
  repoName: '',
  inputValues: {},
  targetBranch: '',
  selectedAgentIndex: '',
  autoStart: true,
  configJson: '{}',
  agentConfigValues: {},
  configError: '',
  prevOpen: false,
};

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

export function CreateRunModal({ open, onClose }: CreateRunModalProps) {
  const { data: reposData, isLoading: loadingRepos } = useRepos();
  const { data: agents, isLoading: loadingAgents } = useAgents();
  const createRun = useCreateRun();
  const startRun = useStartRun();
  const dialogRef = useRef<HTMLDivElement>(null);
  const { preSelectedRoutine } = useCreateRunModal();

  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [routineSelection, setRoutineSelection] = useState<RoutineSelection | null>(null);
  const [routineValidatorOpen, setRoutineValidatorOpen] = useState(false);
  const wasOpenRef = useRef(false);

  // For templates, fetch full routine detail to get input definitions
  const isTemplate = routineSelection && !routineSelection.isProjectRoutine;
  const { data: templateDetail } = useRoutine(isTemplate ? routineSelection.routineId : null);

  // Extract routine inputs from either the project routine config or template detail
  const routineInputs: RoutineInput[] = useMemo(() => {
    if (routineSelection?.isProjectRoutine && routineSelection.config) {
      const inputs = (routineSelection.config as Record<string, unknown>).inputs;
      if (Array.isArray(inputs)) {
        return inputs.map((inp: Record<string, unknown>) => ({
          name: String(inp.name ?? ''),
          required: Boolean(inp.required),
          default: inp.default != null ? String(inp.default) : null,
          description: inp.description != null ? String(inp.description) : null,
        }));
      }
    }
    if (templateDetail?.inputs) {
      return templateDetail.inputs.map((inp: Record<string, unknown>) => ({
        name: String(inp.name ?? ''),
        required: Boolean(inp.required),
        default: inp.default != null ? String(inp.default) : null,
        description: inp.description != null ? String(inp.description) : null,
      }));
    }
    return [];
  }, [routineSelection, templateDetail]);

  // Pre-populate default values when routine inputs change
  useEffect(() => {
    if (routineInputs.length === 0) return;
    const defaults: Record<string, string> = {};
    for (const inp of routineInputs) {
      if (inp.default != null) {
        defaults[inp.name] = inp.default;
      }
    }
    setForm(prev => ({ ...prev, inputValues: defaults }));
  }, [routineInputs]);

  // Reset form on open transition.
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setForm({
        ...INITIAL_FORM,
        prevOpen: true,
        selectedRoutine: preSelectedRoutine ?? '',
      });
      setRoutineSelection(null);
    } else if (!open && wasOpenRef.current) {
      setForm(prev => ({ ...prev, prevOpen: false }));
    }
    wasOpenRef.current = open;
  }, [open, preSelectedRoutine]);

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

  if (!open) return null;

  const repos = reposData?.repos ?? [];
  const allAgents = agents ?? [];
  const titleId = 'create-run-modal-title';

  const selectedAgent = form.selectedAgentIndex !== ''
    ? allAgents[Number(form.selectedAgentIndex)]
    : null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.selectedRoutine || !form.repoName) return;

    // Build config from routine input values
    let config: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(form.inputValues)) {
      if (value.trim()) {
        config[key] = value.trim();
      }
    }
    // Merge with any explicit configJson if the user edited it
    try {
      const parsed = JSON.parse(form.configJson);
      config = { ...config, ...parsed };
      setForm(prev => ({ ...prev, configError: '' }));
    } catch {
      setForm(prev => ({ ...prev, configError: 'Invalid JSON' }));
      return;
    }

    let agentConfig: Record<string, unknown> | undefined;
    if (selectedAgent) {
      agentConfig = form.agentConfigValues;
    }

    try {
      // Project routines must be sent as routine_embedded (backend can't discover them by ID).
      // Fall back to routine_id if config is missing for any reason.
      const useEmbedded = routineSelection?.isProjectRoutine && routineSelection.config;
      const run = await createRun.mutateAsync({
        routine_id: useEmbedded ? undefined : form.selectedRoutine || undefined,
        routine_embedded: useEmbedded ? routineSelection.config : undefined,
        repo_name: form.repoName,
        branch: form.targetBranch || 'main',
        config,
        agent_type: selectedAgent?.agent_type || undefined,
        agent_config: agentConfig,
      });

      if (form.autoStart) {
        await startRun.mutateAsync(run.id);
      }

      onClose();
    } catch {
      // error handled by mutation state
    }
  }

  const loading = loadingRepos || loadingAgents;
  const submitting = createRun.isPending || startRun.isPending;
  const canSubmit = !!form.selectedRoutine && !!form.repoName && !submitting;

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
        <div className="flex items-start justify-between px-6 pt-5 pb-4">
          <div>
            <h2
              id={titleId}
              className="text-lg font-semibold text-text-primary"
            >
              Configure New Agent Run
            </h2>
            <p className="text-text-muted text-[13px] mt-0.5">
              Setup parameters for your next autonomous coding session.
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

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner />
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col flex-1 min-h-0">
            <div className="flex-1 overflow-y-auto px-6 pb-5 space-y-5">
              {/* Repository Selection */}
              <div>
                <label className="flex items-center gap-1.5 text-sm font-medium text-text-secondary mb-2">
                  <span className="text-base leading-none">{'\u{1F4C1}'}</span>
                  Repository
                </label>
                {repos.length === 0 ? (
                  <p className="text-sm text-text-muted py-2">
                    No repositories found. Register repos via CLI or API.
                  </p>
                ) : (
                  <select
                    autoFocus
                    required
                    value={form.repoName}
                    onChange={e => setForm(prev => ({ ...prev, repoName: e.target.value, targetBranch: 'main', selectedRoutine: '' }))}
                    className="w-full rounded-md border border-border bg-bg-card px-3 py-2.5 text-sm text-text-primary shadow-sm focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 appearance-none cursor-pointer"
                  >
                    <option value="">Select a repository...</option>
                    {repos.map(repo => (
                      <option key={repo.name} value={repo.name}>
                        {repo.name} ({repo.path})
                      </option>
                    ))}
                  </select>
                )}
              </div>

              {/* Branch Selection */}
              {form.repoName && (
                <div>
                  <label className="flex items-center gap-1.5 text-sm font-medium text-text-secondary mb-2">
                    <span className="text-base leading-none">{'\u{1F333}'}</span>
                    Branch
                  </label>
                  <BranchSelector
                    repoName={form.repoName}
                    value={form.targetBranch}
                    onChange={branch => setForm(prev => ({ ...prev, targetBranch: branch, selectedRoutine: '' }))}
                    includeRemote={false}
                  />
                </div>
              )}

              {/* Routine Selection */}
              {form.repoName && (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="flex items-center gap-1.5 text-sm font-medium text-text-secondary">
                      <span className="text-base leading-none">{'\u{1F4CB}'}</span>
                      Routine
                    </label>
                    <button
                      type="button"
                      onClick={() => setRoutineValidatorOpen(true)}
                      className="text-xs text-accent-purple hover:text-accent-purple/80 transition-colors"
                    >
                      Validate routine YAML
                    </button>
                  </div>
                  <RoutineSelector
                    repoName={form.repoName}
                    branch={form.targetBranch || 'main'}
                    value={form.selectedRoutine}
                    onChange={routineId => setForm(prev => ({ ...prev, selectedRoutine: routineId, inputValues: {} }))}
                    onSelectionChange={setRoutineSelection}
                    required
                  />
                </div>
              )}

              {/* Routine YAML (prefilled from validator) */}
              {form.repoName && (
                <div>
                  <label className="flex items-center gap-1.5 text-sm font-medium text-text-secondary mb-2">
                    <span className="text-base leading-none">{'\u{1F4DD}'}</span>
                    Routine YAML
                  </label>
                  <textarea
                    rows={5}
                    value={form.routineYaml}
                    onChange={e => setForm(prev => ({ ...prev, routineYaml: e.target.value }))}
                    placeholder="Optional. Use the routine validator to prefill this."
                    className="w-full rounded-md border border-border bg-bg-card px-3 py-2.5 text-sm font-mono text-text-primary shadow-sm placeholder:text-text-muted focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 resize-y"
                  />
                </div>
              )}

              {/* Routine Inputs */}
              {routineInputs.length > 0 && (
                <div>
                  <label className="flex items-center gap-1.5 text-sm font-medium text-text-secondary mb-2">
                    <span className="text-base leading-none">{'\u2699\uFE0F'}</span>
                    Configuration
                  </label>
                  <div className="space-y-3">
                    {routineInputs.map(inp => (
                      <div key={inp.name}>
                        <label className="block text-xs text-text-muted mb-1">
                          {inp.name}
                          {inp.required && <span className="text-status-failed ml-0.5">*</span>}
                        </label>
                        <input
                          type="text"
                          placeholder={inp.default ?? (inp.description ?? `Enter ${inp.name}`)}
                          value={form.inputValues[inp.name] ?? ''}
                          onChange={e => setForm(prev => ({
                            ...prev,
                            inputValues: { ...prev.inputValues, [inp.name]: e.target.value },
                          }))}
                          className="w-full rounded-md border border-border bg-bg-card px-3 py-2 text-sm text-text-primary shadow-sm placeholder:text-text-muted focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50"
                        />
                        {inp.description && (
                          <p className="mt-0.5 text-[11px] text-text-muted">{inp.description}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Agent Selection */}
              <div>
                <label className="flex items-center gap-1.5 text-sm font-medium text-text-secondary mb-2">
                  <span className="text-base leading-none">{'\u{1F916}'}</span>
                  Agent
                </label>
                {allAgents.length === 0 ? (
                  <p className="text-sm text-text-muted py-2">
                    No agents detected. Check server configuration.
                  </p>
                ) : (
                  <div className="grid grid-cols-3 gap-2.5">
                    {allAgents.map((agent, idx) => {
                      const isSelected = form.selectedAgentIndex === String(idx);
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
                            const agentConfigValues = !isSelected
                              ? buildDefaultAgentConfig(agent)
                              : {};
                            setForm(prev => ({
                              ...prev,
                              selectedAgentIndex: newIdx,
                              agentConfigValues,
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

              {/* Agent Configuration (shown when agent is selected) */}
              {selectedAgent && (
                <div>
                  <label className="flex items-center gap-1.5 text-sm font-medium text-text-secondary mb-2">
                    <span className="text-base leading-none">{'\u{1F527}'}</span>
                    Agent Configuration
                  </label>
                  <AgentRunnerConfigForm
                    agent={selectedAgent}
                    values={form.agentConfigValues}
                    onChange={(vals) => setForm(prev => ({ ...prev, agentConfigValues: vals }))}
                    disabled={submitting}
                  />
                  <p className="mt-2 text-xs text-text-muted">{selectedAgent.detail}</p>
                </div>
              )}

              {/* Advanced Config JSON (collapsed by default for power users) */}
              <details className="group">
                <summary className="flex items-center gap-1.5 text-sm font-medium text-text-secondary cursor-pointer select-none">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="transition-transform group-open:rotate-90"
                  >
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                  Advanced Config (JSON)
                </summary>
                <div className="mt-2">
                  <textarea
                    rows={3}
                    value={form.configJson}
                    onChange={e => setForm(prev => ({
                      ...prev,
                      configJson: e.target.value,
                      configError: '',
                    }))}
                    className="w-full rounded-md border border-border bg-bg-card px-3 py-2.5 text-sm font-mono text-text-primary shadow-sm focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple/50 resize-none"
                  />
                  {form.configError && (
                    <p className="mt-1 text-xs text-status-failed">{form.configError}</p>
                  )}
                </div>
              </details>

              {/* Error states */}
              {createRun.isError && (
                <div className="rounded-md bg-status-failed/10 border border-status-failed/20 px-3 py-2">
                  <p className="text-sm text-status-failed">Failed to create run. Check your inputs.</p>
                </div>
              )}
              {startRun.isError && (
                <div className="rounded-md bg-status-failed/10 border border-status-failed/20 px-3 py-2">
                  <p className="text-sm text-status-failed">Run created but failed to start.</p>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-border flex justify-end gap-3">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-text-secondary bg-transparent border border-border-hover rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!canSubmit}
                className="px-5 py-2 text-sm font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
              >
                {submitting ? (
                  <>
                    <Spinner />
                    <span>Creating...</span>
                  </>
                ) : (
                  <>
                    <span>{'\u{1F680}'}</span>
                    <span>Create & Start</span>
                  </>
                )}
              </button>
            </div>
          </form>
        )}
      </div>
      <RoutineValidatorModal
        isOpen={routineValidatorOpen}
        onClose={() => setRoutineValidatorOpen(false)}
        onCreateRun={(yaml) => {
          setForm(prev => ({ ...prev, routineYaml: yaml }));
          setRoutineValidatorOpen(false);
        }}
      />
    </div>
  );
}
