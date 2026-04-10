import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WaitingIndicator } from '../../src/components/guidance/WaitingIndicator';
import * as apiHooks from '../../src/hooks/useApi';

vi.mock('../../src/hooks/useApi', () => ({
  useAgentCancelled: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('WaitingIndicator', () => {
  it('calls useAgentCancelled mutation when cancel is clicked', async () => {
    const mutate = vi.fn();
    vi.spyOn(apiHooks, 'useAgentCancelled').mockReturnValue({
      mutate,
      isPending: false,
    } as any);

    const { container } = render(
      <WaitingIndicator runId="run-1" startedAt={new Date().toISOString()} />
    );

    await userEvent.click(within(container).getByText('Cancel'));
    expect(mutate).toHaveBeenCalledOnce();
  });

  it('renders waiting text', () => {
    vi.spyOn(apiHooks, 'useAgentCancelled').mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as any);

    render(<WaitingIndicator runId="run-1" startedAt={new Date().toISOString()} />);
    expect(screen.getByText('Waiting for agent to submit work...')).toBeInTheDocument();
  });

  it('renders cancel button', () => {
    vi.spyOn(apiHooks, 'useAgentCancelled').mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as any);

    const { container } = render(<WaitingIndicator runId="run-1" startedAt={new Date().toISOString()} />);
    expect(within(container).getByText('Cancel')).toBeInTheDocument();
  });
});
