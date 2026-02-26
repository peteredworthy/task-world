import { useState, type ReactNode } from 'react';
import { useTask, useTaskPrompt } from '../../hooks/useApi';
import { useClarificationHistory } from '../../hooks/useClarifications';
import { TaskStatusBadge } from '../StatusBadge';
import { GradeBadge } from '../GradeBadge';
import { Spinner } from '../Spinner';
import { LogsViewer } from './LogsViewer';
import { ChecklistTable } from './ChecklistTable';
import { ClarificationHistoryCard } from './ClarificationHistoryCard';
import { gradeColor } from '../../lib/status';
import { formatDuration, formatTokens, formatRelativeTime } from '../../lib/format';
import { outcomeColor, outcomeLabel } from '../../lib/outcome';
import {
  PRIORITY_ORDER,
  PRIORITY_LABELS,
  getMetric,
  COLLAPSIBLE_BORDER_CLASS,
  COLLAPSIBLE_DIVIDER_CLASS,
} from './sharedUtils';
import type { ActivityEvent, GradeSummaryItem, AttemptOutcome } from '../../types';
import type { TaskStatus, AttemptSchema, ChecklistItemSchema, GradeSnapshotItem } from '../../types';

interface TaskDetailCardProps {
  taskId: string;
  taskTitle: string;
  stepTitle: string;
  status: string;
  events: ActivityEvent[];
  gradeSummary: GradeSummaryItem[];
  attemptsSummary: AttemptOutcome[];
  runId: string;
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

function StatusIcon({ status }: { status: string }) {
  if (status === 'building' || status === 'verifying' || status === 'recovering') {
    return (
      <span
        className={
          'inline-block h-2.5 w-2.5 rounded-full shrink-0 animate-pulse-dot ' +
          (status === 'building' ? 'bg-status-active' : status === 'recovering' ? 'bg-amber-500' : 'bg-accent-purple')
        }
      />
    );
  }
  if (status === 'completed') {
    return (
      <svg className="h-4 w-4 text-status-completed shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
      </svg>
    );
  }
  if (status === 'failed') {
    return (
      <svg className="h-4 w-4 text-status-failed shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
    );
  }
  return <span className="inline-block h-2.5 w-2.5 rounded-full bg-status-pending shrink-0" />;
}

function CompactGradeBadges({ grades }: { grades: GradeSummaryItem[] }) {
  const withGrade = grades.filter(g => g.grade && g.grade !== '-');
  if (withGrade.length === 0) return null;

  return (
    <div className="flex items-center gap-0.5">
      {withGrade.map((g, i) => (
        <span
          key={i}
          className={'inline-flex w-5 h-5 items-center justify-center rounded text-[10px] font-bold ' + gradeColor(g.grade!)}
          title={`${g.priority}: ${g.grade}`}
        >
          {g.grade}
        </span>
      ))}
    </div>
  );
}

/** Format agent type for display */
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

function DisclosureHeader({
  label,
  open,
  onToggle,
  meta,
  connected = false,
  actions,
  borderClass = COLLAPSIBLE_BORDER_CLASS,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  meta?: string;
  connected?: boolean;
  actions?: ReactNode;
  borderClass?: string;
}) {
  const baseClass = connected
    ? `group w-full cursor-pointer border ${borderClass} bg-bg-card/60 px-2.5 py-1.5 text-left hover:bg-bg-hover/40 hover:border-border-hover transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-cyan/40 ` + (open ? 'rounded-t-md rounded-b-none border-b-0' : 'rounded-md')
    : `group w-full cursor-pointer rounded-md border ${borderClass} bg-bg-card/60 px-2.5 py-1.5 text-left hover:bg-bg-hover/40 hover:border-border-hover transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-cyan/40`;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onToggle();
        }
      }}
      aria-expanded={open}
      className={baseClass}
    >
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-semibold text-text-secondary uppercase tracking-wide">
          {label}
        </span>
        {meta && (
          <span className="text-[10px] text-text-muted">{meta}</span>
        )}
        {actions && (
          <div
            className="ml-auto"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            {actions}
          </div>
        )}
        <svg
          className={'h-3.5 w-3.5 text-text-muted shrink-0 transition-transform ' + (actions ? 'ml-2 ' : 'ml-auto ') + (open ? 'rotate-90' : '')}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </div>
    </div>
  );
}

/** Render a collapsible monospace prompt block. */
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
      <pre className="text-xs text-text-secondary bg-bg-card border border-border rounded-md p-3 overflow-x-auto max-h-60 overflow-y-auto font-mono whitespace-pre-wrap">
        {text}
      </pre>
    </div>
  );
}

/** Concise failure summary showing why an attempt failed. */
function FailureSummary({
  snapshot,
  checklist,
}: {
  snapshot: GradeSnapshotItem[];
  checklist: ChecklistItemSchema[];
}) {
  const checklistMap = new Map(checklist.map(c => [c.req_id, c]));

  const issues: { reqId: string; desc: string; reason: string }[] = [];
  for (const gs of snapshot) {
    const cl = checklistMap.get(gs.req_id);
    const desc = cl?.desc ?? gs.req_id;
    const priority = cl?.priority ?? 'expected';

    if (gs.grade === null) {
      issues.push({ reqId: gs.req_id, desc, reason: `Not graded (${priority})` });
    } else if (priority === 'critical' && gs.grade !== 'A') {
      issues.push({ reqId: gs.req_id, desc, reason: `Grade ${gs.grade} below A` });
    } else if (priority === 'expected' && gs.grade !== 'A' && gs.grade !== 'B') {
      issues.push({ reqId: gs.req_id, desc, reason: `Grade ${gs.grade} below B` });
    }
  }

  if (issues.length === 0) return null;

  return (
    <div className="rounded bg-status-failed/10 border border-status-failed/30 px-2.5 py-2">
      <span className="text-[10px] font-semibold text-status-failed uppercase block mb-1">
        Why verification failed
      </span>
      <ul className="space-y-0.5">
        {issues.map(i => (
          <li key={i.reqId} className="text-xs text-text-secondary">
            <span className="text-status-failed font-medium">{i.reqId}</span>
            {' '}{i.desc} — <span className="text-text-muted">{i.reason}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Display auto-verify check results. */
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

/** Grade table for a single attempt's grade snapshot, enriched with checklist descriptions. */
function AttemptGrades({
  snapshot,
  checklist,
}: {
  snapshot: GradeSnapshotItem[];
  checklist: ChecklistItemSchema[];
}) {
  if (snapshot.length === 0) return null;

  // Build a lookup from req_id → checklist item for desc + priority
  const checklistMap = new Map(checklist.map(c => [c.req_id, c]));

  // Enrich snapshot items with checklist metadata
  const enriched = snapshot.map(gs => ({
    ...gs,
    desc: checklistMap.get(gs.req_id)?.desc ?? gs.req_id,
    priority: (checklistMap.get(gs.req_id)?.priority ?? 'expected').toLowerCase(),
  }));

  // Group by priority
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
              {items.map(item => (
                <div key={item.req_id} className="rounded bg-bg-card border border-border px-2 py-1.5">
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
                  {item.grade_reason && (
                    <p className="text-[11px] text-text-muted mt-1 pl-0.5">
                      {item.grade_reason}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** A single attempt card with grades, prompts, and verifier feedback. */
function AttemptCard({
  att,
  checklist,
  isLatest,
  taskStatus,
  runId,
  taskId,
}: {
  att: AttemptSchema;
  checklist: ChecklistItemSchema[];
  isLatest: boolean;
  taskStatus: string;
  runId: string;
  taskId: string;
}) {
  const [open, setOpen] = useState(false);
  const [promptsOpen, setPromptsOpen] = useState(false);
  const [agentLogOpen, setAgentLogOpen] = useState(false);
  const [agentLogViewMode, setAgentLogViewMode] = useState<'structured' | 'raw'>('structured');
  const [agentLogCapabilities, setAgentLogCapabilities] = useState({ hasStructured: false, hasRaw: false });
  // Lazy-load the live prompt from the API only for the active attempt in a promptable state
  const isPromptable = taskStatus === 'building' || taskStatus === 'verifying';
  const needsApiPrompt = promptsOpen && isLatest && isPromptable && (!att.builder_prompt || !att.verifier_prompt);
  const { data: apiPrompt, isLoading: promptLoading } = useTaskPrompt(
    runId,
    needsApiPrompt ? taskId : undefined,
  );

  const durationMs = getMetric(att.metrics, 'duration_ms');
  const tokensRead = getMetric(att.metrics, 'tokens_read');
  const tokensWrite = getMetric(att.metrics, 'tokens_write');
  const totalTokens = tokensRead + tokensWrite;
  const hasAgentLogs = att.has_output || att.has_action_log;
  const hasPrompts = Boolean(att.builder_prompt || att.verifier_prompt || att.outcome);
  const canSwitchAgentLogView = agentLogCapabilities.hasStructured && agentLogCapabilities.hasRaw;
  const hasBodyContent = Boolean(
    att.error
    || (att.outcome && att.outcome !== 'passed' && att.grade_snapshot.length > 0)
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
        className="w-full text-left px-3 py-2.5 hover:bg-bg-hover/30 transition-colors"
      >
        <div className="flex items-start gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-text-primary">
                Attempt #{att.attempt_num}
              </span>
              {att.outcome ? (
                <span className={'text-[10px] font-semibold uppercase rounded px-1.5 py-0.5 bg-bg-card border border-border ' + outcomeColor(att.outcome)}>
                  {outcomeLabel(att.outcome)}
                </span>
              ) : !isLatest ? (
                <span className="text-[10px] font-semibold uppercase rounded px-1.5 py-0.5 bg-bg-card border border-border text-text-muted">
                  Interrupted
                </span>
              ) : null}
            </div>

            {att.agent_type && (
              <div className="flex items-center gap-1.5 text-xs text-text-secondary mb-1.5">
                <span>Agent:</span>
                <span className="font-medium text-text-primary">{getAgentDisplayName(att)}</span>
                {att.agent_model && (
                  <>
                    <span className="text-text-muted">·</span>
                    <span className="text-text-muted">{att.agent_model}</span>
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
        <div className={`border-t ${COLLAPSIBLE_DIVIDER_CLASS} p-3 space-y-3`}>
          {/* Error banner */}
          {att.error && (
            <div className="rounded bg-status-failed/10 border border-status-failed/30 px-2.5 py-2">
              <span className="text-[10px] font-semibold text-status-failed uppercase block mb-1">
                Error
              </span>
              <p className="text-xs text-status-failed whitespace-pre-wrap">{att.error}</p>
            </div>
          )}

          {/* Failure summary — show when outcome is not passed and there are ungraded/failing items */}
          {att.outcome && att.outcome !== 'passed' && att.grade_snapshot.length > 0 && (
            <FailureSummary snapshot={att.grade_snapshot} checklist={checklist} />
          )}

          {/* Grades for this attempt */}
          {att.grade_snapshot.length > 0 && (
            <AttemptGrades snapshot={att.grade_snapshot} checklist={checklist} />
          )}

          {/* Auto-verify results */}
          {att.auto_verify_results && att.auto_verify_results.length > 0 && (
            <AutoVerifyResults results={att.auto_verify_results} />
          )}

          {/* Verifier feedback */}
          {att.verifier_comment && (
            <div className="rounded bg-bg-card border border-border-hover px-2.5 py-2">
              <span className="text-[10px] font-semibold text-text-muted uppercase block mb-1">
                Verifier Feedback
              </span>
              <p className="text-xs text-text-secondary whitespace-pre-wrap">
                {att.verifier_comment}
              </p>
            </div>
          )}

          {/* Agent Logs / Conversation */}
          {hasAgentLogs && (
            <div>
              <DisclosureHeader
                label="Agent Log"
                open={agentLogOpen}
                onToggle={() => setAgentLogOpen(!agentLogOpen)}
                connected
                borderClass={COLLAPSIBLE_BORDER_CLASS}
                actions={canSwitchAgentLogView ? (
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
                ) : undefined}
              />
              {agentLogOpen && (
                <div className={`border-x border-b ${COLLAPSIBLE_BORDER_CLASS} rounded-b-md`}>
                  <LogsViewer
                    runId={runId}
                    taskId={taskId}
                    attemptNum={att.attempt_num}
                    viewMode={agentLogViewMode}
                    onViewModeChange={setAgentLogViewMode}
                    onCapabilitiesChange={setAgentLogCapabilities}
                  />
                </div>
              )}
            </div>
          )}

          {/* Prompts (collapsible) */}
          {hasPrompts && (
            <div>
              <DisclosureHeader
                label="Prompts"
                open={promptsOpen}
                onToggle={() => setPromptsOpen(!promptsOpen)}
                connected
                borderClass={COLLAPSIBLE_BORDER_CLASS}
              />
              {promptsOpen && (
                <div className={`border-x border-b ${COLLAPSIBLE_BORDER_CLASS} rounded-b-md p-2.5 space-y-3`}>
                  {promptLoading && (
                    <div className="flex justify-center py-3">
                      <Spinner className="h-4 w-4" />
                    </div>
                  )}
                  {/* Builder prompt: stored, or live API when phase is building */}
                  {att.builder_prompt ? (
                    <PromptBlock label="Builder Prompt" text={att.builder_prompt} />
                  ) : apiPrompt?.phase === 'building' ? (
                    <PromptBlock label="Builder Prompt" text={apiPrompt.system + '\n\n' + apiPrompt.user} />
                  ) : null}
                  {/* Verifier prompt: stored, or live API when phase is verifying */}
                  {att.verifier_prompt ? (
                    <PromptBlock label="Verifier Prompt" text={att.verifier_prompt} />
                  ) : apiPrompt?.phase === 'verifying' ? (
                    <PromptBlock label="Verifier Prompt" text={apiPrompt.system + '\n\n' + apiPrompt.user} />
                  ) : null}
                  {!att.builder_prompt && !att.verifier_prompt && !apiPrompt && !promptLoading && (
                    <p className="text-xs text-text-muted italic">No prompts available</p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function TaskDetailCard({
  taskId,
  taskTitle,
  stepTitle,
  status,
  events,
  gradeSummary,
  attemptsSummary,
  runId,
}: TaskDetailCardProps) {
  const [expanded, setExpanded] = useState(false);
  const { data: detail, isLoading } = useTask(runId, expanded ? taskId : undefined);
  const { data: clarificationHistory, error: historyError } = useClarificationHistory(
    runId,
    taskId,
  );

  const attemptCount = attemptsSummary.length;

  return (
    <div className={`rounded-lg border ${COLLAPSIBLE_BORDER_CLASS} bg-bg-card overflow-hidden transition-colors`}>
      {/* Collapsed bar */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left px-3 py-2.5 hover:bg-bg-hover transition-colors"
        aria-expanded={expanded}
        aria-label={'Toggle details for task: ' + taskTitle}
      >
        <div className="flex items-center gap-2">
          {/* Status icon */}
          <StatusIcon status={status} />

          {/* Task title */}
          <span className="text-sm font-medium text-text-primary truncate flex-1 min-w-0" title={taskTitle}>
            {taskTitle}
          </span>

          {/* Step title */}
          {stepTitle && (
            <span className="text-[10px] text-text-muted shrink-0 hidden sm:inline">
              {stepTitle}
            </span>
          )}

          {/* Compact grade badges */}
          <CompactGradeBadges grades={gradeSummary} />

          {/* Attempt count */}
          {attemptCount > 1 && (
            <span className="text-[11px] text-status-paused font-mono shrink-0">
              x{attemptCount}
            </span>
          )}

          {/* Status badge */}
          <TaskStatusBadge status={status as TaskStatus} />

          {/* Chevron */}
          <svg
            className={'h-4 w-4 text-text-muted shrink-0 transition-transform ' + (expanded ? 'rotate-90' : '')}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className={`border-t ${COLLAPSIBLE_DIVIDER_CLASS} px-3 py-4 space-y-5 animate-slide-down`}>
          {isLoading ? (
            <div className="flex justify-center py-6">
              <Spinner className="h-5 w-5" />
            </div>
          ) : detail ? (
            <>
              {/* Requirements Checklist — always visible when expanded */}
              {detail.checklist.length > 0 && (
                <div>
                  <h4 className="text-[11px] font-semibold text-text-secondary uppercase tracking-wide mb-2">
                    Requirements
                  </h4>
                  <ChecklistTable items={detail.checklist} />
                </div>
              )}

              {/* Recovery banner — shown when task is in RECOVERING state */}
              {status === 'recovering' && (
                <div className="rounded-lg border-2 border-amber-400/40 bg-amber-500/10 px-3 py-2.5">
                  <h4 className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-1">
                    Recovery agent diagnosing issue\u2026
                  </h4>
                  {detail.attempts.length > 0 && detail.attempts[detail.attempts.length - 1].verifier_comment && (
                    <p className="text-sm text-text-secondary">
                      {detail.attempts[detail.attempts.length - 1].verifier_comment}
                    </p>
                  )}
                </div>
              )}

              {/* Failure summary — shown prominently when task failed or has revision */}
              {detail.attempts.length > 0 && (() => {
                const latest = detail.attempts[detail.attempts.length - 1];
                if (latest.outcome === 'passed') return null;
                const hasFailure = latest.error || latest.grade_snapshot.some(g => g.grade === null || (g.grade !== 'A' && g.grade !== 'B'));
                if (!hasFailure) return null;
                return (
                  <div className="rounded-lg border-2 border-status-failed/30 bg-status-failed/5 px-3 py-2.5">
                    <h4 className="text-xs font-semibold text-status-failed uppercase tracking-wide mb-1.5">
                      Why this failed
                    </h4>
                    {latest.error && (
                      <p className="text-sm text-status-failed mb-2">{latest.error}</p>
                    )}
                    <FailureSummary snapshot={latest.grade_snapshot} checklist={detail.checklist} />
                    {latest.auto_verify_results && latest.auto_verify_results.length > 0 && (
                      <div className="mt-2">
                        <AutoVerifyResults results={latest.auto_verify_results} />
                      </div>
                    )}
                  </div>
                );
              })()}

              {/* Verifier Feedback — shown prominently if latest attempt has feedback */}
              {detail.attempts.length > 0 && detail.attempts[detail.attempts.length - 1].verifier_comment && (
                <div className="rounded-lg border-2 border-accent-purple/30 bg-accent-purple/5 px-3 py-2.5">
                  <h4 className="text-xs font-semibold text-accent-purple uppercase tracking-wide mb-1.5">
                    Verifier Feedback
                  </h4>
                  <p className="text-sm text-text-secondary whitespace-pre-wrap">
                    {detail.attempts[detail.attempts.length - 1].verifier_comment}
                  </p>
                </div>
              )}

              {/* Attempt History */}
              {detail.attempts.length === 0 ? (
                <p className="text-xs text-text-muted italic">No attempts yet</p>
              ) : (
                <div className="space-y-2">
                  {detail.attempts.map((att, i) => (
                    <AttemptCard
                      key={att.id}
                      att={att}
                      checklist={detail.checklist}
                      isLatest={i === detail.attempts.length - 1}
                      taskStatus={status}
                      runId={runId}
                      taskId={taskId}
                    />
                  ))}
                </div>
              )}
            </>
          ) : null}

          {/* Event Timeline (always available, uses prop data) */}
          {events.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
                Events
              </h4>
              <div className="space-y-1">
                {events.map(ev => {
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
        </div>
      )}
    </div>
  );
}
