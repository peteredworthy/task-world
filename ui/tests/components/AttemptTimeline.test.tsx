import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AttemptTimeline } from '../../src/components/detail/shared';
import type { AttemptSchema, ChecklistItemSchema } from '../../src/types';

function makeAttempt(overrides: Partial<AttemptSchema> & { id: string; attempt_num: number }): AttemptSchema {
  return {
    started_at: null,
    completed_at: null,
    builder_prompt: null,
    verifier_prompt: null,
    verifier_comment: null,
    outcome: null,
    metrics: {},
    grade_snapshot: [],
    auto_verify_results: null,
    agent_type: null,
    agent_model: null,
    agent_settings: {},
    error: null,
    has_output: false,
    has_action_log: false,
    ...overrides,
  };
}

describe('AttemptTimeline', () => {
  it('allows expanding older attempts to inspect details', async () => {
    const attempts: AttemptSchema[] = [
      makeAttempt({
        id: 'a1',
        attempt_num: 1,
        outcome: 'revision_needed',
        verifier_comment: 'First attempt feedback',
        grade_snapshot: [{ req_id: 'req-1', grade: 'C', grade_reason: 'Missing edge case checks' }],
      }),
      makeAttempt({
        id: 'a2',
        attempt_num: 2,
        outcome: 'passed',
        verifier_comment: 'Second attempt accepted',
        grade_snapshot: [{ req_id: 'req-1', grade: 'A', grade_reason: 'Looks good now' }],
      }),
    ];

    const checklist: ChecklistItemSchema[] = [
      {
        req_id: 'req-1',
        desc: 'Handle edge cases',
        priority: 'expected',
        status: 'done',
        note: null,
        grade: 'A',
        grade_reason: 'Looks good now',
      },
    ];

    render(<AttemptTimeline attempts={attempts} checklist={checklist} />);

    // Latest attempt is expanded by default.
    expect(screen.getByText('Second attempt accepted')).toBeInTheDocument();
    expect(screen.queryByText('First attempt feedback')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Attempt #1/i }));

    expect(screen.getByText('First attempt feedback')).toBeInTheDocument();
    expect(screen.getByText('Handle edge cases')).toBeInTheDocument();

    // Compact per-attempt grade chips are always visible in headers.
    expect(screen.getAllByText('A').length).toBeGreaterThan(0);
    expect(screen.getAllByText('C').length).toBeGreaterThan(0);
  });
});
