import { useTask } from '../../hooks/useApi';
import { TaskStatusBadge } from '../StatusBadge';
import { Spinner } from '../Spinner';
import { AttemptTimeline } from './shared';
import type { TaskSummary } from '../../types';

interface InspectorPanelProps {
  task: TaskSummary;
  runId: string;
  onClose: () => void;
}

export function InspectorPanel({ task, runId, onClose }: InspectorPanelProps) {
  const { data: detail, isLoading } = useTask(runId, task.id);

  return (
    <div
      className="fixed inset-0 z-50 bg-bg-card overflow-y-auto animate-slide-in-right md:static md:inset-auto md:z-auto md:w-[340px] md:shrink-0 md:border-l md:border-border md:h-full"
      role="complementary"
      aria-label="Task inspector"
    >
      <div className="p-4 space-y-5">
        {/* Header */}
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

        {/* Selected Task Card */}
        <div className="rounded-lg bg-bg-elevated border border-border p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-text-muted font-mono">{task.id.slice(0, 8)}</span>
            <TaskStatusBadge status={task.status} />
          </div>
          <h3 className="text-sm font-medium text-text-primary">{task.title || task.config_id}</h3>
          <p className="text-xs text-text-muted mt-1">
            Attempt {task.current_attempt} of {task.max_attempts}
          </p>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-6">
            <Spinner className="h-5 w-5" />
          </div>
        ) : detail ? (
          <>
            {/* Attempt History */}
            <div>
              <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
                Attempt History
              </h3>
              <AttemptTimeline attempts={detail.attempts} checklist={detail.checklist} />
            </div>
          </>
        ) : null}

      </div>
    </div>
  );
}
