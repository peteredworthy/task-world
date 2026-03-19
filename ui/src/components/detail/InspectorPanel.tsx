import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { useActivity, useRun, useTask, useTaskPrompt, useRecoverRun, useResumeRun } from '../../hooks/useApi';
import { useClarificationHistory } from '../../hooks/useClarifications';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { TaskStatusBadge } from '../StatusBadge';
import { GradeBadge } from '../GradeBadge';
import { Spinner } from '../Spinner';
import { LogsViewer } from './LogsViewer';
import { ChecklistTable } from './ChecklistTable';
import { ClarificationHistoryCard } from './ClarificationHistoryCard';
import { formatDuration, formatRelativeTime, formatTokens } from '../../lib/format';
import { groupEventsByTask, type TaskEventGroup } from '../../lib/activity';
import { outcomeColor, outcomeLabel } from '../../lib/outcome';
import {
  PRIORITY_ORDER,
  PRIORITY_LABELS,
  getMetric,
  getLatestAttemptContext,
  isGradeFailing,
  COLLAPSIBLE_BORDER_CLASS,
  COLLAPSIBLE_DIVIDER_CLASS,
} from './sharedUtils';
import type { AttemptSchema, ChecklistItemSchema, FanOutChildSummary, GradeSnapshotItem, TaskSummary } from '../../types';

interface InspectorPanelProps {
  task: TaskSummary;
  runId: string;
  onClose: () => void;
}

interface InspectorModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  size?: 'md' | 'lg' | 'xl';
}

function InspectorModal({ open, title, onClose, children, size = 'lg' }: InspectorModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, open);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKeyDown);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [open, onClose]);

  if (!open) return null;

  const maxWidth =
    size === 'md'
      ? 'max-w-lg'
      : size === 'xl'
        ? 'max-w-4xl'
        : 'max-w-2xl';

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        className={`w-full ${maxWidth} max-h-[85vh] overflow-hidden rounded-lg border border-border bg-bg-card shadow-xl`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
          <button
            onClick={onClose}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-bg-hover transition-colors"
            aria-label="Close modal"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="max-h-[calc(85vh-56px)] overflow-y-auto px-4 py-3">
          {children}
        </div>
      </div>
    </div>
  );
}

function formatAgentType(agentType: string | null): string {
  if (!agentType) return 'Unknown';
  return agentType
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function getAgentDisplayName(att: AttemptSchema): string {
  if (att.agent_type === 'cli_subprocess') {
    const command = att.agent_settings?.command;
    if (typeof command === 'string' && command.trim().length > 0) {
      return command.trim();
    }
  }
  return formatAgentType(att.agent_type);
}

function eventLabel(eventType: string, payload: Record<string, unknown>): string {
  switch (eventType) {
    case 'task_status_changed': {
      const oldS = payload.old_status as string | undefined;
      const newS = payload.new_status as string | undefined;
      if (oldS && newS) return `${oldS} \u2192 ${newS}`;
      return 'status changed';
    }
    case 'checklist_gate_evaluated':
      return payload.passed ? 'Gate passed' : 'Gate blocked';
    case 'grades_evaluated': {
      if (payload.passed) return 'Grades passed';
      const failing = payload.failing_items as string[] | undefined;
      if (failing && failing.length > 0) {
        return `Grades failed: ${failing.join('; ')}`;
      }
      return 'Grades failed';
    }
    case 'step_completed':
      return 'Step completed';
    case 'agent_error':
      return (payload.error_message as string) || 'Agent error';
    default:
      return eventType.replace(/_/g, ' ');
  }
}

function PromptBlock({ label, text }: { label: string; text: string }) {
  const copyToClipboard = () => { navigator.clipboard.writeText(text); };

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-semibold text-text-muted uppercase">{label}</span>
        <button
          onClick={copyToClipboard}
          className="text-[10px] text-text-muted hover:text-text-primary transition-colors"
        >
          Copy
        </button>
      </div>
      <pre className="text-[11px] text-text-secondary bg-bg-card border border-border rounded-md p-2 max-h-64 overflow-y-auto font-mono whitespace-pre-wrap">
        {text}
      </pre>
    </div>
  );
}

function AutoVerifyResults({ results }: { results: Record<string, unknown>[] }) {
  return (
    <div className="rounded-md border border-border bg-bg-card/40 p-2">
      <h5 className="text-[11px] font-semibold text-text-secondary uppercase tracking-wide mb-1.5">
        Auto-Verify Checks
      </h5>
      <div className="space-y-1">
        {results.map((r, i) => {
          const passed = r.passed as boolean;
          const itemId = (r.item_id as string) ?? `check-${i}`;
          const cmd = r.cmd as string | undefined;
          const exitCode = r.exit_code as number | undefined;
          const output = r.output as string | undefined;

          return (
            <div key={itemId} className={'rounded border px-2 py-1.5 text-xs ' + (passed ? 'bg-bg-card border-border' : 'bg-status-failed/5 border-status-failed/20')}>
              <div className="flex items-center gap-2">
                <span className="font-medium text-text-primary truncate">{itemId}</span>
                <span className={'ml-auto inline-flex min-w-12 items-center justify-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ' + (passed ? 'bg-status-completed/15 text-status-completed' : 'bg-status-failed/15 text-status-failed')}>
                  {passed ? 'Pass' : 'Fail'}
                </span>
              </div>
              {cmd && <code className="text-text-muted text-[10px] block mt-0.5 truncate">{cmd}</code>}
              {!passed && exitCode !== undefined && (
                <div className="text-[10px] text-text-muted mt-0.5">exit code {exitCode}</div>
              )}
              {!passed && output && (
                <pre className="text-[10px] text-text-muted mt-1 whitespace-pre-wrap max-h-24 overflow-y-auto font-mono">{output}</pre>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function filenameFromPath(path: string): string {
  const parts = path.split('/');
  return parts[parts.length - 1] || path;
}

function InspectorFanOutChildrenSection({
  childTasks,
  runId,
}: {
  childTasks: FanOutChildSummary[];
  runId: string;
}) {
  const [expandedChildId, setExpandedChildId] = useState<string | null>(null);
  const completedCount = childTasks.filter(t => t.status === 'completed').length;
  const failedCount = childTasks.filter(t => t.status === 'failed').length;

  return (
    <div>
      <h3 className="text-[11px] font-semibold text-text-secondary uppercase tracking-wide mb-1.5">
        Fan-out Progress
        <span className="ml-2 text-text-muted font-mono normal-case">
          {completedCount}/{childTasks.length} complete
          {failedCount > 0 && <span className="text-status-failed ml-1">({failedCount} failed)</span>}
        </span>
      </h3>
      <div className="space-y-1">
        {childTasks.map(child => {
          const rowKey = child.id ?? child.fan_out_input ?? child.title;
          const isExpanded = expandedChildId === rowKey;
          return (
            <InspectorFanOutChildRow
              key={rowKey}
              child={child}
              runId={runId}
              isExpanded={isExpanded}
              onToggle={() => setExpandedChildId(isExpanded ? null : rowKey)}
            />
          );
        })}
      </div>
    </div>
  );
}

function InspectorFanOutChildRow({
  child,
  runId,
  isExpanded,
  onToggle,
}: {
  child: FanOutChildSummary;
  runId: string;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const { data: detail, isLoading } = useTask(runId, isExpanded && child.id ? child.id : undefined);

  return (
    <div className={`rounded-md border ${COLLAPSIBLE_BORDER_CLASS} overflow-hidden`}>
      <button
        onClick={onToggle}
        className="w-full text-left px-2 py-1.5 hover:bg-bg-hover/30 transition-colors"
        aria-expanded={isExpanded}
      >
        <div className="flex items-center gap-2">
          <TaskStatusBadge status={child.status} />
          <span className="text-xs text-text-primary truncate flex-1 min-w-0" title={child.title}>
            {detail?.fan_out_input ? filenameFromPath(detail.fan_out_input) : child.fan_out_input ? filenameFromPath(child.fan_out_input) : child.title}
          </span>
          {child.current_attempt > 1 && (
            <span className="text-[10px] text-status-paused font-mono shrink-0">
              x{child.current_attempt}
            </span>
          )}
          <svg
            className={'h-3 w-3 text-text-muted shrink-0 transition-transform ' + (isExpanded ? 'rotate-90' : '')}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>
      </button>
      {isExpanded && (
        <div className={`border-t ${COLLAPSIBLE_DIVIDER_CLASS} p-2 space-y-2`}>
          {child.fan_out_input && (
            <div className="rounded border border-border bg-bg-card/40 px-2 py-1.5">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Input</div>
              <div className="mt-0.5 break-all font-mono text-[11px] text-text-secondary">{child.fan_out_input}</div>
            </div>
          )}
          {child.fan_out_output && (
            <div className="rounded border border-border bg-bg-card/40 px-2 py-1.5">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">Output</div>
              <div className="mt-0.5 break-all font-mono text-[11px] text-text-secondary">{child.fan_out_output}</div>
            </div>
          )}
          {child.is_synthetic && !child.id ? (
            <div className="rounded border border-border bg-bg-card/40 px-2 py-1.5">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-text-muted">History</div>
              <p className="mt-0.5 text-xs text-text-muted italic">
                Historical fan-out child reconstructed from routine inputs. Agent output and per-child grades were not persisted for this run.
              </p>
            </div>
          ) : null}
          {isLoading ? (
            <div className="flex justify-center py-3">
              <Spinner className="h-4 w-4" />
            </div>
          ) : detail ? (
            detail.attempts.length === 0 ? (
              <p className="text-xs text-text-muted italic">No attempts yet</p>
            ) : (
              detail.attempts.map((att, i) => (
                <div
                  key={att.id}
                  className="rounded border border-border bg-bg-card/40 px-2 py-1.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium text-text-primary">
                      Attempt #{att.attempt_num}
                    </span>
                    {att.outcome && (
                      <span className={'text-[10px] font-semibold uppercase rounded px-1.5 py-0.5 bg-bg-card border border-border ' + outcomeColor(att.outcome)}>
                        {outcomeLabel(att.outcome)}
                      </span>
                    )}
                  </div>
                  {i === detail.attempts.length - 1 && att.verifier_comment && (
                    <p className="text-[11px] text-text-muted mt-1 whitespace-pre-wrap break-words">
                      {att.verifier_comment}
                    </p>
                  )}
                </div>
              ))
            )
          ) : null}
        </div>
      )}
    </div>
  );
}

function AttemptGrades({
  snapshot,
  checklist,
}: {
  snapshot: GradeSnapshotItem[];
  checklist: ChecklistItemSchema[];
}) {
  if (snapshot.length === 0) return null;

  const checklistMap = new Map(checklist.map(c => [c.req_id, c]));

  const enriched = snapshot.map(gs => ({
    ...gs,
    desc: checklistMap.get(gs.req_id)?.desc ?? gs.req_id,
    priority: (checklistMap.get(gs.req_id)?.priority ?? 'expected').toLowerCase(),
  }));

  const grouped = new Map<string, typeof enriched>();
  for (const item of enriched) {
    const existing = grouped.get(item.priority);
    if (existing) existing.push(item);
    else grouped.set(item.priority, [item]);
  }

  const activePriorities = PRIORITY_ORDER.filter(p => grouped.has(p));
  if (activePriorities.length === 0) return null;

  return (
    <div className="space-y-2">
      {activePriorities.map(priority => {
        const items = grouped.get(priority) ?? [];
        const label = PRIORITY_LABELS[priority] ?? priority;
        const withGrade = items.filter(i => i.grade);

        return (
          <div key={priority} className="rounded-md border border-border bg-bg-card/40 p-2">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-wide">
                {label}
              </span>
              <span className="text-[10px] text-text-muted">
                ({withGrade.length}/{items.length})
              </span>
            </div>
            <div className="space-y-1">
              {items.map(item => {
                const failing = isGradeFailing(item.grade, item.priority);
                return (
                  <div key={item.req_id} className={`rounded border px-2 py-1.5 ${failing ? 'bg-status-failed/5 border-status-failed/40' : 'bg-bg-card border-border'}`}>
                    <div className="flex items-center gap-2">
                      <span className="flex-1 text-xs text-text-secondary truncate">
                        {item.desc}
                      </span>
                      <div className="w-10 shrink-0 flex justify-end">
                        {item.grade ? (
                          <GradeBadge grade={item.grade} />
                        ) : (
                          <span className="text-text-muted text-[10px]">--</span>
                        )}
                      </div>
                    </div>
                    {(item.grade_reason || item.note) && (
                      <p className="text-[11px] text-text-muted mt-1 pl-0.5">
                        {item.grade_reason}
                        {item.grade_reason && item.note && <span className="mx-1">·</span>}
                        {item.note}
                      </p>
                    )}
                    {failing && (
                      <div className="flex justify-end mt-0.5">
                        <span className="text-[10px] font-semibold text-status-failed uppercase tracking-wide">Failed</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function InspectorAttemptCard({
  att,
  checklist,
  isLatest,
  onOpenLogs,
  onOpenPrompts,
}: {
  att: AttemptSchema;
  checklist: ChecklistItemSchema[];
  isLatest: boolean;
  onOpenLogs: (att: AttemptSchema) => void;
  onOpenPrompts: (att: AttemptSchema) => void;
}) {
  const [open, setOpen] = useState(false);
  const durationMs = getMetric(att.metrics, 'duration_ms');
  const tokensRead = getMetric(att.metrics, 'tokens_read');
  const tokensWrite = getMetric(att.metrics, 'tokens_write');
  const totalTokens = tokensRead + tokensWrite;
  const hasAgentLogs = att.has_output || att.has_action_log;
  const hasPrompts = Boolean(att.builder_prompt || att.verifier_prompt || att.outcome);
  const hasBodyContent = Boolean(
    att.error
    || att.grade_snapshot.length > 0
    || (att.auto_verify_results && att.auto_verify_results.length > 0)
    || att.verifier_comment
    || hasAgentLogs
    || hasPrompts,
  );

  return (
    <div
      className={
        'rounded-md border overflow-hidden ' +
        (isLatest ? `bg-bg-elevated ${COLLAPSIBLE_BORDER_CLASS}` : `bg-bg-card ${COLLAPSIBLE_BORDER_CLASS}`)
      }
    >
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full text-left px-2 py-1.5 hover:bg-bg-hover/30 transition-colors"
      >
        <div className="flex items-start gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-text-primary">
                Attempt #{att.attempt_num}
              </span>
              {att.outcome && (
                <span className={'text-[10px] font-semibold uppercase rounded px-1.5 py-0.5 bg-bg-card border border-border ' + outcomeColor(att.outcome)}>
                  {outcomeLabel(att.outcome)}
                </span>
              )}
            </div>

            {att.agent_type && (
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-text-secondary mb-1.5">
                <span>Agent:</span>
                <span className="font-medium text-text-primary truncate">{getAgentDisplayName(att)}</span>
                {att.agent_model && (
                  <>
                    <span className="text-text-muted">·</span>
                    <span className="text-text-muted truncate">{att.agent_model}</span>
                  </>
                )}
                {totalTokens > 0 && (
                  <>
                    <span className="text-text-muted">·</span>
                    <span className="text-text-muted">{formatTokens(totalTokens)} tokens</span>
                  </>
                )}
              </div>
            )}

            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-text-muted">
              {durationMs > 0 && <span>{formatDuration(durationMs)}</span>}
              {tokensRead > 0 && <span>{formatTokens(tokensRead)} read</span>}
              {tokensWrite > 0 && <span>{formatTokens(tokensWrite)} write</span>}
            </div>
          </div>
          <svg
            className={'h-4 w-4 text-text-muted shrink-0 mt-0.5 transition-transform ' + (open ? 'rotate-90' : '')}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>
      </button>

      {open && hasBodyContent && (
        <div className={`border-t ${COLLAPSIBLE_DIVIDER_CLASS} p-2 space-y-2`}>
          {att.error && (
            <div className="rounded bg-status-failed/10 border border-status-failed/30 px-2 py-1.5">
              <span className="text-[10px] font-semibold text-status-failed uppercase block mb-1">
                Error
              </span>
              <p className="text-xs text-status-failed whitespace-pre-wrap break-words">{att.error}</p>
            </div>
          )}

          {att.grade_snapshot.length > 0 && (
            <AttemptGrades snapshot={att.grade_snapshot} checklist={checklist} />
          )}

          {att.auto_verify_results && att.auto_verify_results.length > 0 && (
            <AutoVerifyResults results={att.auto_verify_results} />
          )}

          {att.verifier_comment && (
            <div className="rounded bg-bg-card border border-border-hover px-2 py-1.5">
              <span className="text-[10px] font-semibold text-text-muted uppercase block mb-1">
                Verifier Feedback
              </span>
              <p className="text-xs text-text-secondary whitespace-pre-wrap break-words">
                {att.verifier_comment}
              </p>
            </div>
          )}

          {(hasAgentLogs || hasPrompts) && (
            <div className="flex flex-wrap gap-2">
              {hasAgentLogs && (
                <button
                  type="button"
                  onClick={() => onOpenLogs(att)}
                  className="px-2 py-1 text-[11px] font-medium text-text-muted bg-bg-card border border-border rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors"
                >
                  Agent Log
                </button>
              )}
              {hasPrompts && (
                <button
                  type="button"
                  onClick={() => onOpenPrompts(att)}
                  className="px-2 py-1 text-[11px] font-medium text-text-muted bg-bg-card border border-border rounded-md hover:bg-bg-hover hover:text-text-primary transition-colors"
                >
                  Prompts
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function InspectorPanel({ task, runId, onClose }: InspectorPanelProps) {
  const { data: detail, isLoading } = useTask(runId, task.id);
  const { data: runData } = useRun(runId);
  const { data: activityData } = useActivity(runId);
  const { data: clarificationHistory, error: historyError } = useClarificationHistory(
    runId,
    task.id,
  );
  const [logAttempt, setLogAttempt] = useState<AttemptSchema | null>(null);
  const [promptAttempt, setPromptAttempt] = useState<AttemptSchema | null>(null);
  const [agentLogViewMode, setAgentLogViewMode] = useState<'structured' | 'raw'>('structured');
  const [agentLogCapabilities, setAgentLogCapabilities] = useState({ hasStructured: false, hasRaw: false });
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [retryGuidance, setRetryGuidance] = useState('');
  const recoverRun = useRecoverRun(runId);
  const resumeRun = useResumeRun();
  const canRetry = task.status === 'failed' && (runData?.status === 'failed' || runData?.status === 'paused');

  const handleRetry = useCallback(() => {
    setRetrying(true);
    setRetryError(null);
    recoverRun.mutate(
      {
        target_task_id: task.id,
        guidance: retryGuidance.trim() || undefined,
      },
      {
        onSuccess: () => {
          resumeRun.mutate(
            { runId },
            {
              onSuccess: () => {
                setRetrying(false);
                setRetryGuidance('');
                onClose();
              },
              onError: (err) => {
                setRetrying(false);
                setRetryError(err instanceof Error ? err.message : 'Failed to resume run');
              },
            },
          );
        },
        onError: (err) => {
          setRetrying(false);
          setRetryError(err instanceof Error ? err.message : 'Failed to recover run');
        },
      },
    );
  }, [recoverRun, resumeRun, runId, task.id, retryGuidance, onClose]);
  const isPromptable = task.status === 'building' || task.status === 'verifying';
  const latestAttempt = detail?.attempts[detail.attempts.length - 1];
  const isLatestPrompt = promptAttempt && latestAttempt && promptAttempt.id === latestAttempt.id;
  const needsApiPrompt = Boolean(
    promptAttempt
    && isLatestPrompt
    && isPromptable
    && (!promptAttempt.builder_prompt || !promptAttempt.verifier_prompt),
  );
  const { data: promptData, isLoading: promptLoading, error: promptError } = useTaskPrompt(
    runId,
    needsApiPrompt ? task.id : undefined,
  );

  useEffect(() => {
    if (!logAttempt) return;
    setAgentLogViewMode('structured');
    setAgentLogCapabilities({ hasStructured: false, hasRaw: false });
  }, [logAttempt]);

  const canSwitchAgentLogView = agentLogCapabilities.hasStructured && agentLogCapabilities.hasRaw;
  const storedBuilderPrompt = promptAttempt?.builder_prompt ?? null;
  const storedVerifierPrompt = promptAttempt?.verifier_prompt ?? null;
  const livePrompt = promptData ? `${promptData.system}\n\n${promptData.user}` : null;
  const builderPrompt = storedBuilderPrompt || (promptData?.phase === 'building' ? livePrompt : null);
  const verifierPrompt = storedVerifierPrompt || (promptData?.phase === 'verifying' ? livePrompt : null);
  const taskEvents = useMemo(() => {
    const groups = groupEventsByTask(activityData?.events ?? []);
    const taskGroup = groups.find((group): group is TaskEventGroup => group.kind === 'task' && group.task_id === task.id);
    return taskGroup?.events ?? [];
  }, [activityData?.events, task.id]);
  const fanOutChildren = detail?.fan_out_children ?? [];
  const latestAttemptContext = useMemo(
    () => getLatestAttemptContext(detail?.attempts ?? [], task.status),
    [detail?.attempts, task.status],
  );

  return (
    <div
      className="fixed inset-0 z-50 bg-bg-card overflow-y-auto animate-slide-in-right md:static md:inset-auto md:z-auto md:w-[340px] md:shrink-0 md:border-l md:border-border md:h-full"
      role="complementary"
      aria-label="Task inspector"
    >
      <div className="p-2.5 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wide">
            Inspector
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-bg-hover transition-colors"
            aria-label="Close inspector panel"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="rounded-lg bg-bg-elevated border border-border p-2.5">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-text-muted font-mono">{task.id.slice(0, 8)}</span>
            <TaskStatusBadge status={task.status} />
          </div>
          <h3 className="text-sm font-medium text-text-primary break-words">
            {task.title || task.config_id}
          </h3>
          <p className="text-xs text-text-muted mt-1">
            Attempt {task.current_attempt} of {task.max_attempts}
          </p>
          {fanOutChildren.length > 0 && (
            <div className="mt-2 inline-flex items-center rounded border border-accent-cyan/30 bg-accent-cyan/10 px-2 py-0.5 text-[10px] font-mono text-accent-cyan">
              {fanOutChildren.length} child{fanOutChildren.length === 1 ? '' : 'ren'}
            </div>
          )}
          {canRetry && (
            <div className="mt-2 space-y-2">
              <textarea
                value={retryGuidance}
                onChange={(e) => setRetryGuidance(e.target.value)}
                placeholder="Optional: guidance for the agent on this retry..."
                disabled={retrying}
                rows={3}
                className="w-full rounded-md border border-border-default bg-bg-surface px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:border-accent-purple focus:outline-none focus:ring-1 focus:ring-accent-purple disabled:opacity-50 resize-y"
              />
              <button
                type="button"
                onClick={handleRetry}
                disabled={retrying}
                className="w-full inline-flex items-center justify-center gap-2 px-3 py-1.5 text-xs font-medium text-white bg-accent-purple rounded-md hover:bg-accent-purple/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {retrying ? (
                  <>
                    <Spinner className="h-3.5 w-3.5" />
                    Retrying...
                  </>
                ) : (
                  'Retry Task'
                )}
              </button>
              {retryError && (
                <p className="text-xs text-status-failed">{retryError}</p>
              )}
            </div>
          )}
        </div>

        {isLoading ? (
          <div className="flex justify-center py-6">
            <Spinner className="h-5 w-5" />
          </div>
        ) : detail ? (
          <>
            {detail.checklist.length > 0 && (
              <div>
                <h3 className="text-[11px] font-semibold text-text-secondary uppercase tracking-wide mb-1.5">
                  Requirements
                </h3>
                <ChecklistTable items={detail.checklist} variant="stacked" />
              </div>
            )}

            {fanOutChildren.length > 0 && (
              <InspectorFanOutChildrenSection childTasks={fanOutChildren} runId={runId} />
            )}

            {task.status === 'recovering' && (
              <div className="rounded-lg border-2 border-amber-400/40 bg-amber-500/10 px-3 py-2.5">
                <h4 className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-1">
                  Recovery agent diagnosing issue...
                </h4>
                {detail.attempts.length > 0 && detail.attempts[detail.attempts.length - 1].verifier_comment && (
                  <p className="text-sm text-text-secondary">
                    {detail.attempts[detail.attempts.length - 1].verifier_comment}
                  </p>
                )}
              </div>
            )}

            {latestAttemptContext.latest
              && latestAttemptContext.latest.outcome !== 'passed'
              && !latestAttemptContext.showFailureCard
              && latestAttemptContext.hasAutoVerify
              && !latestAttemptContext.hasFailure
              && (
                <div className="rounded-lg border border-border-default bg-bg-secondary px-3 py-2.5">
                  <h4 className="text-xs font-semibold text-text-secondary uppercase tracking-wide mb-1.5">
                    Auto-verify checks
                  </h4>
                  <AutoVerifyResults results={latestAttemptContext.latest.auto_verify_results ?? []} />
                </div>
              )}

            {latestAttemptContext.showFailureCard && latestAttemptContext.latest && (
              <div className="rounded-lg border-2 border-status-failed/30 bg-status-failed/5 px-3 py-2.5">
                <h4 className="text-xs font-semibold text-status-failed uppercase tracking-wide mb-1.5">
                  Why this failed
                </h4>
                <p className="text-[11px] text-text-muted mb-1.5">
                  Attempt #{latestAttemptContext.latest.attempt_num}
                </p>
                {latestAttemptContext.hasError && (
                  <p className="text-sm text-status-failed mb-2 whitespace-pre-wrap break-words">
                    {latestAttemptContext.latest.error}
                  </p>
                )}
                {latestAttemptContext.hasAutoVerify && (
                  <AutoVerifyResults results={latestAttemptContext.latest.auto_verify_results ?? []} />
                )}
              </div>
            )}

            {latestAttemptContext.showFeedbackCard && latestAttemptContext.latest?.verifier_comment && (
              <div className="rounded-lg border-2 border-accent-purple/30 bg-accent-purple/5 px-3 py-2.5">
                <h4 className="text-xs font-semibold text-accent-purple uppercase tracking-wide mb-1.5">
                  {latestAttemptContext.feedbackTitle}
                </h4>
                <p className="text-sm text-text-secondary whitespace-pre-wrap break-words">
                  {latestAttemptContext.latest.verifier_comment}
                </p>
              </div>
            )}

            {detail.attempts.length === 0 ? (
              <p className="text-xs text-text-muted italic">No attempts yet</p>
            ) : (
              <div className="space-y-2">
                {detail.attempts.map((att, i) => (
                  <InspectorAttemptCard
                    key={att.id}
                    att={att}
                    checklist={detail.checklist}
                    isLatest={i === detail.attempts.length - 1}
                    onOpenLogs={setLogAttempt}
                    onOpenPrompts={setPromptAttempt}
                  />
                ))}
              </div>
            )}

            {taskEvents.length > 0 && (
              <div>
                <h3 className="text-[11px] font-semibold text-text-secondary uppercase tracking-wide mb-1.5">
                  Events
                </h3>
                <div className="space-y-1">
                  {taskEvents.map(ev => {
                    if (ev.event_type === 'clarification_responded') {
                      if (historyError) {
                        return (
                          <div key={ev.id} className="text-xs text-text-muted">
                            Unable to load clarification history.
                          </div>
                        );
                      }

                      const requestId =
                        typeof ev.payload.request_id === 'string'
                          ? ev.payload.request_id
                          : undefined;
                      const matchingIndex = clarificationHistory?.findIndex(
                        item => item.request.id === requestId,
                      );

                      if (matchingIndex !== undefined && matchingIndex >= 0) {
                        const matchingItem = clarificationHistory?.[matchingIndex];
                        if (!matchingItem) {
                          return (
                            <div key={ev.id} className="text-xs text-text-muted">
                              Clarification response recorded
                            </div>
                          );
                        }
                        return (
                          <ClarificationHistoryCard
                            key={ev.id}
                            item={matchingItem}
                            roundNumber={matchingIndex + 1}
                          />
                        );
                      }

                      return (
                        <div key={ev.id} className="text-xs text-text-muted">
                          Clarification response recorded
                        </div>
                      );
                    }

                    const isError = ev.event_type === 'agent_error';
                    return (
                      <div key={ev.id} className="flex items-center gap-2 text-xs">
                        <span className={'w-1.5 h-1.5 rounded-full shrink-0 ' + (isError ? 'bg-status-failed' : 'bg-border')} />
                        <span className={isError ? 'text-status-failed font-medium' : 'text-text-secondary'}>
                          {eventLabel(ev.event_type, ev.payload)}
                        </span>
                        <span className="text-text-muted ml-auto text-[10px] whitespace-nowrap">
                          {formatRelativeTime(ev.timestamp)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        ) : null}
      </div>

      <InspectorModal
        open={Boolean(logAttempt)}
        onClose={() => setLogAttempt(null)}
        title={logAttempt ? `Agent Log · Attempt #${logAttempt.attempt_num}` : 'Agent Log'}
        size="xl"
      >
        {logAttempt && (
          <>
            {canSwitchAgentLogView && (
              <div className="flex justify-end mb-3">
                <div className="relative grid grid-cols-2 w-40 rounded-md border border-border bg-bg-card p-0.5">
                  <span
                    className={
                      'pointer-events-none absolute top-0.5 bottom-0.5 left-0.5 w-[calc(50%-2px)] rounded bg-bg-hover transition-transform duration-200 ease-out ' +
                      (agentLogViewMode === 'raw' ? 'translate-x-full' : 'translate-x-0')
                    }
                  />
                  <button
                    type="button"
                    onClick={() => setAgentLogViewMode('structured')}
                    className={'relative z-10 px-2 py-0.5 text-[10px] rounded transition-colors ' + (agentLogViewMode === 'structured' ? 'text-text-primary font-semibold' : 'text-text-muted hover:text-text-secondary')}
                  >
                    Structured
                  </button>
                  <button
                    type="button"
                    onClick={() => setAgentLogViewMode('raw')}
                    className={'relative z-10 px-2 py-0.5 text-[10px] rounded transition-colors ' + (agentLogViewMode === 'raw' ? 'text-text-primary font-semibold' : 'text-text-muted hover:text-text-secondary')}
                  >
                    Raw
                  </button>
                </div>
              </div>
            )}
            <LogsViewer
              runId={runId}
              taskId={task.id}
              attemptNum={logAttempt.attempt_num}
              viewMode={agentLogViewMode}
              onViewModeChange={setAgentLogViewMode}
              onCapabilitiesChange={setAgentLogCapabilities}
            />
          </>
        )}
      </InspectorModal>

      <InspectorModal
        open={Boolean(promptAttempt)}
        onClose={() => setPromptAttempt(null)}
        title={promptAttempt ? `Prompts · Attempt #${promptAttempt.attempt_num}` : 'Prompts'}
      >
        {promptAttempt && (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-semibold text-text-muted uppercase">Source:</span>
              <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-bg-elevated text-text-secondary">
                {promptData ? 'live prompt' : 'stored attempt prompt'}
              </span>
            </div>

            {promptLoading ? (
              <div className="flex justify-center py-4">
                <Spinner className="h-4 w-4" />
              </div>
            ) : (
              <>
                {builderPrompt && <PromptBlock label="Builder Prompt" text={builderPrompt} />}
                {verifierPrompt && <PromptBlock label="Verifier Prompt" text={verifierPrompt} />}
                {!builderPrompt && !verifierPrompt && (
                  <p className="text-xs text-text-muted italic text-center py-2">
                    {promptError
                      ? 'Prompt unavailable from API for this task state.'
                      : 'No prompts available for this attempt'}
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </InspectorModal>
    </div>
  );
}
