import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { BranchStatusPanel } from '../BranchStatusPanel';
import * as apiHooks from '../../../hooks/useApi';

vi.mock('../../../hooks/useApi', () => ({
  useBranchStatus: vi.fn(),
  useBackMerge: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('BranchStatusPanel', () => {
  it('renders ahead and behind counts', () => {
    vi.spyOn(apiHooks, 'useBranchStatus').mockReturnValue({
      data: {
        source_branch: 'main',
        run_branch: 'orchestrator/run-123',
        behind_count: 4,
        ahead_count: 2,
        can_merge_cleanly: true,
        has_conflicts: false,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as any);
    vi.spyOn(apiHooks, 'useBackMerge').mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as any);

    render(<BranchStatusPanel runId="run-1" />);

    expect(screen.getByText('Behind')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('Ahead')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('shows conflict warning when has_conflicts is true', () => {
    vi.spyOn(apiHooks, 'useBranchStatus').mockReturnValue({
      data: {
        source_branch: 'main',
        run_branch: 'orchestrator/run-123',
        behind_count: 1,
        ahead_count: 0,
        can_merge_cleanly: false,
        has_conflicts: true,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as any);
    vi.spyOn(apiHooks, 'useBackMerge').mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as any);

    render(<BranchStatusPanel runId="run-1" />);

    expect(screen.getByText('Merge conflicts detected. Resolve conflicts before pulling upstream changes.')).toBeInTheDocument();
  });
});
