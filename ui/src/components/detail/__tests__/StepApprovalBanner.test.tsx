import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StepApprovalBanner } from '../StepApprovalBanner';
import type { StepSummary } from '../../../../types';

afterEach(cleanup);

function makeStep(overrides: Partial<StepSummary> = {}): StepSummary {
  return {
    id: 'step-1',
    config_id: 'step_cfg',
    title: 'Approval Step',
    completed: false,
    has_approval_gate: true,
    approval_status: 'pending',
    tasks: [],
    ...overrides,
  };
}

function renderBanner(step: StepSummary) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <StepApprovalBanner runId="run-1" step={step} />
    </QueryClientProvider>,
  );
}

describe('StepApprovalBanner', () => {
  it('renders banner for pending approval gate', () => {
    renderBanner(makeStep());

    expect(screen.getByText('Step approval required')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve Step' })).toBeInTheDocument();
  });

  it('renders nothing when no pending gate', () => {
    const { container } = renderBanner(
      makeStep({ has_approval_gate: false, approval_status: null }),
    );

    expect(container).toBeEmptyDOMElement();
  });
});
