import { TaskStatusBadge } from '../StatusBadge';
import { formatRelativeTime } from '../../lib/format';
import { groupEventsByTask } from '../../lib/activity';
import { TaskDetailCard } from './TaskDetailCard';
import type { ActivityEvent, TaskSummary, RunResponse } from '../../types';
import type { ActiveTask, ActivityGroup, TaskEventGroup, MilestoneEvent } from '../../lib/activity';

interface ActivityFeedProps {
  events: ActivityEvent[];
  activeTasks?: ActiveTask[];
  onSelectTask?: (taskId: string) => void;
  selectedTaskId?: string | null;
  run?: RunResponse;
}

function eventLabel(eventType: string, payload: Record<string, unknown>): string {
  switch (eventType) {
    case 'task_status_changed': {
      const oldS = payload.old_status as string | undefined;
      const newS = payload.new_status as string | undefined;
      if (oldS && newS) return `${oldS} \u2192 ${newS}`;
      return 'status changed';
    }
    case 'run_status_changed': {
      const oldS = payload.old_status as string | undefined;
      const newS = payload.new_status as string | undefined;
      if (oldS && newS) {
        return `Run ${oldS} \u2192 ${newS}`;
      }
      if (newS) {
        return `Run ${newS}`;
      }
      return 'Run status changed';
    }
    case 'checklist_gate_evaluated':
      return payload.passed ? 'Gate passed' : 'Gate blocked';
    case 'grades_evaluated':
      return payload.passed ? 'Grades passed' : 'Grades failed';
    case 'step_completed':
      return 'Step completed';
    case 'agent_error':
      return (payload.error_message as string) || 'Agent error';
    default:
      return eventType.replace(/_/g, ' ');
  }
}

function statusFromPayload(payload: Record<string, unknown>): string | null {
  return (payload.new_status as string) ?? null;
}

function MilestoneRow({ item }: { item: MilestoneEvent }) {
  const { event } = item;
  const label = eventLabel(event.event_type, event.payload);

  return (
    <div className="flex items-center gap-3 py-2">
      <div className="flex-1 h-px bg-border" />
      <span className="text-[11px] font-semibold text-text-muted uppercase tracking-wide whitespace-nowrap">
        {label}
      </span>
      <span className="text-[10px] text-text-muted whitespace-nowrap">
        {formatRelativeTime(event.timestamp)}
      </span>
      <div className="flex-1 h-px bg-border" />
    </div>
  );
}

function TaskGroupCard({
  group,
  isSelected,
  onSelect,
}: {
  group: TaskEventGroup;
  isSelected: boolean;
  onSelect?: () => void;
}) {
  // Determine current status from the last task_status_changed event
  const lastStatusEvent = [...group.events]
    .reverse()
    .find(e => e.event_type === 'task_status_changed');
  const currentStatus = lastStatusEvent
    ? statusFromPayload(lastStatusEvent.payload)
    : null;

  // Count attempts (number of pending->building transitions)
  const attemptCount = group.events.filter(
    e =>
      e.event_type === 'task_status_changed' &&
      e.payload.new_status === 'building',
  ).length;

  const isSelectable = !!onSelect;
  const Wrapper = isSelectable ? 'button' : 'div';

  const wrapperProps = isSelectable
    ? {
        onClick: onSelect,
        'aria-label': 'Select task: ' + group.task_title,
        'aria-pressed': isSelected,
      }
    : {};

  return (
    <Wrapper
      {...wrapperProps}
      className={
        'w-full text-left rounded-lg border transition-colors ' +
        (isSelectable
          ? isSelected
            ? 'bg-accent-purple/10 border-accent-purple/30'
            : 'bg-bg-card border-border hover:bg-bg-hover hover:border-border-hover'
          : 'bg-bg-card border-border')
      }
    >
      {/* Card header */}
      <div className="px-3 py-2.5 border-b border-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            {/* Status dot / icon */}
            {currentStatus === 'building' || currentStatus === 'verifying' ? (
              <span
                className={
                  'inline-block h-2 w-2 rounded-full shrink-0 animate-pulse-dot ' +
                  (currentStatus === 'building' ? 'bg-status-active' : 'bg-accent-purple')
                }
              />
            ) : currentStatus === 'completed' ? (
              <svg
                className="h-3.5 w-3.5 text-status-completed shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2.5}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            ) : currentStatus === 'failed' ? (
              <svg
                className="h-3.5 w-3.5 text-status-failed shrink-0"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2.5}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <span className="inline-block h-2 w-2 rounded-full bg-status-pending shrink-0" />
            )}
            <span className="text-sm font-medium text-text-primary truncate">
              {group.task_title}
            </span>
          </div>
          <div className="flex items-center gap-2 ml-2 shrink-0">
            {attemptCount > 1 && (
              <span className="text-[11px] text-status-paused font-mono">
                x{attemptCount}
              </span>
            )}
            {currentStatus && (
              <TaskStatusBadge status={currentStatus as TaskSummary['status']} />
            )}
          </div>
        </div>
        {group.step_title && (
          <span className="text-[10px] text-text-muted mt-0.5 block">
            {group.step_title}
          </span>
        )}
      </div>

      {/* Event timeline */}
      <div className="px-3 py-2 space-y-1">
        {group.events.map(ev => {
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
    </Wrapper>
  );
}

/** Card for an active task that has no events (status derived from run data). */
function ActiveTaskCard({
  task,
  isSelected,
  onSelect,
}: {
  task: ActiveTask;
  isSelected: boolean;
  onSelect?: () => void;
}) {
  const status = task.status;
  const isSelectable = !!onSelect;
  const Wrapper = isSelectable ? 'button' : 'div';

  const wrapperProps = isSelectable
    ? {
        onClick: onSelect,
        'aria-label': 'Select task: ' + task.task_title,
        'aria-pressed': isSelected,
      }
    : {};

  return (
    <Wrapper
      {...wrapperProps}
      className={
        'w-full text-left rounded-lg border transition-colors ' +
        (isSelectable
          ? isSelected
            ? 'bg-accent-purple/10 border-accent-purple/30'
            : 'bg-bg-card border-border hover:bg-bg-hover hover:border-border-hover'
          : 'bg-bg-card border-border')
      }
    >
      <div className="px-3 py-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            {status === 'building' || status === 'verifying' ? (
              <span
                className={
                  'inline-block h-2 w-2 rounded-full shrink-0 animate-pulse-dot ' +
                  (status === 'building' ? 'bg-status-active' : 'bg-accent-purple')
                }
              />
            ) : status === 'completed' ? (
              <svg className="h-3.5 w-3.5 text-status-completed shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            ) : status === 'failed' ? (
              <svg className="h-3.5 w-3.5 text-status-failed shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <span className="inline-block h-2 w-2 rounded-full bg-status-pending shrink-0" />
            )}
            <span className="text-sm font-medium text-text-primary truncate">
              {task.task_title}
            </span>
          </div>
          <div className="flex items-center gap-2 ml-2 shrink-0">
            <TaskStatusBadge status={status as TaskSummary['status']} />
          </div>
        </div>
        {task.step_title && (
          <span className="text-[10px] text-text-muted mt-0.5 block ml-5">
            {task.step_title}
          </span>
        )}
      </div>
    </Wrapper>
  );
}

export function ActivityFeed({ events, activeTasks, onSelectTask, selectedTaskId, run }: ActivityFeedProps) {
  const groups: ActivityGroup[] = groupEventsByTask(events);

  // Find active tasks that have NO events (status-only, not in any event group)
  const eventTaskIds = new Set<string>();
  for (const g of groups) {
    if (g.kind === 'task') eventTaskIds.add(g.task_id);
  }
  const statusOnlyTasks = (activeTasks ?? []).filter(t => !eventTaskIds.has(t.task_id));

  if (groups.length === 0 && statusOnlyTasks.length === 0) {
    return (
      <div className="text-center py-8 text-text-muted text-sm">
        No activity yet
      </div>
    );
  }

  // When run is provided and onSelectTask is NOT provided, use expandable TaskDetailCards
  const useExpandableCards = !!run && !onSelectTask;

  // Look up task data from run for expandable cards
  const allTasks = run ? run.steps.flatMap(s => s.tasks) : [];
  const allSteps = run ? run.steps : [];

  // Track which step IDs have been anchored so we only add the id to the first task per step
  const anchoredStepIds = new Set<string>();

  /** Return an id attribute for the first task in each step (for scroll-to-step). */
  function getStepAnchorId(taskId: string): string | undefined {
    const step = allSteps.find(s => s.tasks.some(t => t.id === taskId));
    if (step && !anchoredStepIds.has(step.id)) {
      anchoredStepIds.add(step.id);
      return `step-${step.id}`;
    }
    return undefined;
  }

  return (
    <div className="space-y-2" role="feed" aria-label="Activity log">
      {groups.map((group, i) => {
        // Skip milestone rows — they add noise (agent output, step-complete, auto-verify, etc.)
        if (group.kind === 'milestone') {
          return null;
        }

        const anchorId = getStepAnchorId(group.task_id);

        if (useExpandableCards) {
          const taskData = allTasks.find(t => t.id === group.task_id);
          // Find step title from run data
          const step = allSteps.find(s => s.tasks.some(t => t.id === group.task_id));
          const stepTitle = step?.title || step?.config_id || group.step_title;

          return (
            <div key={group.task_id + '-' + i} id={anchorId}>
              <TaskDetailCard
                taskId={group.task_id}
                taskTitle={group.task_title}
                stepTitle={stepTitle}
                status={taskData?.status ?? 'pending'}
                events={group.events}
                gradeSummary={taskData?.grade_summary ?? []}
                attemptsSummary={taskData?.attempts_summary ?? []}
                runId={run!.id}
              />
            </div>
          );
        }

        return (
          <div key={group.task_id + '-' + i} id={anchorId}>
            <TaskGroupCard
              group={group}
              isSelected={selectedTaskId === group.task_id}
              onSelect={() => onSelectTask?.(group.task_id)}
            />
          </div>
        );
      })}
      {statusOnlyTasks.map(task => {
        const anchorId = getStepAnchorId(task.task_id);

        if (useExpandableCards) {
          const taskData = allTasks.find(t => t.id === task.task_id);
          const step = allSteps.find(s => s.tasks.some(t => t.id === task.task_id));
          const stepTitle = step?.title || step?.config_id || task.step_title;

          return (
            <div key={task.task_id} id={anchorId}>
              <TaskDetailCard
                taskId={task.task_id}
                taskTitle={task.task_title}
                stepTitle={stepTitle}
                status={taskData?.status ?? task.status}
                events={[]}
                gradeSummary={taskData?.grade_summary ?? []}
                attemptsSummary={taskData?.attempts_summary ?? []}
                runId={run!.id}
              />
            </div>
          );
        }

        return (
          <div key={task.task_id} id={anchorId}>
            <ActiveTaskCard
              task={task}
              isSelected={selectedTaskId === task.task_id}
              onSelect={() => onSelectTask?.(task.task_id)}
            />
          </div>
        );
      })}
    </div>
  );
}
