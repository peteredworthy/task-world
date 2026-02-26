import type { ChecklistItemSchema, ChecklistStatus } from '../../types';
import { checklistStatusColor, gradeColor } from '../../lib/status';
import { PriorityBadge } from '../PriorityBadge';
import { GradeBadge } from '../GradeBadge';
import { isGradeFailing } from './sharedUtils';

function StatusIcon({ status }: { status: ChecklistStatus }) {
  const color = checklistStatusColor(status);
  if (status === 'done') {
    return (
      <svg className={'h-4 w-4 ' + color} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
      </svg>
    );
  }
  if (status === 'blocked') {
    return (
      <svg className={'h-4 w-4 ' + color} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
    );
  }
  if (status === 'not_applicable') {
    return (
      <svg className={'h-4 w-4 ' + color} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14" />
      </svg>
    );
  }
  return (
    <svg className={'h-4 w-4 ' + color} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <circle cx="12" cy="12" r="9" />
    </svg>
  );
}

const STACKED_PRIORITY_ORDER = ['critical', 'expected', 'nice'] as const;

const STACKED_PRIORITY_LABELS: Record<string, string> = {
  critical: 'Critical',
  expected: 'Expected',
  nice: 'Nice to',
};

function CompactGradeMarker({ grade }: { grade: string }) {
  return (
    <span
      className={
        'inline-flex h-5 w-5 items-center justify-center rounded text-[9px] font-bold ' +
        gradeColor(grade)
      }
      title={`Grade ${grade}`}
    >
      {grade}
    </span>
  );
}

function ChecklistLeftMarker({ item }: { item: ChecklistItemSchema }) {
  if (item.grade) {
    return <CompactGradeMarker grade={item.grade} />;
  }

  if (item.status === 'done') {
    return <StatusIcon status="done" />;
  }

  return <StatusIcon status={item.status} />;
}

interface ChecklistTableProps {
  items: ChecklistItemSchema[];
  variant?: 'table' | 'stacked';
}

export function ChecklistTable({ items, variant = 'table' }: ChecklistTableProps) {
  if (items.length === 0) {
    return <p className="text-sm text-text-muted italic">No checklist items</p>;
  }

  if (variant === 'stacked') {
    const grouped = new Map<string, ChecklistItemSchema[]>();
    for (const item of items) {
      const key = item.priority.toLowerCase();
      const list = grouped.get(key);
      if (list) list.push(item);
      else grouped.set(key, [item]);
    }
    const priorities = STACKED_PRIORITY_ORDER.filter(priority => grouped.has(priority));

    return (
      <div className="space-y-2">
        {priorities.map(priority => {
          const groupItems = grouped.get(priority) ?? [];
          const gradedCount = groupItems.filter(item => item.grade).length;

          return (
            <div key={priority} className="rounded-md border border-border bg-bg-card/40 overflow-hidden">
              <div className="flex items-center gap-2 px-2 py-1 border-b border-border/60 bg-bg-elevated/40">
                <span className="text-[11px] font-semibold text-text-secondary">
                  {STACKED_PRIORITY_LABELS[priority] ?? priority}
                </span>
                <span className="text-[10px] text-text-muted">
                  {gradedCount}/{groupItems.length} graded
                </span>
              </div>
              <div>
                {groupItems.map((item, index) => {
                  const failing = item.grade ? isGradeFailing(item.grade, item.priority) : false;
                  return (
                    <div
                      key={item.req_id}
                      className={
                        'px-2 py-1.5 ' +
                        (index > 0 ? 'border-t border-border/50 ' : '') +
                        (failing ? 'bg-status-failed/5' : '')
                      }
                    >
                      <div className="grid grid-cols-[20px_minmax(0,1fr)] gap-x-2 items-start">
                        <div className="pt-0.5 flex h-5 items-center justify-center">
                          <ChecklistLeftMarker item={item} />
                        </div>
                        <div className="min-w-0">
                          <div className="text-xs text-text-secondary break-words leading-snug">
                            {item.desc}
                          </div>
                          {(item.grade_reason || item.note || failing) && (
                            <div className="mt-0.5 flex flex-wrap items-center gap-x-1 text-[10px] text-text-muted break-words">
                              {item.grade_reason && (
                                <span className="text-text-secondary">{item.grade_reason}</span>
                              )}
                              {item.grade_reason && item.note && <span>·</span>}
                              {item.note && <span>{item.note}</span>}
                              {failing && (
                                <span className="ml-auto shrink-0 font-semibold uppercase tracking-wide text-status-failed">
                                  Failed
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
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

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-text-muted border-b border-border">
            <th className="pb-2 w-8"></th>
            <th className="pb-2">Requirement</th>
            <th className="pb-2 w-20">Priority</th>
            <th className="pb-2 w-16">Grade</th>
            <th className="pb-2">Note</th>
          </tr>
        </thead>
        <tbody>
          {items.map(item => {
            const failing = item.grade ? isGradeFailing(item.grade, item.priority) : false;
            return (
              <tr key={item.req_id} className={`border-b ${failing ? 'border-status-failed/30 bg-status-failed/5' : 'border-border/50'}`}>
                <td className="py-1.5">
                  <StatusIcon status={item.status} />
                </td>
                <td className="py-1.5 text-text-secondary">{item.desc}</td>
                <td className="py-1.5">
                  <PriorityBadge priority={item.priority} />
                </td>
                <td className="py-1.5">
                  {item.grade ? (
                    <GradeBadge grade={item.grade} />
                  ) : (
                    <span className="text-text-muted">-</span>
                  )}
                </td>
                <td className="py-1.5 text-text-muted text-xs">
                  {item.grade_reason && (
                    <span className="text-text-secondary">{item.grade_reason}</span>
                  )}
                  {item.grade_reason && item.note && <span className="mx-1">·</span>}
                  {item.note || ''}
                  {failing && (
                    <span className={`${item.grade_reason || item.note ? 'ml-2' : ''} text-[10px] font-semibold text-status-failed uppercase tracking-wide`}>Failed</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
