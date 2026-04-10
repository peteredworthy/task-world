import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ApiError } from '../../../api/client';
import * as apiClient from '../../../api/client';
import { AgentGuidancePanel } from '../AgentGuidancePanel';
import * as apiHooks from '../../../hooks/useApi';
import type { RunResponse } from '../../../types';

vi.mock('../../../hooks/useApi', () => ({
  useGuidance: vi.fn(),
  useAgentStarted: vi.fn(),
  useAgentCancelled: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function makeRun(): RunResponse {
  return {
    id: 'run-1',
    started_at: '2026-02-19T00:00:00Z',
  } as unknown as RunResponse;
}

describe('AgentGuidancePanel', () => {
  it('renders guidance and calls start/cancel lifecycle mutations', async () => {
    const startMutate = vi.fn();
    const cancelMutate = vi.fn();
    vi.spyOn(apiClient, 'getAuthToken').mockReturnValue('token-123');
    vi.spyOn(apiHooks, 'useGuidance').mockReturnValue({
      data: {
        task_id: 'task-1',
        prompt: 'Build the feature and run tests.',
        phase: 'building',
        mcp_url: 'https://example.com/mcp/sse',
        expected_actions: [],
      },
      isLoading: false,
      error: null,
    } as any);
    vi.spyOn(apiHooks, 'useAgentStarted').mockReturnValue({
      mutate: startMutate,
      isPending: false,
    } as any);
    vi.spyOn(apiHooks, 'useAgentCancelled').mockReturnValue({
      mutate: cancelMutate,
      isPending: false,
    } as any);

    render(<AgentGuidancePanel run={makeRun()} />);

    expect(screen.getByText('Task Prompt')).toBeInTheDocument();
    expect(screen.getByText('Build the feature and run tests.')).toBeInTheDocument();
    expect(screen.getByText('https://example.com/mcp/sse')).toBeInTheDocument();
    expect(screen.getByText('Bearer token-123')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: "I've started my agent" }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(startMutate).toHaveBeenCalledOnce();
    expect(cancelMutate).toHaveBeenCalledOnce();
  });

  it('shows fallback when guidance endpoint returns 404', () => {
    vi.spyOn(apiHooks, 'useGuidance').mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new ApiError(404, { detail: 'No active task' }),
    } as any);
    vi.spyOn(apiHooks, 'useAgentStarted').mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as any);

    render(<AgentGuidancePanel run={makeRun()} />);

    expect(screen.getByText('No active task guidance available')).toBeInTheDocument();
  });
});
