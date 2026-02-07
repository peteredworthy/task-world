import { useState } from 'react';
import { useTask, useTaskPrompt } from '../../hooks/useApi';
import { TaskStatusBadge } from '../StatusBadge';
import { GradeBadge } from '../GradeBadge';
import { Spinner } from '../Spinner';
import { LogsViewer } from './LogsViewer';
import { ChecklistTable } from './ChecklistTable';
import { gradeColor } from '../../lib/status';
import { formatDuration, formatTokens, formatRelativeTime } from '../../lib/format';
import { outcomeColor, outcomeLabel } from '../../lib/outcome';
import { PRIORITY_ORDER, PRIORITY_LABELS, getMetric } from './sharedUtils';
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
    case 'grades_evaluated':
      return payload.passed ? 'Grades passed' : 'Grades failed';
    case 'step_completed':
      return 'Step completed';
    default:
      return eventType.replace(/_/g, ' ');
  }
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'building' || status === 'verifying') {
    return (
      <span
        className={
          'inline-block h-2.5 w-2.5 rounded-full shrink-0 animate-pulse-dot ' +
          (status === 'building' ? 'bg-status-active' : 'bg-accent-purple')
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

/** Get agent icon based on agent type */
function getAgentIcon(agentType: string | null): string {
  switch (agentType) {
    case 'cli_subprocess':
      return '▶';
    case 'openhands_local':
      return '🖐';
    case 'openhands_docker':
      return '🐳';
    case 'user_managed':
      return '👤';
    default:
      return '⚙';
  }
}

/** Format agent type for display */
function formatAgentType(agentType: string | null): string {
  if (!agentType) return 'Unknown';
  return agentType
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
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
          <div key={priority}>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wide">
                {label}
              </span>
              <span className="text-[10px] text-text-muted">
                ({withGrade.length}/{items.length})
              </span>
            </div>
            <div className="space-y-0.5">
              {items.map(item => (
                <div key={item.req_id} className="rounded bg-bg-card border border-border px-2 py-1.5">
                  <div className="flex items-center gap-2">
                    <span className="flex-1 text-xs text-text-secondary truncate">
                      {item.desc}
                    </span>
                    {item.grade ? (
                      <GradeBadge grade={item.grade} />
                    ) : (
                      <span className="text-text-muted text-[10px]">--</span>
                    )}
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
  runId,
  taskId,
}: {
  att: AttemptSchema;
  checklist: ChecklistItemSchema[];
  isLatest: boolean;
  runId: string;
  taskId: string;
}) {
  const [promptsOpen, setPromptsOpen] = useState(false);
  // Lazy-load the builder prompt from the API (only if no inline prompt and user opens section)
  const needsApiPrompt = promptsOpen && !att.builder_prompt;
  const { data: apiPrompt, isLoading: promptLoading } = useTaskPrompt(
    runId,
    needsApiPrompt ? taskId : undefined,
  );

  const durationMs = getMetric(att.metrics, 'duration_ms');
  const tokensRead = getMetric(att.metrics, 'tokens_read');
  const tokensWrite = getMetric(att.metrics, 'tokens_write');
  const totalTokens = tokensRead + tokensWrite;

  return (
    <div
      className={
        'rounded-md border p-3 space-y-3 ' +
        (isLatest ? 'bg-bg-elevated border-border-hover' : 'bg-bg-card border-border')
      }
    >
      {/* Header: attempt number + outcome */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-semibold text-text-primary">
            Attempt #{att.attempt_num}
          </span>
          {att.outcome && (
            <span className={'text-xs font-medium uppercase ' + outcomeColor(att.outcome)}>
              {outcomeLabel(att.outcome)}
            </span>
          )}
        </div>

        {/* Agent info line */}
        {att.agent_type && (
          <div className="flex items-center gap-1.5 text-xs text-text-secondary mb-1.5">
            <span className="text-sm" role="img" aria-label={formatAgentType(att.agent_type)}>
              {getAgentIcon(att.agent_type)}
            </span>
            <span>{formatAgentType(att.agent_type)}</span>
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

        {/* Metrics line */}
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-text-muted">
          {durationMs > 0 && <span>{formatDuration(durationMs)}</span>}
          {tokensRead > 0 && <span>{formatTokens(tokensRead)} read</span>}
          {tokensWrite > 0 && <span>{formatTokens(tokensWrite)} write</span>}
        </div>
      </div>

      {/* Grades for this attempt */}
      {att.grade_snapshot.length > 0 && (
        <AttemptGrades snapshot={att.grade_snapshot} checklist={checklist} />
      )}

      {/* Verifier feedback */}
      {att.verifier_comment && (
        <div className="rounded bg-bg-card border border-border px-2.5 py-2">
          <span className="text-[10px] font-semibold text-text-muted uppercase block mb-1">
            Verifier Feedback
          </span>
          <p className="text-xs text-text-secondary whitespace-pre-wrap">
            {att.verifier_comment}
          </p>
        </div>
      )}

      {/* Agent Logs / Conversation */}
      {att.has_output && (
        <div>
          <h5 className="text-[10px] font-semibold text-text-muted uppercase tracking-wide mb-1">
            Agent Log
          </h5>
          <LogsViewer runId={runId} taskId={taskId} attemptNum={att.attempt_num} />
        </div>
      )}

      {/* Prompts (collapsible) */}
      {(att.builder_prompt || att.verifier_prompt || att.outcome) && (
        <div>
          <button
            onClick={() => setPromptsOpen(!promptsOpen)}
            className="flex items-center gap-1.5 text-[11px] font-semibold text-text-muted uppercase tracking-wide hover:text-text-primary transition-colors"
          >
            <svg
              className={'h-3 w-3 transition-transform ' + (promptsOpen ? 'rotate-90' : '')}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            Prompts
          </button>
          {promptsOpen && (
            <div className="mt-2 space-y-3">
              {promptLoading && (
                <div className="flex justify-center py-3">
                  <Spinner className="h-4 w-4" />
                </div>
              )}
              {att.builder_prompt && (
                <PromptBlock label="Builder Prompt" text={att.builder_prompt} />
              )}
              {!att.builder_prompt && apiPrompt && (
                <>
                  <PromptBlock label="Builder System Prompt" text={apiPrompt.system} />
                  <PromptBlock label="Builder User Prompt" text={apiPrompt.user} />
                </>
              )}
              {att.verifier_prompt && (
                <PromptBlock label="Verifier Prompt" text={att.verifier_prompt} />
              )}
              {!att.builder_prompt && !apiPrompt && !promptLoading && (
                <p className="text-xs text-text-muted italic">No prompts available</p>
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

  const attemptCount = attemptsSummary.length;

  return (
    <div className="rounded-lg border border-border bg-bg-card overflow-hidden transition-colors">
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
          <span className="text-sm font-medium text-text-primary truncate flex-1 min-w-0">
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
            className={'h-4 w-4 text-text-muted shrink-0 transition-transform ' + (expanded ? 'rotate-180' : '')}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-border px-3 py-4 space-y-5 animate-slide-down">
          {isLoading ? (
            <div className="flex justify-center py-6">
              <Spinner className="h-5 w-5" />
            </div>
          ) : detail ? (
            <>
              {/* Requirements Checklist — always visible when expanded */}
              {detail.checklist.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
                    Requirements
                  </h4>
                  <ChecklistTable items={detail.checklist} />
                </div>
              )}

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

              {/* Attempt History — each attempt includes its grades, prompts, and verifier feedback */}
              <div>
                <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
                  Attempts
                </h4>
                {detail.attempts.length === 0 ? (
                  <p className="text-xs text-text-muted italic">No attempts yet</p>
                ) : (
                  <div className="space-y-3">
                    {detail.attempts.map((att, i) => (
                      <AttemptCard
                        key={att.id}
                        att={att}
                        checklist={detail.checklist}
                        isLatest={i === detail.attempts.length - 1}
                        runId={runId}
                        taskId={taskId}
                      />
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : null}

          {/* Event Timeline (always available, uses prop data) */}
          {events.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
                Events
              </h4>
              <div className="space-y-1">
                {events.map(ev => (
                  <div key={ev.id} className="flex items-center gap-2 text-xs">
                    <span className="w-1.5 h-1.5 rounded-full bg-border shrink-0" />
                    <span className="text-text-secondary">
                      {eventLabel(ev.event_type, ev.payload)}
                    </span>
                    <span className="text-text-muted ml-auto text-[10px] whitespace-nowrap">
                      {formatRelativeTime(ev.timestamp)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
