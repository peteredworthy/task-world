import { describe, it, expect } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StepTimeline } from '../../src/components/dashboard/StepTimeline';
import type { StepSummary, TaskSummary } from '../../src/types';

function makeTask(overrides: Partial<TaskSummary> & { id: string; config_id: string; status: TaskSummary['status'] }): TaskSummary {
  return {
    title: '',
    current_attempt: 0,
    max_attempts: 3,
    grade_summary: [],
    attempts_summary: [],
    ...overrides,
  };
}

function makeStep(overrides: Partial<StepSummary> & { id: string; config_id: string }): StepSummary {
  return {
    title: '',
    completed: false,
    has_approval_gate: false,
    approval_status: null,
    tasks: [],
    ...overrides,
  };
}

function renderTimeline(steps: StepSummary[], currentStepIndex: number) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <StepTimeline runId="run-1" steps={steps} currentStepIndex={currentStepIndex} />
    </QueryClientProvider>,
  );
}

describe('StepTimeline', () => {
  it('renders nothing when steps is empty', () => {
    cleanup();
    const { container } = renderTimeline([], 0);
    expect(container.firstChild).toBeNull();
  });

  it('renders a badge for each step', () => {
    cleanup();
    const steps: StepSummary[] = [
      makeStep({ id: 's1', config_id: 'cfg1', tasks: [] }),
      makeStep({ id: 's2', config_id: 'cfg2', tasks: [] }),
      makeStep({ id: 's3', config_id: 'cfg3', tasks: [] }),
    ];
    renderTimeline(steps, 0);
    const badges = screen.getAllByRole('img');
    expect(badges).toHaveLength(3);
  });

  it('step badges have tabIndex={0} for keyboard focus', () => {
    cleanup();
    const steps: StepSummary[] = [
      makeStep({ id: 's1', config_id: 'cfg1', tasks: [] }),
    ];
    renderTimeline(steps, 0);
    const badge = screen.getByRole('img');
    expect(badge).toHaveAttribute('tabindex', '0');
  });

  it('step badges have role="img" and aria-label', () => {
    cleanup();
    const steps: StepSummary[] = [
      makeStep({
        id: 's1',
        config_id: 'cfg1',
        tasks: [
          makeTask({ id: 't1', config_id: 'tc1', status: 'completed', current_attempt: 1 }),
          makeTask({ id: 't2', config_id: 'tc2', status: 'pending', current_attempt: 0 }),
        ],
      }),
    ];
    renderTimeline(steps, 0);
    const badge = screen.getByRole('img');
    expect(badge).toHaveAttribute('aria-label', 'Step 1: 1/2 tasks, active');
  });

  it('completed step renders with accent-purple background', () => {
    cleanup();
    const steps: StepSummary[] = [
      makeStep({
        id: 's1',
        config_id: 'cfg1',
        completed: true,
        tasks: [
          makeTask({ id: 't1', config_id: 'tc1', status: 'completed', current_attempt: 1 }),
        ],
      }),
    ];
    renderTimeline(steps, 1);
    const badge = screen.getByRole('img');
    expect(badge.className).toContain('bg-accent-purple');
  });

  it('current step renders with status-active background', () => {
    cleanup();
    const steps: StepSummary[] = [
      makeStep({
        id: 's1',
        config_id: 'cfg1',
        tasks: [
          makeTask({ id: 't1', config_id: 'tc1', status: 'building', current_attempt: 1 }),
        ],
      }),
    ];
    renderTimeline(steps, 0);
    const badge = screen.getByRole('img');
    expect(badge.className).toContain('bg-status-active');
  });

  it('failed step renders with status-failed background', () => {
    cleanup();
    const steps: StepSummary[] = [
      makeStep({
        id: 's1',
        config_id: 'cfg1',
        tasks: [
          makeTask({ id: 't1', config_id: 'tc1', status: 'failed', current_attempt: 1 }),
        ],
      }),
    ];
    renderTimeline(steps, 1);
    const badge = screen.getByRole('img');
    expect(badge.className).toContain('bg-status-failed');
  });

  it('pending step renders with transparent background and border', () => {
    cleanup();
    const steps: StepSummary[] = [
      makeStep({
        id: 's1',
        config_id: 'cfg1',
        tasks: [
          makeTask({ id: 't1', config_id: 'tc1', status: 'pending', current_attempt: 0 }),
        ],
      }),
    ];
    renderTimeline(steps, 1);
    const badge = screen.getByRole('img');
    expect(badge.className).toContain('bg-transparent');
  });

  it('aria-label shows correct task counts for multi-task step', () => {
    cleanup();
    const steps: StepSummary[] = [
      makeStep({
        id: 's1',
        config_id: 'cfg1',
        tasks: [
          makeTask({ id: 't1', config_id: 'tc1', status: 'completed', current_attempt: 1 }),
          makeTask({ id: 't2', config_id: 'tc2', status: 'completed', current_attempt: 1 }),
          makeTask({ id: 't3', config_id: 'tc3', status: 'building', current_attempt: 1 }),
        ],
      }),
    ];
    renderTimeline(steps, 0);
    const badge = screen.getByRole('img');
    expect(badge).toHaveAttribute('aria-label', 'Step 1: 2/3 tasks, active');
  });
});
