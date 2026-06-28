import { afterEach, describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { RunEvidenceDigest } from '../RunEvidenceDigest';
import type { RunEvidenceDigestResponse } from '../../../types';

afterEach(() => {
  cleanup();
});

function renderDigest(runId: string, digest?: RunEvidenceDigestResponse) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  if (digest) {
    queryClient.setQueryData(['runEvidenceDigest', runId, undefined, false], digest);
  }

  return render(
    <QueryClientProvider client={queryClient}>
      <RunEvidenceDigest runId={runId} />
    </QueryClientProvider>,
  );
}

function makeDigest(overrides: Partial<RunEvidenceDigestResponse> = {}): RunEvidenceDigestResponse {
  return {
    run_id: 'run-1',
    status: 'paused',
    execution_mode: 'graph',
    is_graph_backed: true,
    generated_at: '2026-01-01T00:00:00Z',
    run_summary: {
      routine_id: 'routine-1',
      repo_name: 'repo-1',
      current_step_index: 0,
      step_count: 1,
      task_count: 2,
      task_status_counts: { pending_user_action: 1, completed: 1 },
      pause_reason: 'manual_gate',
      last_error: 'Graph paused for inspection',
    },
    blockers: [
      'pause_reason:manual_gate',
      'scheduler:waiting_resources:node-b:resource_conflict:write:write',
    ],
    scheduler: {
      graph_event_count: 7,
      ready_count: 0,
      blocked_count: 0,
      waiting_resource_count: 1,
      waiting_gate_count: 0,
      active_lease_count: 0,
      suspended_lease_count: 0,
    },
    representative_nodes: [
      {
        node_id: 'node-a',
        state: 'running',
        role: 'builder',
        title: 'Task Alpha worker',
        evidence_summary: null,
        blockers: [],
      },
      {
        node_id: 'node-b',
        state: 'planned',
        role: 'builder',
        title: 'Task Beta worker',
        evidence_summary: null,
        blockers: ['scheduler:waiting_resources:resource_conflict:write:write'],
      },
    ],
    metrics: {
      total_tokens_read: 11,
      total_tokens_write: 22,
      total_tokens_cache: 7,
      total_duration_ms: 777,
      total_num_actions: 5,
      estimated_cost_usd: 0.1234,
      token_usage_by_model_count: 1,
    },
    ...overrides,
  };
}

describe('RunEvidenceDigest', () => {
  it('renders the digest with hidden evidence and bounded nodes', () => {
    renderDigest('run-1', makeDigest());

    expect(screen.getByText('Run Evidence Digest')).toBeInTheDocument();
    expect(screen.getByText('paused')).toBeInTheDocument();
    expect(screen.getByText('Graph-backed')).toBeInTheDocument();
    expect(screen.getByText('Raw node evidence is hidden in this digest view.')).toBeInTheDocument();
    expect(screen.getByText('node-a')).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === 'Task Alpha worker · builder · running')).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === 'Task Beta worker · builder · planned')).toBeInTheDocument();
    expect(screen.getByText('1 blocker')).toBeInTheDocument();
    expect(screen.getByText('777ms')).toBeInTheDocument();
    expect(screen.getByText('$0.1234')).toBeInTheDocument();
  });

  it('renders a legacy empty digest without representative nodes', () => {
    renderDigest(
      'run-legacy',
      makeDigest({
        is_graph_backed: false,
        execution_mode: 'legacy',
        blockers: [],
        representative_nodes: [],
        scheduler: {
          graph_event_count: 0,
          ready_count: 0,
          blocked_count: 0,
          waiting_resource_count: 0,
          waiting_gate_count: 0,
          active_lease_count: 0,
          suspended_lease_count: 0,
        },
      }),
    );

    expect(screen.getByText('Legacy')).toBeInTheDocument();
    expect(screen.getByText('Legacy run has no graph evidence.')).toBeInTheDocument();
    expect(screen.getByText('No blockers reported.')).toBeInTheDocument();
  });

});
