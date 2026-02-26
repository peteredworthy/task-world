import type { ChecklistItemSchema, ChecklistStatus } from '../../types';
import { checklistStatusColor } from '../../lib/status';
import { PriorityBadge } from '../PriorityBadge';
import { GradeBadge } from '../GradeBadge';

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

interface ChecklistTableProps {
  items: ChecklistItemSchema[];
  variant?: 'table' | 'stacked';
}

export function ChecklistTable({ items, variant = 'table' }: ChecklistTableProps) {
  if (items.length === 0) {
    return <p className="text-sm text-text-muted italic">No checklist items</p>;
  }

  if (variant === 'stacked') {
    return (
      <div className="space-y-2">
        {items.map(item => (
          <div key={item.req_id} className="rounded-md border border-border bg-bg-card/40 p-2">
            <div className="flex items-start gap-2">
              <div className="pt-0.5">
                <StatusIcon status={item.status} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs text-text-secondary break-words">
                  {item.desc}
                </div>
                <div className="flex flex-wrap items-center gap-2 mt-1">
                  <PriorityBadge priority={item.priority} />
                  {item.grade ? (
                    <GradeBadge grade={item.grade} />
                  ) : (
                    <span className="text-[11px] text-text-muted">-</span>
                  )}
                </div>
                {(item.grade_reason || item.note) && (
                  <div className="text-[11px] text-text-muted mt-1 break-words">
                    {item.grade_reason && (
                      <span className="text-text-secondary">{item.grade_reason}</span>
                    )}
                    {item.grade_reason && item.note && <span className="mx-1">·</span>}
                    {item.note || ''}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
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
          {items.map(item => (
            <tr key={item.req_id} className="border-b border-border/50">
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
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
