import { TaskStatusBadge } from '../StatusBadge';
import { CompactGradeRow } from '../CompactGradeRow';
import type { TaskSummary } from '../../types';

interface TaskCardProps {
  runId: string;
  task: TaskSummary;
  taskTitle: string;
  isSelected?: boolean;
  onSelect?: (task: TaskSummary) => void;
}

function hasFailures(task: TaskSummary): boolean {
  return task.status === 'failed' || task.current_attempt > 1;
}

export function TaskCard({ task, taskTitle, isSelected, onSelect }: TaskCardProps) {
  const failed = hasFailures(task);
  const hasPendingAction = task.pending_action_type !== null;

  // Left border color: yellow for pending actions, orange for retried tasks, red for failed, accent-purple when selected
  let leftBorderClass = 'border-l-2 border-l-transparent';
  if (hasPendingAction) {
    leftBorderClass = 'border-l-2 border-l-yellow-600';
  } else if (failed && task.status === 'failed') {
    leftBorderClass = 'border-l-2 border-l-status-failed';
  } else if (failed) {
    leftBorderClass = 'border-l-2 border-l-status-paused';
  } else if (isSelected) {
    leftBorderClass = 'border-l-2 border-l-accent-purple';
  }

  return (
    <button
      onClick={() => onSelect?.(task)}
      className={
        'w-full flex items-center justify-between px-3 py-2.5 rounded-md text-left transition-colors ' +
        leftBorderClass + ' ' +
        (isSelected
          ? 'bg-accent-purple/10 border border-accent-purple/30'
          : 'bg-bg-card border border-border hover:bg-bg-hover hover:border-border-hover')
      }
      aria-label={'Select task: ' + taskTitle}
      aria-pressed={isSelected}
    >
      <div className="flex items-center gap-2 min-w-0">
        {/* Status dot or pending action icon */}
        {hasPendingAction ? (
          <svg className="h-3.5 w-3.5 text-yellow-600 shrink-0" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
          </svg>
        ) : task.status === 'building' || task.status === 'verifying' ? (
          <span className={
            'inline-block h-2 w-2 rounded-full shrink-0 animate-pulse-dot ' +
            (task.status === 'building' ? 'bg-status-active' : 'bg-accent-purple')
          } />
        ) : task.status === 'completed' ? (
          <svg className="h-3.5 w-3.5 text-status-completed shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        ) : task.status === 'failed' ? (
          <svg className="h-3.5 w-3.5 text-status-failed shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        ) : (
          <span className="inline-block h-2 w-2 rounded-full bg-status-pending shrink-0" />
        )}

        <span className={
          'text-sm font-medium truncate ' +
          (isSelected ? 'text-text-primary' : 'text-text-secondary')
        }>
          {taskTitle}
        </span>
        {hasPendingAction && (
          <span className="text-[10px] font-semibold text-yellow-600 uppercase tracking-wide shrink-0">
            {task.pending_action_type === 'clarification' ? 'Answer needed' : 'Review needed'}
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 ml-2 shrink-0">
        {task.grade_summary.length > 0 && (
          <CompactGradeRow grades={task.grade_summary} />
        )}
        {task.current_attempt > 1 && (
          <span className="text-[11px] text-status-paused font-mono">
            x{task.current_attempt}
          </span>
        )}
        <span className="text-[11px] text-text-muted font-mono">
          {task.current_attempt}/{task.max_attempts}
        </span>
        <TaskStatusBadge status={task.status} />
      </div>
    </button>
  );
}
