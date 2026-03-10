import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StepTimeline } from '../StepTimeline';
import type { StepSummary } from '../../../types';

afterEach(cleanup);

function makeStep(stepId: string, completed: boolean, overrides: Partial<StepSummary> = {}): StepSummary {
  return {
    id: stepId,
    config_id: `${stepId}-cfg`,
    title: stepId,
    completed,
    has_approval_gate: false,
    approval_status: null,
    tasks: [],
    skipped: false,
    skip_reason: null,
    condition: null,
    ...overrides,
  };
}

function renderTimeline(
  steps: StepSummary[],
  currentStepIndex: number,
  pendingCount = 0,
  onPendingClick?: () => void,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <StepTimeline
        runId="run-1"
        steps={steps}
        currentStepIndex={currentStepIndex}
        showRevert
        pendingCount={pendingCount}
        onPendingClick={onPendingClick}
      />
    </QueryClientProvider>,
  );
}

describe('StepTimeline', () => {
  it('shows revert action only on completed steps before current', () => {
    renderTimeline(
      [
        makeStep('step-1', true),
        makeStep('step-2', false),
        makeStep('step-3', false),
      ],
      1,
    );

    expect(screen.getByRole('button', { name: 'Revert to step 1' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Revert to step 2' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Revert to step 3' })).not.toBeInTheDocument();
  });

  it('opens confirmation dialog on revert click', async () => {
    renderTimeline(
      [
        makeStep('step-1', true),
        makeStep('step-2', false),
      ],
      1,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Revert to step 1' }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Revert to this step?')).toBeInTheDocument();
    expect(screen.getByText('This will reset all tasks from step 1 onward to PENDING')).toBeInTheDocument();
    expect(screen.getByLabelText('Reason (optional)')).toBeInTheDocument();
  });

  describe('Skipped step rendering', () => {
    it('renders skipped step with dashed border class', () => {
      renderTimeline(
        [
          makeStep('step-1', false, {
            skipped: true,
            skip_reason: 'Condition not met',
          }),
        ],
        0,
      );

      const stepBadge = screen.getByRole('img', { name: /Step 1/ });
      expect(stepBadge).toHaveClass('border-dashed');
      expect(stepBadge).toHaveClass('border');
    });

    it('displays "Skipped" text instead of step number', () => {
      renderTimeline(
        [
          makeStep('step-1', false, {
            skipped: true,
            skip_reason: 'Condition not met',
          }),
        ],
        0,
      );

      expect(screen.getByText('Skipped')).toBeInTheDocument();
    });

    it('shows skip reason in tooltip on hover', async () => {
      renderTimeline(
        [
          makeStep('step-1', false, {
            skipped: true,
            skip_reason: 'Condition not met',
          }),
        ],
        0,
      );

      const stepBadge = screen.getByRole('img', { name: /Step 1/ });
      await userEvent.hover(stepBadge);

      expect(screen.getByText('Step 1: Skipped - Condition not met')).toBeInTheDocument();
    });

    it('includes skip reason in tooltip text', () => {
      renderTimeline(
        [
          makeStep('step-1', false, {
            skipped: true,
            skip_reason: 'Test condition failed',
          }),
        ],
        0,
      );

      const stepBadge = screen.getByRole('img', { name: /Step 1/ });
      const tooltip = stepBadge.querySelector('.group-hover\\/steptip\\:opacity-100');
      expect(tooltip?.textContent).toContain('Skipped - Test condition failed');
    });
  });

  describe('Pending conditional step rendering', () => {
    it('shows condition text in tooltip for pending conditional step', async () => {
      renderTimeline(
        [
          makeStep('step-1', false, {
            condition: {
              when: 'environment === "production"',
              repeat_for: null,
            },
          }),
        ],
        0,
      );

      const stepBadge = screen.getByRole('img', { name: /Step 1/ });
      await userEvent.hover(stepBadge);

      expect(screen.getByText('Step 1: Pending - when: environment === "production"')).toBeInTheDocument();
    });

    it('does not show condition text for completed conditional step', () => {
      renderTimeline(
        [
          makeStep('step-1', true, {
            condition: {
              when: 'environment === "production"',
              repeat_for: null,
            },
          }),
        ],
        0,
      );

      const stepBadge = screen.getByRole('img', { name: /Step 1/ });
      const tooltip = stepBadge.querySelector('.group-hover\\/steptip\\:opacity-100');
      expect(tooltip?.textContent).not.toContain('Pending - when:');
    });
  });

  describe('Repeat for iterations', () => {
    it('renders repeat_for iterations as sub-item text', () => {
      renderTimeline(
        [
          makeStep('step-1', false, {
            condition: {
              when: 'has_changes',
              repeat_for: '[0, 1, 2]',
            },
          }),
        ],
        0,
      );

      expect(screen.getByText('for [0, 1, 2]')).toBeInTheDocument();
    });

    it('displays repeat_for with correct styling', () => {
      renderTimeline(
        [
          makeStep('step-1', false, {
            condition: {
              when: null,
              repeat_for: 'items in array',
            },
          }),
        ],
        0,
      );

      const repeatText = screen.getByText('for items in array');
      expect(repeatText).toHaveClass('text-[9px]');
      expect(repeatText).toHaveClass('italic');
    });

    it('does not render repeat_for when not present', () => {
      renderTimeline(
        [
          makeStep('step-1', false, {
            condition: null,
          }),
        ],
        0,
      );

      expect(screen.queryByText(/^for /)).not.toBeInTheDocument();
    });

    it('does not render repeat_for when condition is null', () => {
      renderTimeline(
        [
          makeStep('step-1', false, {
            condition: null,
          }),
        ],
        0,
      );

      const repeatElements = screen.queryAllByText(/^for /);
      expect(repeatElements).toHaveLength(0);
    });
  });

  describe('Pending action badge', () => {
    it('shows pending action count badge on current step', () => {
      renderTimeline(
        [
          makeStep('step-1', false),
          makeStep('step-2', false),
        ],
        0,
        2,
      );

      expect(screen.getByText('2')).toBeInTheDocument();
      const badge = screen.getByRole('img', { name: /Step 1/ }).querySelector('.bg-status-paused');
      expect(badge?.textContent).toContain('2');
    });

    it('clicking pending action badge calls onPendingClick', async () => {
      const onPendingClick = vi.fn();
      renderTimeline(
        [
          makeStep('step-1', false),
        ],
        0,
        1,
        onPendingClick,
      );

      const button = screen.getByRole('button', {
        name: /1 pending action.*open now/i,
      });
      await userEvent.click(button);

      expect(onPendingClick).toHaveBeenCalled();
    });

    it('does not show pending badge on non-current steps', () => {
      renderTimeline(
        [
          makeStep('step-1', true),
          makeStep('step-2', false),
        ],
        1,
        2,
      );

      const step1Badge = screen.getByRole('img', { name: /Step 1/ });
      expect(step1Badge).not.toHaveClass('bg-status-paused');
    });
  });
});
