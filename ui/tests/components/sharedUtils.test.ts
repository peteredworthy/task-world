import { describe, expect, it } from 'vitest';
import { getLatestAttemptContext } from '../../src/components/detail/sharedUtils';
import type { AttemptSchema, TaskStatus } from '../../src/types';

function makeAttempt(overrides: Partial<AttemptSchema> = {}): AttemptSchema {
  return {
    id: 'a1',
    attempt_num: 1,
    started_at: null,
    completed_at: null,
    builder_prompt: null,
    verifier_prompt: null,
    verifier_comment: null,
    outcome: null,
    metrics: {},
    grade_snapshot: [],
    auto_verify_results: null,
    agent_runner_type: null,
    agent_model: null,
    agent_settings: {},
    error: null,
    has_output: false,
    has_action_log: false,
    start_commit: null,
    end_commit: null,
    ...overrides,
  };
}

function contextFor(status: TaskStatus, attempt: AttemptSchema) {
  return getLatestAttemptContext([attempt], status);
}

describe('getLatestAttemptContext', () => {
  it('hides failure cards when an attempt is active again in building', () => {
    const activeAttempt = makeAttempt({
      error: "Agent runner 'cli_subprocess' execution failed",
      auto_verify_results: [{ passed: false }],
      verifier_comment: 'Auto-verify failed. Fix and resubmit.',
      completed_at: null,
    });

    const context = contextFor('building', activeAttempt);

    expect(context.isActiveAttempt).toBe(true);
    expect(context.showFailureCard).toBe(false);
    expect(context.showFeedbackCard).toBe(false);
  });

  it('shows failure cards for inactive/terminal task states', () => {
    const terminalAttempt = makeAttempt({
      completed_at: '2026-03-09T18:18:20Z',
      error: 'boom',
      outcome: 'failed',
    });

    const context = contextFor('failed', terminalAttempt);

    expect(context.isActiveAttempt).toBe(false);
    expect(context.showFailureCard).toBe(true);
  });

  it('labels auto-verify generated verifier_comment as auto-verify feedback', () => {
    const attempt = makeAttempt({
      completed_at: '2026-03-09T18:18:20Z',
      auto_verify_results: [{ passed: false }],
      verifier_comment: 'Auto-verify failed. Fix this and resubmit.',
    });

    const context = contextFor('failed', attempt);

    expect(context.showFeedbackCard).toBe(true);
    expect(context.feedbackTitle).toBe('Auto-verify Feedback');
  });
});
