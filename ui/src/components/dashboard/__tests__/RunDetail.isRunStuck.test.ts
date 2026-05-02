import { describe, expect, it } from 'vitest';
import { isRunStuck } from '../../../lib/runStuck';
import type { RunResponse, StepSummary, TaskSummary } from '../../../types';

function makeTask(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    id: 'task-1',
    config_id: 'task-cfg',
    title: 'My Task',
    status: 'pending',
    current_attempt: 1,
    max_attempts: 3,
    grade_summary: [],
    attempts_summary: [],
    pending_action_type: null,
    pending_clarification_count: null,
    parent_task_id: null,
    ...overrides,
  };
}

function makeStep(tasks: TaskSummary[] = []): StepSummary {
  return {
    id: 'step-1',
    config_id: 'step-cfg',
    title: 'Step 1',
    completed: false,
    tasks,
    has_approval_gate: false,
    approval_status: null,
    skipped: false,
    skip_reason: null,
    condition: null,
  };
}

function makeRun(overrides: Partial<Pick<RunResponse, 'status' | 'steps'>>): RunResponse {
  return {
    id: 'run-1',
    repo_name: 'repo',
    status: 'active',
    pause_reason: null,
    last_error: null,
    routine_id: null,
    routine_sha: null,
    routine_source: null,
    routine_embedded: null,
    agent_type: null,
    agent_type_display: '',
    agent_icon: '',
    agent_config: {},
    worktree_enabled: false,
    worktree_path: null,
    source_branch: null,
    merge_strategy: null,
    config: {},
    env_file_specs: [],
    env_source_dir: null,
    steps: [],
    current_step_index: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    started_at: null,
    completed_at: null,
    agent_started_at: null,
    total_tokens_read: 0,
    total_tokens_write: 0,
    total_tokens_cache: 0,
    total_duration_ms: 0,
    token_usage_by_model: [],
    estimated_cost_usd: null,
    cost_disclaimer: null,
    ...overrides,
  };
}

describe('isRunStuck', () => {
  it('returns not stuck for a non-active run (paused)', () => {
    const run = makeRun({ status: 'paused' });
    expect(isRunStuck(run)).toEqual({ stuck: false, failedTask: null });
  });

  it('returns not stuck for an active run with no steps', () => {
    const run = makeRun({ status: 'active', steps: [] });
    expect(isRunStuck(run)).toEqual({ stuck: false, failedTask: null });
  });

  it('returns stuck when a top-level task has failed at max_attempts', () => {
    const task = makeTask({
      status: 'failed',
      current_attempt: 3,
      max_attempts: 3,
      parent_task_id: null,
      title: 'Build Step',
    });
    const run = makeRun({ steps: [makeStep([task])] });
    expect(isRunStuck(run)).toEqual({ stuck: true, failedTask: 'Build Step' });
  });

  it('returns not stuck when a task has failed but still has remaining attempts', () => {
    const task = makeTask({
      status: 'failed',
      current_attempt: 2,
      max_attempts: 3,
      parent_task_id: null,
    });
    const run = makeRun({ steps: [makeStep([task])] });
    expect(isRunStuck(run)).toEqual({ stuck: false, failedTask: null });
  });

  it('returns not stuck when a child task has failed at max_attempts (parent_task_id set)', () => {
    const task = makeTask({
      status: 'failed',
      current_attempt: 3,
      max_attempts: 3,
      parent_task_id: 'parent-task-99',
    });
    const run = makeRun({ steps: [makeStep([task])] });
    expect(isRunStuck(run)).toEqual({ stuck: false, failedTask: null });
  });

  it('falls back to config_id as failedTask when title is falsy', () => {
    const task = makeTask({
      status: 'failed',
      current_attempt: 5,
      max_attempts: 5,
      parent_task_id: null,
      title: '',
      config_id: 'my-config-id',
    });
    const run = makeRun({ steps: [makeStep([task])] });
    expect(isRunStuck(run)).toEqual({ stuck: true, failedTask: 'my-config-id' });
  });
});
