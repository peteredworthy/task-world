import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StepTimeline } from '../StepTimeline';
import type { StepSummary } from '../../../types';

afterEach(cleanup);

function makeStep(stepId: string, completed: boolean): StepSummary {
  return {
    id: stepId,
    config_id: `${stepId}-cfg`,
    title: stepId,
    completed,
    has_approval_gate: false,
    approval_status: null,
    tasks: [],
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
});
