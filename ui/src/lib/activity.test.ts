import { describe, it, expect } from 'vitest';
import { groupEventsByTask, classifyTasks } from './activity';
import type { ActivityEvent, RunResponse, StepSummary, TaskSummary } from '../types';
import type { RunStatus, TaskStatus } from '../types';

// ---------------------------------------------------------------------------
// Test-data helpers
// ---------------------------------------------------------------------------

let eventIdCounter = 0;

function makeEvent(overrides: Partial<ActivityEvent> = {}): ActivityEvent {
  eventIdCounter += 1;
  return {
    id: eventIdCounter,
    event_type: 'task_status_changed',
    timestamp: new Date(Date.UTC(2025, 0, 1, 0, 0, eventIdCounter)).toISOString(),
    payload: {},
    task_title: null,
    step_title: null,
    ...overrides,
  };
}

function makeTask(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    id: 'task-1',
    config_id: 'task-cfg-1',
    title: 'Test Task',
    status: 'pending' as TaskStatus,
    current_attempt: 1,
    max_attempts: 3,
    grade_summary: [],
    attempts_summary: [],
    pending_action_type: null,
    pending_clarification_count: null,
    ...overrides,
  };
}

function makeStep(overrides: Partial<StepSummary> = {}): StepSummary {
  return {
    id: 'step-1',
    config_id: 'step-cfg-1',
    title: 'Test Step',
    completed: false,
    tasks: [makeTask()],
    has_approval_gate: false,
    approval_status: null,
    skipped: false,
    skip_reason: null,
    condition: null,
    ...overrides,
  };
}

function makeRun(overrides: Partial<RunResponse> = {}): RunResponse {
  return {
    id: 'run-1',
    repo_name: 'proj-1',
    status: 'active' as RunStatus,
    routine_id: null,
    routine_sha: null,
    routine_source: null,
    routine_embedded: null,
    agent_runner_type: null,
    agent_runner_type_display: 'No Agent Runner',
    agent_icon: 'none',
    agent_runner_started_at: null,
    agent_runner_config: {},
    worktree_enabled: false,
    worktree_path: null,
    source_branch: null,
    merge_strategy: null,
    config: {},
    env_file_specs: [],
    env_source_dir: null,
    steps: [makeStep()],
    current_step_index: 0,
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
    started_at: null,
    completed_at: null,
    total_tokens_read: 0,
    total_tokens_write: 0,
    total_tokens_cache: 0,
    total_duration_ms: 0,
    estimated_cost_usd: null,
    cost_disclaimer: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// groupEventsByTask
// ---------------------------------------------------------------------------

describe('groupEventsByTask', () => {
  it('returns empty array for empty events', () => {
    expect(groupEventsByTask([])).toEqual([]);
  });

  it('returns a milestone for a run_status_changed event', () => {
    const event = makeEvent({
      event_type: 'run_status_changed',
      payload: { from_status: 'draft', to_status: 'active' },
    });

    const groups = groupEventsByTask([event]);

    expect(groups).toHaveLength(1);
    expect(groups[0].kind).toBe('milestone');
    if (groups[0].kind === 'milestone') {
      expect(groups[0].event).toBe(event);
    }
  });

  it('groups multiple task events for the same task together', () => {
    const e1 = makeEvent({
      event_type: 'task_status_changed',
      payload: { task_id: 'task-a', from_status: 'pending', to_status: 'building' },
      task_title: 'Task A',
      step_title: 'Step 1',
    });
    const e2 = makeEvent({
      event_type: 'task_status_changed',
      payload: { task_id: 'task-a', from_status: 'building', to_status: 'verifying' },
      task_title: 'Task A',
      step_title: 'Step 1',
    });

    const groups = groupEventsByTask([e1, e2]);

    expect(groups).toHaveLength(1);
    expect(groups[0].kind).toBe('task');
    if (groups[0].kind === 'task') {
      expect(groups[0].task_id).toBe('task-a');
      expect(groups[0].events).toHaveLength(2);
      expect(groups[0].events[0]).toBe(e1);
      expect(groups[0].events[1]).toBe(e2);
    }
  });

  it('interleaves task groups and milestones in chronological order', () => {
    const taskEvent = makeEvent({
      event_type: 'task_status_changed',
      payload: { task_id: 'task-a' },
      task_title: 'Task A',
    });
    const milestoneEvent = makeEvent({
      event_type: 'run_status_changed',
      payload: { from_status: 'draft', to_status: 'active' },
    });
    const taskEvent2 = makeEvent({
      event_type: 'task_status_changed',
      payload: { task_id: 'task-b' },
      task_title: 'Task B',
    });

    const groups = groupEventsByTask([taskEvent, milestoneEvent, taskEvent2]);

    expect(groups).toHaveLength(3);
    expect(groups[0].kind).toBe('task');
    expect(groups[1].kind).toBe('milestone');
    expect(groups[2].kind).toBe('task');
    if (groups[0].kind === 'task') expect(groups[0].task_id).toBe('task-a');
    if (groups[2].kind === 'task') expect(groups[2].task_id).toBe('task-b');
  });

  it('treats step_completed events as milestones', () => {
    const event = makeEvent({
      event_type: 'step_completed',
      payload: { step_id: 'step-1' },
      step_title: 'Step 1',
    });

    const groups = groupEventsByTask([event]);

    expect(groups).toHaveLength(1);
    expect(groups[0].kind).toBe('milestone');
  });

  it('creates separate groups for multiple distinct tasks', () => {
    const eA = makeEvent({
      event_type: 'task_status_changed',
      payload: { task_id: 'task-a' },
      task_title: 'Task A',
    });
    const eB = makeEvent({
      event_type: 'task_status_changed',
      payload: { task_id: 'task-b' },
      task_title: 'Task B',
    });

    const groups = groupEventsByTask([eA, eB]);

    expect(groups).toHaveLength(2);
    expect(groups[0].kind).toBe('task');
    expect(groups[1].kind).toBe('task');
    if (groups[0].kind === 'task') expect(groups[0].task_id).toBe('task-a');
    if (groups[1].kind === 'task') expect(groups[1].task_id).toBe('task-b');
  });

  it('groups a full task lifecycle into one group', () => {
    const taskId = 'task-full';
    const events = [
      makeEvent({
        event_type: 'task_status_changed',
        payload: { task_id: taskId, from_status: 'pending', to_status: 'building' },
        task_title: 'Full Task',
        step_title: 'Step 1',
      }),
      makeEvent({
        event_type: 'checklist_gate_evaluated',
        payload: { task_id: taskId, passed: true },
        task_title: 'Full Task',
        step_title: 'Step 1',
      }),
      makeEvent({
        event_type: 'task_status_changed',
        payload: { task_id: taskId, from_status: 'building', to_status: 'verifying' },
        task_title: 'Full Task',
        step_title: 'Step 1',
      }),
      makeEvent({
        event_type: 'grades_evaluated',
        payload: { task_id: taskId, passed: true },
        task_title: 'Full Task',
        step_title: 'Step 1',
      }),
      makeEvent({
        event_type: 'task_status_changed',
        payload: { task_id: taskId, from_status: 'verifying', to_status: 'completed' },
        task_title: 'Full Task',
        step_title: 'Step 1',
      }),
    ];

    const groups = groupEventsByTask(events);

    expect(groups).toHaveLength(1);
    expect(groups[0].kind).toBe('task');
    if (groups[0].kind === 'task') {
      expect(groups[0].task_id).toBe(taskId);
      expect(groups[0].task_title).toBe('Full Task');
      expect(groups[0].step_title).toBe('Step 1');
      expect(groups[0].events).toHaveLength(5);
    }
  });

  it('groups all events from multiple build/verify cycles (revision attempts) in one group', () => {
    const taskId = 'task-revision';
    const events = [
      // Attempt 1: build -> verify -> revision
      makeEvent({
        event_type: 'task_status_changed',
        payload: { task_id: taskId, from_status: 'pending', to_status: 'building' },
        task_title: 'Revision Task',
      }),
      makeEvent({
        event_type: 'checklist_gate_evaluated',
        payload: { task_id: taskId, passed: true },
        task_title: 'Revision Task',
      }),
      makeEvent({
        event_type: 'task_status_changed',
        payload: { task_id: taskId, from_status: 'building', to_status: 'verifying' },
        task_title: 'Revision Task',
      }),
      makeEvent({
        event_type: 'grades_evaluated',
        payload: { task_id: taskId, passed: false },
        task_title: 'Revision Task',
      }),
      // Attempt 2: back to building -> verify -> pass
      makeEvent({
        event_type: 'task_status_changed',
        payload: { task_id: taskId, from_status: 'verifying', to_status: 'building' },
        task_title: 'Revision Task',
      }),
      makeEvent({
        event_type: 'task_status_changed',
        payload: { task_id: taskId, from_status: 'building', to_status: 'verifying' },
        task_title: 'Revision Task',
      }),
      makeEvent({
        event_type: 'grades_evaluated',
        payload: { task_id: taskId, passed: true },
        task_title: 'Revision Task',
      }),
      makeEvent({
        event_type: 'task_status_changed',
        payload: { task_id: taskId, from_status: 'verifying', to_status: 'completed' },
        task_title: 'Revision Task',
      }),
    ];

    const groups = groupEventsByTask(events);

    expect(groups).toHaveLength(1);
    if (groups[0].kind === 'task') {
      expect(groups[0].task_id).toBe(taskId);
      expect(groups[0].events).toHaveLength(8);
    }
  });

  it('uses task_id as fallback title when task_title is null', () => {
    const event = makeEvent({
      event_type: 'task_status_changed',
      payload: { task_id: 'task-no-title' },
      task_title: null,
    });

    const groups = groupEventsByTask([event]);

    expect(groups[0].kind).toBe('task');
    if (groups[0].kind === 'task') {
      expect(groups[0].task_title).toBe('task-no-title');
    }
  });

  it('uses empty string as fallback step_title when step_title is null', () => {
    const event = makeEvent({
      event_type: 'task_status_changed',
      payload: { task_id: 'task-no-step' },
      step_title: null,
    });

    const groups = groupEventsByTask([event]);

    if (groups[0].kind === 'task') {
      expect(groups[0].step_title).toBe('');
    }
  });
});

// ---------------------------------------------------------------------------
// classifyTasks
// ---------------------------------------------------------------------------

describe('classifyTasks', () => {
  it('puts all pending tasks with no events into upcoming', () => {
    const run = makeRun({
      steps: [
        makeStep({
          tasks: [
            makeTask({ id: 't1', status: 'pending' }),
            makeTask({ id: 't2', status: 'pending' }),
          ],
        }),
      ],
    });

    const result = classifyTasks(run, []);

    expect(result.active).toHaveLength(0);
    expect(result.upcoming).toHaveLength(2);
  });

  it('puts a task with non-pending status but no events into active', () => {
    const run = makeRun({
      steps: [
        makeStep({
          tasks: [makeTask({ id: 't1', status: 'building' })],
        }),
      ],
    });

    const result = classifyTasks(run, []);

    expect(result.active).toHaveLength(1);
    expect(result.active[0].task_id).toBe('t1');
    expect(result.active[0].status).toBe('building');
    expect(result.upcoming).toHaveLength(0);
  });

  it('puts a pending task with events into active', () => {
    const run = makeRun({
      steps: [
        makeStep({
          tasks: [makeTask({ id: 't1', status: 'pending' })],
        }),
      ],
    });
    const events = [
      makeEvent({
        event_type: 'task_status_changed',
        payload: { task_id: 't1', from_status: 'pending', to_status: 'building' },
      }),
    ];

    const result = classifyTasks(run, events);

    expect(result.active).toHaveLength(1);
    expect(result.active[0].task_id).toBe('t1');
    expect(result.upcoming).toHaveLength(0);
  });

  it('places all tasks in active for a completed run', () => {
    const run = makeRun({
      status: 'completed',
      steps: [
        makeStep({
          completed: true,
          tasks: [
            makeTask({ id: 't1', status: 'completed' }),
            makeTask({ id: 't2', status: 'completed' }),
          ],
        }),
      ],
    });

    const result = classifyTasks(run, []);

    expect(result.active).toHaveLength(2);
    expect(result.upcoming).toHaveLength(0);
  });

  it('splits tasks between active and upcoming for an active run with a mix', () => {
    const run = makeRun({
      status: 'active',
      steps: [
        makeStep({
          id: 'step-1',
          title: 'Step One',
          tasks: [
            makeTask({ id: 't1', status: 'completed', title: 'Done Task' }),
            makeTask({ id: 't2', status: 'building', title: 'Building Task' }),
          ],
        }),
        makeStep({
          id: 'step-2',
          title: 'Step Two',
          tasks: [
            makeTask({ id: 't3', status: 'pending', title: 'Future Task' }),
          ],
        }),
      ],
    });

    const result = classifyTasks(run, []);

    expect(result.active).toHaveLength(2);
    expect(result.active.map(t => t.task_id)).toEqual(['t1', 't2']);
    expect(result.upcoming).toHaveLength(1);
    expect(result.upcoming[0].task_id).toBe('t3');
  });

  it('puts all tasks into upcoming for a draft run with all pending tasks', () => {
    const run = makeRun({
      status: 'draft',
      steps: [
        makeStep({
          tasks: [
            makeTask({ id: 't1', status: 'pending' }),
            makeTask({ id: 't2', status: 'pending' }),
          ],
        }),
      ],
    });

    const result = classifyTasks(run, []);

    expect(result.active).toHaveLength(0);
    expect(result.upcoming).toHaveLength(2);
  });

  it('preserves step_title, step_id, and step_index in upcoming tasks', () => {
    const run = makeRun({
      steps: [
        makeStep({
          id: 'step-alpha',
          title: 'Alpha Step',
          tasks: [makeTask({ id: 't1', status: 'completed' })],
        }),
        makeStep({
          id: 'step-beta',
          title: 'Beta Step',
          tasks: [makeTask({ id: 't2', status: 'pending', title: 'Upcoming Task' })],
        }),
      ],
    });

    const result = classifyTasks(run, []);

    expect(result.upcoming).toHaveLength(1);
    expect(result.upcoming[0]).toEqual({
      task_id: 't2',
      task_title: 'Upcoming Task',
      step_id: 'step-beta',
      step_title: 'Beta Step',
      step_index: 1,
    });
  });

  it('uses config_id as fallback when task title is empty', () => {
    const run = makeRun({
      steps: [
        makeStep({
          tasks: [makeTask({ id: 't1', title: '', config_id: 'fallback-cfg', status: 'building' })],
        }),
      ],
    });

    const result = classifyTasks(run, []);

    expect(result.active[0].task_title).toBe('fallback-cfg');
  });

  it('uses config_id as fallback when step title is empty', () => {
    const run = makeRun({
      steps: [
        makeStep({
          title: '',
          config_id: 'step-fallback-cfg',
          tasks: [makeTask({ id: 't1', status: 'pending' })],
        }),
      ],
    });

    const result = classifyTasks(run, []);

    expect(result.upcoming[0].step_title).toBe('step-fallback-cfg');
  });
});
