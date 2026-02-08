import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BranchSelector } from '../../src/components/BranchSelector';
import * as useApiModule from '../../src/hooks/useApi';
import type { BranchCountResponse, BranchesListResponse } from '../../src/types';

afterEach(cleanup);

// Mock the useApi hooks
vi.mock('../../src/hooks/useApi');

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function renderBranchSelector(props: {
  repoName: string;
  value: string;
  onChange: (branch: string) => void;
  includeRemote?: boolean;
}) {
  const qc = makeQueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <BranchSelector {...props} />
    </QueryClientProvider>
  );
}

describe('BranchSelector', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders input with placeholder', () => {
    vi.spyOn(useApiModule, 'useBranchCount').mockReturnValue({
      data: { count: 0, pattern: '*' },
    } as ReturnType<typeof useApiModule.useBranchCount>);

    vi.spyOn(useApiModule, 'useBranches').mockReturnValue({
      data: undefined,
    } as ReturnType<typeof useApiModule.useBranches>);

    const onChange = vi.fn();
    renderBranchSelector({ repoName: 'test-repo', value: '', onChange });

    expect(screen.getByPlaceholderText('e.g. main or feature/*')).toBeInTheDocument();
  });

  it('shows initial value in input', () => {
    vi.spyOn(useApiModule, 'useBranchCount').mockReturnValue({
      data: { count: 1, pattern: 'main' },
    } as ReturnType<typeof useApiModule.useBranchCount>);

    vi.spyOn(useApiModule, 'useBranches').mockReturnValue({
      data: undefined,
    } as ReturnType<typeof useApiModule.useBranches>);

    const onChange = vi.fn();
    renderBranchSelector({ repoName: 'test-repo', value: 'main', onChange });

    expect(screen.getByDisplayValue('main')).toBeInTheDocument();
  });

  it('calls onChange when input changes', async () => {
    vi.spyOn(useApiModule, 'useBranchCount').mockReturnValue({
      data: { count: 0, pattern: '*' },
    } as ReturnType<typeof useApiModule.useBranchCount>);

    vi.spyOn(useApiModule, 'useBranches').mockReturnValue({
      data: undefined,
    } as ReturnType<typeof useApiModule.useBranches>);

    const onChange = vi.fn();
    renderBranchSelector({ repoName: 'test-repo', value: '', onChange });

    const input = screen.getByPlaceholderText('e.g. main or feature/*');
    await userEvent.type(input, 'develop');

    expect(onChange).toHaveBeenCalled();
    expect(onChange).toHaveBeenLastCalledWith('develop');
  });

  it('shows dropdown with branches when count <= 100', async () => {
    const branchesData: BranchesListResponse = {
      branches: [
        { name: 'main', is_remote: false, commit: 'abc123' },
        { name: 'develop', is_remote: false, commit: 'def456' },
      ],
      total: 2,
      truncated: false,
    };

    vi.spyOn(useApiModule, 'useBranchCount').mockReturnValue({
      data: { count: 2, pattern: '*' },
    } as ReturnType<typeof useApiModule.useBranchCount>);

    vi.spyOn(useApiModule, 'useBranches').mockReturnValue({
      data: branchesData,
    } as ReturnType<typeof useApiModule.useBranches>);

    const onChange = vi.fn();
    renderBranchSelector({ repoName: 'test-repo', value: '', onChange });

    const input = screen.getByPlaceholderText('e.g. main or feature/*');
    await userEvent.click(input);

    await waitFor(() => {
      expect(screen.getByText('main')).toBeInTheDocument();
      expect(screen.getByText('develop')).toBeInTheDocument();
    });
  });

  it('shows "refine pattern" message when count > 100', async () => {
    const countData: BranchCountResponse = {
      count: 150,
      pattern: '*',
    };

    vi.spyOn(useApiModule, 'useBranchCount').mockReturnValue({
      data: countData,
    } as ReturnType<typeof useApiModule.useBranchCount>);

    vi.spyOn(useApiModule, 'useBranches').mockReturnValue({
      data: undefined,
    } as ReturnType<typeof useApiModule.useBranches>);

    const onChange = vi.fn();
    renderBranchSelector({ repoName: 'test-repo', value: '', onChange });

    const input = screen.getByPlaceholderText('e.g. main or feature/*');
    await userEvent.click(input);

    await waitFor(() => {
      expect(screen.getByText(/Too many branches \(150\)/)).toBeInTheDocument();
      expect(screen.getByText(/Refine your search pattern/)).toBeInTheDocument();
    });
  });

  it('selects branch from dropdown and updates input', async () => {
    const branchesData: BranchesListResponse = {
      branches: [
        { name: 'main', is_remote: false, commit: 'abc123' },
        { name: 'develop', is_remote: false, commit: 'def456' },
      ],
      total: 2,
      truncated: false,
    };

    vi.spyOn(useApiModule, 'useBranchCount').mockReturnValue({
      data: { count: 2, pattern: '*' },
    } as ReturnType<typeof useApiModule.useBranchCount>);

    vi.spyOn(useApiModule, 'useBranches').mockReturnValue({
      data: branchesData,
    } as ReturnType<typeof useApiModule.useBranches>);

    const onChange = vi.fn();
    renderBranchSelector({ repoName: 'test-repo', value: '', onChange });

    const input = screen.getByPlaceholderText('e.g. main or feature/*');
    await userEvent.click(input);

    await waitFor(() => {
      expect(screen.getByText('develop')).toBeInTheDocument();
    });

    const developButton = screen.getByRole('button', { name: /develop/ });
    await userEvent.click(developButton);

    expect(onChange).toHaveBeenCalledWith('develop');
    expect(screen.getByDisplayValue('develop')).toBeInTheDocument();
  });

  it('shows remote label for remote branches', async () => {
    const branchesData: BranchesListResponse = {
      branches: [
        { name: 'origin/main', is_remote: true, commit: 'abc123' },
        { name: 'main', is_remote: false, commit: 'def456' },
      ],
      total: 2,
      truncated: false,
    };

    vi.spyOn(useApiModule, 'useBranchCount').mockReturnValue({
      data: { count: 2, pattern: '*' },
    } as ReturnType<typeof useApiModule.useBranchCount>);

    vi.spyOn(useApiModule, 'useBranches').mockReturnValue({
      data: branchesData,
    } as ReturnType<typeof useApiModule.useBranches>);

    const onChange = vi.fn();
    renderBranchSelector({ repoName: 'test-repo', value: '', onChange });

    const input = screen.getByPlaceholderText('e.g. main or feature/*');
    await userEvent.click(input);

    await waitFor(() => {
      expect(screen.getByText('origin/main')).toBeInTheDocument();
    });

    // Check for "remote" label
    const remoteLabels = screen.getAllByText('remote');
    expect(remoteLabels).toHaveLength(1);
  });

  it('shows helper text for branch count', async () => {
    vi.spyOn(useApiModule, 'useBranchCount').mockReturnValue({
      data: { count: 5, pattern: 'feature/*' },
    } as ReturnType<typeof useApiModule.useBranchCount>);

    vi.spyOn(useApiModule, 'useBranches').mockReturnValue({
      data: {
        branches: [],
        total: 5,
        truncated: false,
      },
    } as ReturnType<typeof useApiModule.useBranches>);

    const onChange = vi.fn();
    renderBranchSelector({ repoName: 'test-repo', value: '', onChange });

    await waitFor(() => {
      expect(screen.getByText('5 branches match')).toBeInTheDocument();
    });
  });

  it('shows singular "branch" for count of 1', async () => {
    vi.spyOn(useApiModule, 'useBranchCount').mockReturnValue({
      data: { count: 1, pattern: 'main' },
    } as ReturnType<typeof useApiModule.useBranchCount>);

    vi.spyOn(useApiModule, 'useBranches').mockReturnValue({
      data: {
        branches: [{ name: 'main', is_remote: false, commit: 'abc123' }],
        total: 1,
        truncated: false,
      },
    } as ReturnType<typeof useApiModule.useBranches>);

    const onChange = vi.fn();
    renderBranchSelector({ repoName: 'test-repo', value: '', onChange });

    await waitFor(() => {
      expect(screen.getByText('1 branch match')).toBeInTheDocument();
    });
  });

  it('shows no match message when count is 0', async () => {
    vi.spyOn(useApiModule, 'useBranchCount').mockReturnValue({
      data: { count: 0, pattern: 'nonexistent' },
    } as ReturnType<typeof useApiModule.useBranchCount>);

    vi.spyOn(useApiModule, 'useBranches').mockReturnValue({
      data: undefined,
    } as ReturnType<typeof useApiModule.useBranches>);

    const onChange = vi.fn();
    renderBranchSelector({ repoName: 'test-repo', value: 'nonexistent', onChange });

    // Wait for debounce
    await waitFor(() => {
      expect(screen.getByText(/No branches match pattern "nonexistent"/)).toBeInTheDocument();
    }, { timeout: 500 });
  });
});
