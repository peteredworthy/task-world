import { useState, type ReactNode } from 'react';
import { TaskStatusBadge } from '../StatusBadge';
import { formatRelativeTime } from '../../lib/format';
import { groupEventsByTask } from '../../lib/activity';
import { TaskDetailCard } from './TaskDetailCard';
import { COLLAPSIBLE_BORDER_CLASS, COLLAPSIBLE_DIVIDER_CLASS } from './sharedUtils';
import type { ActivityEvent, TaskSummary, RunResponse, StepSummary } from '../../types';
import type { ActiveTask, ActivityGroup, TaskEventGroup } from '../../lib/activity';

interface ActivityFeedProps {
  events: ActivityEvent[];
  activeTasks?: ActiveTask[];
  onSelectTask?: (taskId: string) => void;
  selectedTaskId?: string | null;
  run?: RunResponse;
  expandCompletedSteps?: boolean;
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
    case 'step_skipped': {
      const reason = payload.skip_reason as string | undefined;
      return reason ? `Skipped: ${reason}` : 'Step skipped';
    }
    case 'agent_error':
      return (payload.error_message as string) || 'Agent error';
    default:
      return eventType.replace(/_/g, ' ');
  }
}

function statusFromPayload(payload: Record<string, unknown>): string | null {
  return (payload.new_status as string) ?? null;
}

function eventDotColor(eventType: string): string {
  switch (eventType) {
    case 'step_skipped':
      return 'bg-status-paused';
    case 'agent_error':
      return 'bg-status-failed';
    default:
      return 'bg-border';
  }
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
            {currentStatus === 'building' || currentStatus === 'verifying' || currentStatus === 'fan_out_running' ? (
              <span
                className={
                  'inline-block h-2 w-2 rounded-full shrink-0 animate-pulse-dot ' +
                  (currentStatus === 'building' || currentStatus === 'fan_out_running' ? 'bg-status-active' : 'bg-accent-purple')
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
            <span className="text-sm font-medium text-text-primary truncate" title={group.task_title}>
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
          const isSkipped = ev.event_type === 'step_skipped';
          return (
            <div key={ev.id} className="flex items-center gap-2 text-xs">
              <span className={'w-1.5 h-1.5 rounded-full shrink-0 ' + eventDotColor(ev.event_type)} />
              <span className={isError || isSkipped ? (isError ? 'text-status-failed font-medium' : 'text-status-paused font-medium') : 'text-text-secondary'}>
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
            {status === 'building' || status === 'verifying' || status === 'fan_out_running' ? (
              <span
                className={
                  'inline-block h-2 w-2 rounded-full shrink-0 animate-pulse-dot ' +
                  (status === 'building' || status === 'fan_out_running' ? 'bg-status-active' : 'bg-accent-purple')
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
            <span className="text-sm font-medium text-text-primary truncate" title={task.task_title}>
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

/**
 * Determine if a step should be expanded by default.
 * Expanded when: any task is failed, OR any task is NOT completed and NOT failed.
 */
function defaultStepExpanded(step: StepSummary): boolean {
  // If any task is failed → keep expanded
  if (step.tasks.some(t => t.status === 'failed')) return true;
  // If all tasks are completed or failed → collapse
  if (step.tasks.every(t => t.status === 'completed' || t.status === 'failed')) return false;
  // Otherwise (has active/pending tasks) → expand
  return true;
}

function StepSection({
  step,
  stepNumber,
  expandCompleted,
  children,
}: {
  step: StepSummary;
  stepNumber: number;
  expandCompleted: boolean;
  children: ReactNode;
}) {
  const [expanded, setExpanded] = useState(() => expandCompleted || defaultStepExpanded(step));

  const topLevelTasks = step.tasks.filter(t => !t.parent_task_id);
  const totalTasks = topLevelTasks.length;
  const doneTasks = topLevelTasks.filter(t => t.status === 'completed' || t.status === 'failed').length;

  return (
    <div className={`rounded-lg border ${COLLAPSIBLE_BORDER_CLASS} bg-bg-elevated overflow-hidden`}>
      {/* Header — always visible, clickable */}
      <button
        id={`step-${step.id}`}
        onClick={() => setExpanded(e => !e)}
        className="w-full text-left px-3 py-2.5 flex items-center gap-2.5 hover:bg-bg-hover transition-colors"
        aria-expanded={expanded}
      >
        {/* Step number circle */}
        <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-accent-purple/20 text-accent-purple text-[11px] font-bold shrink-0">
          {stepNumber}
        </span>

        {/* Step title */}
        <span className="text-sm font-semibold text-text-primary truncate flex-1 min-w-0" title={step.title || step.config_id}>
          {step.title || step.config_id}
        </span>

        {/* Task progress badge */}
        <span className="text-[11px] font-mono text-text-muted shrink-0 bg-bg-card border border-border rounded px-1.5 py-0.5">
          {doneTasks} / {totalTasks} tasks
        </span>

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
      </button>

      {/* Body — collapsible */}
      {expanded && (
        <div className={`border-t ${COLLAPSIBLE_DIVIDER_CLASS} px-3 py-3 space-y-2`}>
          {children}
        </div>
      )}
    </div>
  );
}

export function ActivityFeed({
  events,
  activeTasks,
  onSelectTask,
  selectedTaskId,
  run,
  expandCompletedSteps = false,
}: ActivityFeedProps) {
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
  // grouped by step sections.
  const useExpandableCards = !!run && !onSelectTask;

  // Look up step data from run
  const allSteps = run ? run.steps : [];

  // --- Step-sectioned rendering (when run is provided) ---
  if (useExpandableCards) {
    // Build a map from task_id → event group for quick lookup
    const groupByTaskId = new Map<string, TaskEventGroup>();
    for (const g of groups) {
      if (g.kind === 'task') groupByTaskId.set(g.task_id, g);
    }
    // Also index statusOnlyTasks by task_id
    const statusOnlyByTaskId = new Map(statusOnlyTasks.map(t => [t.task_id, t]));

    return (
      <div className="space-y-3" role="feed" aria-label="Activity log">
        {allSteps.map((step, stepIdx) => {
          // Collect task cards for this step (only top-level tasks; children are nested under parents)
          const stepTaskCards: ReactNode[] = [];
          for (const taskSummary of step.tasks) {
            // Skip child tasks — they appear nested under their fan-out parent
            if (taskSummary.parent_task_id) continue;

            const taskId = taskSummary.id;
            const taskTitle = taskSummary.title || taskSummary.config_id;
            const stepTitle = step.title || step.config_id;
            const eventGroup = groupByTaskId.get(taskId);
            const statusOnly = statusOnlyByTaskId.get(taskId);

            if (eventGroup) {
              stepTaskCards.push(
                <TaskDetailCard
                  key={taskId}
                  taskId={taskId}
                  taskTitle={taskTitle}
                  stepTitle={stepTitle}
                  status={taskSummary.status}
                  events={eventGroup.events}
                  gradeSummary={taskSummary.grade_summary}
                  attemptsSummary={taskSummary.attempts_summary}
                  runId={run!.id}
                  stepTasks={step.tasks}
                />,
              );
            } else if (statusOnly || taskSummary.status !== 'pending') {
              // Show the card even if no events, if status is non-pending or it appeared in activeTasks
              stepTaskCards.push(
                <TaskDetailCard
                  key={taskId}
                  taskId={taskId}
                  taskTitle={taskTitle}
                  stepTitle={stepTitle}
                  status={taskSummary.status}
                  events={[]}
                  gradeSummary={taskSummary.grade_summary}
                  attemptsSummary={taskSummary.attempts_summary}
                  runId={run!.id}
                  stepTasks={step.tasks}
                />,
              );
            }
          }

          // Skip steps with no visible task cards
          if (stepTaskCards.length === 0) return null;

          return (
            <StepSection
              key={step.id}
              step={step}
              stepNumber={stepIdx + 1}
              expandCompleted={expandCompletedSteps}
            >
              {stepTaskCards}
            </StepSection>
          );
        })}
      </div>
    );
  }

  // --- Flat rendering (no run prop) ---
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
