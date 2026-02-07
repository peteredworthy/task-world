import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AttemptHistory } from '../../src/components/detail/AttemptHistory';
import type { AttemptSchema } from '../../src/types';

afterEach(cleanup);

function makeAttempt(overrides: Partial<AttemptSchema> & { id: string; attempt_num: number }): AttemptSchema {
  return {
    started_at: null,
    completed_at: null,
    outcome: null,
    metrics: {},
    ...overrides,
  };
}

describe('AttemptHistory', () => {
  it('renders empty state message when no attempts', () => {
    render(<AttemptHistory attempts={[]} />);
    expect(screen.getByText('No attempts yet')).toBeInTheDocument();
  });

  it('shows latest attempt by default when multiple attempts exist', () => {
    const attempts = [
      makeAttempt({ id: 'a1', attempt_num: 1, outcome: 'revision_needed' }),
      makeAttempt({ id: 'a2', attempt_num: 2, outcome: 'passed' }),
    ];
    render(<AttemptHistory attempts={attempts} />);

    // Only the latest (last) attempt should be visible
    expect(screen.getByText('#2')).toBeInTheDocument();
    expect(screen.queryByText('#1')).not.toBeInTheDocument();
  });

  it('shows single attempt without expand button', () => {
    const attempts = [
      makeAttempt({ id: 'a1', attempt_num: 1, outcome: 'passed' }),
    ];
    render(<AttemptHistory attempts={attempts} />);
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(screen.queryByText(/Show all/)).not.toBeInTheDocument();
  });

  it('expand/collapse to show all attempts', async () => {
    const attempts = [
      makeAttempt({ id: 'a1', attempt_num: 1, outcome: 'revision_needed' }),
      makeAttempt({ id: 'a2', attempt_num: 2, outcome: 'revision_needed' }),
      makeAttempt({ id: 'a3', attempt_num: 3, outcome: 'passed' }),
    ];
    render(<AttemptHistory attempts={attempts} />);

    // Initially only latest is shown
    expect(screen.queryByText('#1')).not.toBeInTheDocument();
    expect(screen.queryByText('#2')).not.toBeInTheDocument();
    expect(screen.getByText('#3')).toBeInTheDocument();

    // Click to expand
    await userEvent.click(screen.getByText('Show all 3 attempts'));

    // All attempts should be visible
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(screen.getByText('#2')).toBeInTheDocument();
    expect(screen.getByText('#3')).toBeInTheDocument();

    // Click to collapse
    await userEvent.click(screen.getByText('Show latest only'));

    // Back to only latest
    expect(screen.queryByText('#1')).not.toBeInTheDocument();
    expect(screen.queryByText('#2')).not.toBeInTheDocument();
    expect(screen.getByText('#3')).toBeInTheDocument();
  });

  it('displays Passed outcome with status-completed color class', () => {
    const attempts = [
      makeAttempt({ id: 'a1', attempt_num: 1, outcome: 'passed' }),
    ];
    render(<AttemptHistory attempts={attempts} />);
    const outcomeEl = screen.getByText('Passed');
    expect(outcomeEl.className).toContain('text-status-completed');
  });

  it('displays Revision outcome with status-paused color class', () => {
    const attempts = [
      makeAttempt({ id: 'a1', attempt_num: 1, outcome: 'revision_needed' }),
    ];
    render(<AttemptHistory attempts={attempts} />);
    const outcomeEl = screen.getByText('Revision');
    expect(outcomeEl.className).toContain('text-status-paused');
  });

  it('displays Failed outcome with status-failed color class', () => {
    const attempts = [
      makeAttempt({ id: 'a1', attempt_num: 1, outcome: 'failed' }),
    ];
    render(<AttemptHistory attempts={attempts} />);
    const outcomeEl = screen.getByText('Failed');
    expect(outcomeEl.className).toContain('text-status-failed');
  });

  it('does not render outcome element when outcome is null', () => {
    const attempts = [
      makeAttempt({ id: 'a1', attempt_num: 1, outcome: null }),
    ];
    render(<AttemptHistory attempts={attempts} />);
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(screen.queryByText('Passed')).not.toBeInTheDocument();
    expect(screen.queryByText('Revision')).not.toBeInTheDocument();
    expect(screen.queryByText('Failed')).not.toBeInTheDocument();
  });

  it('displays formatted duration when duration_ms metric is present', () => {
    const attempts = [
      makeAttempt({ id: 'a1', attempt_num: 1, metrics: { duration_ms: 5000 } }),
    ];
    render(<AttemptHistory attempts={attempts} />);
    expect(screen.getByText('5s')).toBeInTheDocument();
  });

  it('displays formatted token counts when present', () => {
    const attempts = [
      makeAttempt({ id: 'a1', attempt_num: 1, metrics: { tokens_read: 1500, tokens_write: 300 } }),
    ];
    render(<AttemptHistory attempts={attempts} />);
    expect(screen.getByText('1.5k read')).toBeInTheDocument();
    expect(screen.getByText('300 write')).toBeInTheDocument();
  });

  it('does not display duration when duration_ms is 0', () => {
    const attempts = [
      makeAttempt({ id: 'a1', attempt_num: 1, metrics: { duration_ms: 0 } }),
    ];
    render(<AttemptHistory attempts={attempts} />);
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(screen.queryByText('0ms')).not.toBeInTheDocument();
  });

  it('does not display tokens when counts are 0', () => {
    const attempts = [
      makeAttempt({ id: 'a1', attempt_num: 1, metrics: { tokens_read: 0, tokens_write: 0 } }),
    ];
    render(<AttemptHistory attempts={attempts} />);
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(screen.queryByText('read')).not.toBeInTheDocument();
    expect(screen.queryByText('write')).not.toBeInTheDocument();
  });
});
