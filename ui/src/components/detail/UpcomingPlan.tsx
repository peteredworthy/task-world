import type { UpcomingTask } from '../../lib/activity';

interface UpcomingPlanProps {
  tasks: UpcomingTask[];
  onSelectTask?: (taskId: string) => void;
}

/**
 * Groups upcoming tasks by step and renders them in a muted/dashed style
 * to distinguish from the primary activity feed above.
 */
export function UpcomingPlan({ tasks, onSelectTask }: UpcomingPlanProps) {
  if (tasks.length === 0) return null;

  // Group by step_id preserving order
  const stepGroups: { step_title: string; step_index: number; tasks: UpcomingTask[] }[] = [];
  const stepMap = new Map<string, (typeof stepGroups)[number]>();

  for (const task of tasks) {
    let group = stepMap.get(task.step_id);
    if (!group) {
      group = { step_title: task.step_title, step_index: task.step_index, tasks: [] };
      stepMap.set(task.step_id, group);
      stepGroups.push(group);
    }
    group.tasks.push(task);
  }

  return (
    <div>
      <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-3">
        Upcoming
      </h3>
      <div className="space-y-3">
        {stepGroups.map(group => (
          <div
            key={group.step_title + group.step_index}
            className="rounded-lg border border-dashed border-border bg-bg-card/50 p-3"
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-bold border border-border text-text-muted">
                S{group.step_index + 1}
              </span>
              <span className="text-xs font-semibold text-text-muted">
                {group.step_title}
              </span>
            </div>
            <div className="space-y-1">
              {group.tasks.map(task => {
                const isSelectable = !!onSelectTask;
                const Wrapper = isSelectable ? 'button' : 'div';
                const wrapperProps = isSelectable
                  ? {
                      onClick: () => onSelectTask!(task.task_id),
                      'aria-label': 'Select upcoming task: ' + task.task_title,
                    }
                  : {};

                return (
                  <Wrapper
                    key={task.task_id}
                    {...wrapperProps}
                    className={
                      'w-full flex items-center gap-2 px-2.5 py-2 rounded-md text-left border border-dashed border-border/60 transition-colors' +
                      (isSelectable ? ' hover:bg-bg-hover hover:border-border-hover' : '')
                    }
                  >
                    <span className="inline-block h-2 w-2 rounded-full bg-status-pending/40 shrink-0" />
                    <span className="text-sm text-text-muted truncate">
                      {task.task_title}
                    </span>
                  </Wrapper>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
