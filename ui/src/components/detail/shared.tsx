import { GradeBadge } from '../GradeBadge';
import { formatDuration, formatTokens } from '../../lib/format';
import { outcomeColor, outcomeLabel } from '../../lib/outcome';
import type { AttemptSchema, ChecklistItemSchema } from '../../types';
import { getMetric, PRIORITY_ORDER, PRIORITY_LABELS } from './sharedUtils';

export function AttemptTimeline({ attempts }: { attempts: AttemptSchema[] }) {
  if (attempts.length === 0) {
    return (
      <p className="text-xs text-text-muted italic">No attempts yet</p>
    );
  }

  return (
    <div className="space-y-2">
      {attempts.map((att, i) => {
        const durationMs = getMetric(att.metrics, 'duration_ms');
        const tokensRead = getMetric(att.metrics, 'tokens_read');
        const tokensWrite = getMetric(att.metrics, 'tokens_write');
        const isLatest = i === attempts.length - 1;

        return (
          <div
            key={att.id}
            className={
              'relative rounded-md border p-3 ' +
              (isLatest
                ? 'bg-bg-elevated border-border-hover'
                : 'bg-bg-card border-border')
            }
          >
            {/* Timeline connector */}
            {i < attempts.length - 1 && (
              <div className="absolute left-5 top-full w-px h-2 bg-border" />
            )}

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

            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-text-muted">
              {durationMs > 0 && (
                <span>{formatDuration(durationMs)}</span>
              )}
              {tokensRead > 0 && (
                <span>{formatTokens(tokensRead)} read</span>
              )}
              {tokensWrite > 0 && (
                <span>{formatTokens(tokensWrite)} write</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function ChecklistGrades({ checklist }: { checklist: ChecklistItemSchema[] }) {
  // Group checklist items by priority
  const grouped = new Map<string, ChecklistItemSchema[]>();
  for (const item of checklist) {
    const key = item.priority.toLowerCase();
    const existing = grouped.get(key);
    if (existing) {
      existing.push(item);
    } else {
      grouped.set(key, [item]);
    }
  }

  const activePriorities = PRIORITY_ORDER.filter(p => grouped.has(p));

  if (activePriorities.length === 0) {
    return <p className="text-xs text-text-muted italic">No requirements</p>;
  }

  return (
    <div className="space-y-3">
      {activePriorities.map(priority => {
        const items = grouped.get(priority) ?? [];
        const label = PRIORITY_LABELS[priority] ?? priority;

        return (
          <div key={priority}>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wide">
                {label}
              </span>
              <span className="text-[10px] text-text-muted">
                ({items.filter(i => i.status === 'done').length}/{items.length})
              </span>
            </div>
            <div className="space-y-1">
              {items.map(item => (
                <div
                  key={item.req_id}
                  className="rounded-md bg-bg-card border border-border px-2.5 py-2"
                >
                  <div className="flex items-center gap-2">
                    {/* Status icon */}
                    {item.status === 'done' ? (
                      <svg className="h-3.5 w-3.5 text-status-completed shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    ) : item.status === 'blocked' ? (
                      <svg className="h-3.5 w-3.5 text-status-failed shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    ) : (
                      <svg className="h-3.5 w-3.5 text-text-muted shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <circle cx="12" cy="12" r="9" />
                      </svg>
                    )}

                    {/* Description */}
                    <span className={'flex-1 text-xs truncate ' + (item.status === 'done' ? 'text-text-secondary' : 'text-text-muted')}>
                      {item.desc}
                    </span>

                    {/* Grade badge */}
                    {item.grade ? (
                      <GradeBadge grade={item.grade} />
                    ) : (
                      <span className="text-text-muted text-[10px]">--</span>
                    )}
                  </div>
                  {/* Grade reason - shown inline */}
                  {item.grade_reason && (
                    <p className="text-[11px] text-text-muted mt-1 ml-5.5">
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
