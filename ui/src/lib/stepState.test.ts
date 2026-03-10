import { describe, it, expect } from 'vitest';
import { getStepState } from '../components/dashboard/stepTimelineUtils';
import type { StepSummary, TaskSummary } from '../types';
import type { TaskStatus } from '../types';

// ---------------------------------------------------------------------------
// Test-data helpers
// ---------------------------------------------------------------------------

function makeTask(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    id: 'task-1',
    config_id: 'task-cfg-1',
    title: 'Test Task',
    status: 'completed' as TaskStatus,
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

// ---------------------------------------------------------------------------
// getStepState
// ---------------------------------------------------------------------------

describe('getStepState', () => {
  it('returns "completed" for a completed step with no failed tasks', () => {
    const step = makeStep({
      completed: true,
      tasks: [
        makeTask({ status: 'completed' }),
        makeTask({ id: 'task-2', status: 'completed' }),
      ],
    });

    expect(getStepState(step, false)).toBe('completed');
  });

  it('returns "failed" for a step with a failed task (even if not completed)', () => {
    const step = makeStep({
      completed: false,
      tasks: [
        makeTask({ status: 'completed' }),
        makeTask({ id: 'task-2', status: 'failed' }),
      ],
    });

    expect(getStepState(step, true)).toBe('failed');
  });

  it('returns "active" for the current step with no failures', () => {
    const step = makeStep({
      completed: false,
      tasks: [
        makeTask({ status: 'building' }),
        makeTask({ id: 'task-2', status: 'pending' }),
      ],
    });

    expect(getStepState(step, true)).toBe('active');
  });

  it('returns "pending" for a future step (not current, not completed)', () => {
    const step = makeStep({
      completed: false,
      tasks: [
        makeTask({ status: 'pending' }),
      ],
    });

    expect(getStepState(step, false)).toBe('pending');
  });

  it('returns "failed" when completed=true AND has failed tasks (critical bug fix)', () => {
    // This is the critical case: the workflow engine marks a step as completed=true
    // even when it contains failed tasks (because all tasks reached terminal state).
    // The UI must show "failed" not "completed" in this case.
    const step = makeStep({
      completed: true,
      tasks: [
        makeTask({ status: 'completed' }),
        makeTask({ id: 'task-2', status: 'failed' }),
      ],
    });

    // Must be 'failed', not 'completed'
    expect(getStepState(step, false)).toBe('failed');
    // Also 'failed' even when it's the current step
    expect(getStepState(step, true)).toBe('failed');
  });

  it('returns "failed" when all tasks in a step are failed', () => {
    const step = makeStep({
      completed: true,
      tasks: [
        makeTask({ status: 'failed' }),
        makeTask({ id: 'task-2', status: 'failed' }),
      ],
    });

    expect(getStepState(step, false)).toBe('failed');
  });

  it('returns "completed" for a step with a single completed task', () => {
    const step = makeStep({
      completed: true,
      tasks: [makeTask({ status: 'completed' })],
    });

    expect(getStepState(step, false)).toBe('completed');
  });

  it('returns "active" for a current step with all pending tasks', () => {
    const step = makeStep({
      completed: false,
      tasks: [
        makeTask({ status: 'pending' }),
        makeTask({ id: 'task-2', status: 'pending' }),
      ],
    });

    expect(getStepState(step, true)).toBe('active');
  });
});
