import { afterEach, describe, it, expect } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import type { AgentOption, AgentQuota } from '../types/agents';

afterEach(() => {
  cleanup();
});

function makeQuota(overrides: Partial<AgentQuota> = {}): AgentQuota {
  return {
    balance_usd: 10.00,
    balance_pct: null,
    max_balance_usd: 100.00,
    label: 'Test quota',
    supports_quota: true,
    ...overrides,
  };
}

function makeAgent(overrides: Partial<AgentOption> = {}): AgentOption {
  return {
    agent_type: 'test_agent',
    name: 'Test Agent',
    title: 'Test Agent Title',
    description: 'A test agent description',
    available: true,
    detail: 'Test agent detail',
    install_hint: 'No install needed',
    config_schema: [],
    quota: null,
    ...overrides,
  };
}

function renderSidebar(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('Sidebar quota section', () => {
  it('shows skeleton while loading', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    // Initiate a never-resolving fetch so the agents query stays in loading state
    void queryClient.fetchQuery({
      queryKey: ['agents'],
      queryFn: (): Promise<AgentOption[]> => new Promise(() => {}),
    });

    const { container } = renderSidebar(queryClient);

    expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
  });

  it('hides section when all agents have null quota', () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData<AgentOption[]>(['agents'], [
      makeAgent({ agent_type: 'agent1', name: 'Agent One', quota: null }),
      makeAgent({ agent_type: 'agent2', name: 'Agent Two', quota: null }),
    ]);

    renderSidebar(queryClient);

    expect(screen.queryByText('Agent Quotas')).not.toBeInTheDocument();
    expect(screen.queryByText('Agent One')).not.toBeInTheDocument();
    expect(screen.queryByText('Agent Two')).not.toBeInTheDocument();
  });

  it('hides section on error', async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, refetchOnMount: false },
      },
    });
    // prefetchQuery silently swallows errors, leaving the query in error state
    await queryClient.prefetchQuery({
      queryKey: ['agents'],
      queryFn: () => Promise.reject(new Error('Network error')),
    });

    renderSidebar(queryClient);

    // The quota section heading must not appear regardless of whether
    // the component is in error or loading-during-refetch state
    expect(screen.queryByText('Agent Quotas')).not.toBeInTheDocument();
  });

  it('renders one row per agent with non-null quota', () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData<AgentOption[]>(['agents'], [
      makeAgent({ agent_type: 'agent1', name: 'Agent Alpha', quota: makeQuota({ balance_usd: 5.00 }) }),
      makeAgent({ agent_type: 'agent2', name: 'Agent Beta', quota: makeQuota({ balance_usd: 10.00 }) }),
      makeAgent({ agent_type: 'agent3', name: 'Agent Gamma', quota: null }),
    ]);

    renderSidebar(queryClient);

    expect(screen.getByText('Agent Alpha')).toBeInTheDocument();
    expect(screen.getByText('Agent Beta')).toBeInTheDocument();
    expect(screen.queryByText('Agent Gamma')).not.toBeInTheDocument();
  });

  it('excludes unavailable agents even with non-null quota', () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData<AgentOption[]>(['agents'], [
      makeAgent({
        agent_type: 'agent1',
        name: 'Available Agent',
        available: true,
        quota: makeQuota({ balance_usd: 5.00 }),
      }),
      makeAgent({
        agent_type: 'agent2',
        name: 'Unavailable Agent',
        available: false,
        quota: makeQuota({ balance_usd: 5.00 }),
      }),
    ]);

    renderSidebar(queryClient);

    expect(screen.getByText('Available Agent')).toBeInTheDocument();
    expect(screen.queryByText('Unavailable Agent')).not.toBeInTheDocument();
  });

  it('has no manual refresh button in any state', () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData<AgentOption[]>(['agents'], [
      makeAgent({
        agent_type: 'agent1',
        name: 'Agent One',
        quota: makeQuota({ balance_usd: 5.00 }),
      }),
    ]);

    renderSidebar(queryClient);

    expect(screen.queryByRole('button', { name: /refresh/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/refresh/i)).not.toBeInTheDocument();
  });
});
