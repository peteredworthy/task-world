import type { ActivityEvent, RunResponse } from '../types';

/** A group of events belonging to a single task. */
export interface TaskEventGroup {
  kind: 'task';
  task_id: string;
  task_title: string;
  step_title: string;
  events: ActivityEvent[];
}

/** A run-level milestone event (e.g. run_started, step_completed). */
export interface MilestoneEvent {
  kind: 'milestone';
  event: ActivityEvent;
}

export type ActivityGroup = TaskEventGroup | MilestoneEvent;

/** Event types that are task-scoped (have a task_id in payload). */
const TASK_EVENT_TYPES = new Set([
  'task_status_changed',
  'checklist_gate_evaluated',
  'grades_evaluated',
  'agent_error',
  'agent_output',
]);

/**
 * Group events into task groups and run-level milestones,
 * preserving chronological order of first appearance.
 */
export function groupEventsByTask(events: ActivityEvent[]): ActivityGroup[] {
  const groups: ActivityGroup[] = [];
  const taskGroupMap = new Map<string, TaskEventGroup>();

  for (const event of events) {
    const taskId = event.payload.task_id as string | undefined;

    if (taskId && TASK_EVENT_TYPES.has(event.event_type)) {
      let group = taskGroupMap.get(taskId);
      if (!group) {
        group = {
          kind: 'task',
          task_id: taskId,
          task_title: event.task_title ?? taskId,
          step_title: event.step_title ?? '',
          events: [],
        };
        taskGroupMap.set(taskId, group);
        groups.push(group);
      }
      group.events.push(event);
    } else {
      groups.push({ kind: 'milestone', event });
    }
  }

  return groups;
}

/** A task that has activity events (has been started). */
export interface ActiveTask {
  task_id: string;
  task_title: string;
  step_title: string;
  status: string;
}

/** A task from the run blueprint with no activity yet. */
export interface UpcomingTask {
  task_id: string;
  task_title: string;
  step_id: string;
  step_title: string;
  step_index: number;
}

export interface ClassifiedTasks {
  active: ActiveTask[];
  upcoming: UpcomingTask[];
}

/**
 * Split run tasks into "has activity" (any task_status_changed event, or
 * non-pending status) vs "upcoming" (truly pending with no events).
 */
export function classifyTasks(
  run: RunResponse,
  events: ActivityEvent[],
): ClassifiedTasks {
  // Collect task IDs that have at least one task_status_changed event
  const activeTaskIds = new Set<string>();
  for (const event of events) {
    if (event.event_type === 'task_status_changed') {
      const taskId = event.payload.task_id as string | undefined;
      if (taskId) activeTaskIds.add(taskId);
    }
  }

  const active: ActiveTask[] = [];
  const upcoming: UpcomingTask[] = [];

  for (let si = 0; si < run.steps.length; si++) {
    const step = run.steps[si];
    const stepTitle = step.title || step.config_id;

    for (const task of step.tasks) {
      const taskTitle = task.title || task.config_id;

      // A task is "active" if it has events OR its status is anything other
      // than pending (the status itself proves work has happened).
      const isActive =
        activeTaskIds.has(task.id) || task.status !== 'pending';

      if (isActive) {
        active.push({
          task_id: task.id,
          task_title: taskTitle,
          step_title: stepTitle,
          status: task.status,
        });
      } else {
        upcoming.push({
          task_id: task.id,
          task_title: taskTitle,
          step_id: step.id,
          step_title: stepTitle,
          step_index: si,
        });
      }
    }
  }

  return { active, upcoming };
}

/** Extract the last agent error from events, if any. */
export function getLastAgentError(events: ActivityEvent[]): {
  errorMessage: string;
  taskTitle: string | null;
} | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.event_type === 'agent_error') {
      // Also scan backwards through agent_output for the real error detail
      // (the agent_error payload is often generic like "Process exited with code 1")
      let detail = '';
      for (let j = i - 1; j >= 0; j--) {
        const prev = events[j];
        if (prev.event_type !== 'agent_output') break;
        const lines = prev.payload.lines as string[] | undefined;
        if (lines) {
          const errorLines = lines.filter(
            l => l.startsWith('ERROR:') || l.includes('does not exist') || l.includes('Reconnecting... 5/5'),
          );
          if (errorLines.length > 0) {
            detail = errorLines[errorLines.length - 1];
            break;
          }
        }
      }

      const message = detail || (e.payload.error_message as string) || 'Unknown error';
      return { errorMessage: message, taskTitle: e.task_title };
    }
  }
  return null;
}
