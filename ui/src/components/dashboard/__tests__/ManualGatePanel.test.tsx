import { describe, expect, it, beforeEach, vi, afterEach } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { WebSocketProvider } from '../../../context/WebSocketContext';
import { ReviewMergeProvider } from '../../../context/ReviewMergeContext';
import { RunDetail } from '../RunDetail';
import * as useApiModule from '../../../hooks/useApi';
import * as useActivityModule from '../../../hooks/useActivityStream';
import * as usePendingActionsModule from '../../../hooks/usePendingActions';
import * as useWebSocketStatusModule from '../../../hooks/useWebSocketStatus';
import * as useReviewModule from '../../../hooks/useReview';
import * as useReviewMergeModule from '../../../context/useReviewMerge';
import type { RunResponse, StepSummary } from '../../../types';

afterEach(cleanup);

function createMockStep(overrides: Partial<StepSummary> = {}): StepSummary {
  return {
    id: 'step-1',
    config_id: 'step-1-cfg',
    title: 'Test Step',
    completed: false,
    tasks: [],
    has_approval_gate: false,
    approval_status: null,
    skipped: false,
    skip_reason: null,
    condition: null,
    ...overrides,
  };
}

function createMockRun(overrides: Partial<RunResponse> = {}): RunResponse {
  return {
    id: 'run-1',
    repo_name: 'test-repo',
    status: 'paused',
    pause_reason: 'manual_gate',
    last_error: null,
    routine_id: 'routine-1',
    routine_sha: 'abc123',
    routine_source: 'embedded',
    routine_embedded: { name: 'Test Routine' },
    agent_type: 'user_managed',
    agent_type_display: 'User Managed',
    agent_icon: 'icon',
    agent_config: {},
    worktree_enabled: false,
    worktree_path: null,
    source_branch: 'main',
    merge_strategy: 'squash',
    config: {},
    env_file_specs: [],
    env_source_dir: null,
    steps: [createMockStep()],
    current_step_index: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    completed_at: null,
    agent_started_at: null,
    total_tokens_read: 0,
    total_tokens_write: 0,
    total_tokens_cache: 0,
    total_duration_ms: 0,
    estimated_cost_usd: null,
    cost_disclaimer: null,
    ...overrides,
  };
}

function renderRunDetail() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <WebSocketProvider>
          <ReviewMergeProvider>
            <RunDetail />
          </ReviewMergeProvider>
        </WebSocketProvider>
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

describe('Manual Gate Panel', () => {
  beforeEach(() => {
    // Setup default mocks
    vi.spyOn(useApiModule, 'useRun').mockReturnValue({
      data: createMockRun(),
      isLoading: false,
      error: null,
    } as any);

    vi.spyOn(useApiModule, 'useRoutine').mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    } as any);

    vi.spyOn(useActivityModule, 'useActivityStream').mockReturnValue({
      data: { events: [] },
      isLoading: false,
      error: null,
    } as any);

    vi.spyOn(usePendingActionsModule, 'usePendingActions').mockReturnValue({
      data: { pendingActions: [], badgeCount: 0 },
      isLoading: false,
      error: null,
    } as any);

    vi.spyOn(useWebSocketStatusModule, 'useWebSocketStatus').mockReturnValue({
      status: 'connected',
      reconnect: vi.fn(),
    } as any);

    vi.spyOn(useReviewModule, 'useBranchStatus').mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    } as any);

    vi.spyOn(useReviewMergeModule, 'useReviewMerge').mockReturnValue({
      isPruneMode: false,
      onTogglePruneMode: vi.fn(),
      onOpenBackMergeModal: vi.fn(),
    } as any);

    vi.spyOn(useApiModule, 'usePauseRun').mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as any);

    vi.spyOn(useApiModule, 'useCancelRun').mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as any);

    vi.spyOn(useApiModule, 'useMergeBack').mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as any);

    vi.spyOn(useApiModule, 'useResumeRun').mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as any);

    vi.spyOn(useApiModule, 'useSkipStep').mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as any);

    vi.spyOn(useApiModule, 'useTransitionBack').mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as any);
  });

  it('shows manual gate panel when run is paused at manual gate', () => {
    renderRunDetail();

    expect(screen.getByText(/Manual gate: Step 1/)).toBeInTheDocument();
    expect(screen.getByText('Choose to execute or skip this step.')).toBeInTheDocument();
  });

  it('displays Execute Step and Skip Step buttons', () => {
    renderRunDetail();

    expect(screen.getByRole('button', { name: 'Execute this step' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Skip this step' })).toBeInTheDocument();
  });

  it('calls resumeRun.mutate when Execute Step is clicked', async () => {
    const mockResume = vi.fn();
    vi.spyOn(useApiModule, 'useResumeRun').mockReturnValue({
      mutate: mockResume,
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as any);

    renderRunDetail();

    const executeButton = screen.getByRole('button', { name: 'Execute this step' });
    await userEvent.click(executeButton);

    expect(mockResume).toHaveBeenCalledWith(
      { runId: 'run-1' },
      expect.objectContaining({
        onError: expect.any(Function),
      })
    );
  });

  it('calls skipStep.mutate when Skip Step is clicked', async () => {
    const mockSkip = vi.fn();
    vi.spyOn(useApiModule, 'useSkipStep').mockReturnValue({
      mutate: mockSkip,
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as any);

    renderRunDetail();

    const skipButton = screen.getByRole('button', { name: 'Skip this step' });
    await userEvent.click(skipButton);

    expect(mockSkip).toHaveBeenCalledWith(
      'step-1',
      expect.objectContaining({
        onError: expect.any(Function),
      })
    );
  });

  it('has proper aria labels on buttons', () => {
    renderRunDetail();

    const executeButton = screen.getByRole('button', { name: 'Execute this step' });
    const skipButton = screen.getByRole('button', { name: 'Skip this step' });

    expect(executeButton).toHaveAttribute('aria-label', 'Execute this step');
    expect(skipButton).toHaveAttribute('aria-label', 'Skip this step');
  });

  it('hides manual gate panel when not paused at manual gate', () => {
    vi.spyOn(useApiModule, 'useRun').mockReturnValue({
      data: createMockRun({ pause_reason: 'manual_pause' }),
      isLoading: false,
      error: null,
    } as any);

    renderRunDetail();

    expect(screen.queryByText(/Manual gate:/)).not.toBeInTheDocument();
  });

  it('hides manual gate panel when run is active', () => {
    vi.spyOn(useApiModule, 'useRun').mockReturnValue({
      data: createMockRun({ status: 'active', pause_reason: null }),
      isLoading: false,
      error: null,
    } as any);

    renderRunDetail();

    expect(screen.queryByText(/Manual gate:/)).not.toBeInTheDocument();
  });

  it('shows the correct step number in manual gate panel', () => {
    vi.spyOn(useApiModule, 'useRun').mockReturnValue({
      data: createMockRun({
        steps: [
          createMockStep({ completed: true }),
          createMockStep({ id: 'step-2' }),
        ],
        current_step_index: 1,
      }),
      isLoading: false,
      error: null,
    } as any);

    renderRunDetail();

    expect(screen.getByText(/Manual gate: Step 2/)).toBeInTheDocument();
  });
});
