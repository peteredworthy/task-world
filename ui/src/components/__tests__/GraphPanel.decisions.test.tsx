import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { GraphPanel } from '../GraphPanel';
import type { DecisionViewResponse, GraphProjectionResponse, RunResponse } from '../../types';

const originalFetch = globalThis.fetch;

afterEach(() => {
  cleanup();
  globalThis.fetch = originalFetch;
});

function makeRun(): RunResponse {
  return {
    id: 'run-1',
    repo_name: 'repo',
    status: 'active',
    pause_reason: null,
    last_error: null,
    is_graph_backed: true,
    routine_id: 'routine-1',
    routine_sha: null,
    routine_source: null,
    routine_embedded: null,
    routine_path: null,
    routine_commit: null,
    parent_run_id: null,
    parent_slice_id: null,
    oversight_state: {},
    agent_runner_type: null,
    agent_runner_type_display: 'None',
    agent_icon: 'bot',
    agent_runner_config: {},
    verifier_model: null,
    worktree_enabled: true,
    worktree_path: '/tmp/worktree',
    worktree_relative_path: null,
    source_branch: 'main',
    source_branch_sha: null,
    merge_strategy: null,
    config: {},
    env_file_specs: [],
    env_source_dir: null,
    steps: [],
    current_step_index: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    started_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    agent_runner_started_at: null,
    total_tokens_read: 0,
    total_tokens_write: 0,
    total_tokens_cache: 0,
    total_duration_ms: 0,
    total_num_actions: 0,
    token_usage_by_model: [],
    estimated_cost_usd: null,
    cost_disclaimer: null,
  };
}

function makeDecisionView(): DecisionViewResponse {
  return {
    run_id: 'run-1',
    event_count: 2,
    pending_gates: [
      {
        node_id: 'human-gate-1',
        gate_type: 'human_approval',
        prompt: 'Approve the verified candidate?',
        consequence_summary: 'Approval releases the waiting successor; rejection blocks it.',
      },
      {
        node_id: 'authority-1',
        gate_type: 'authority_request',
        prompt: 'Grant repository write access?',
        requested_authority: ['repo:docs/**:write'],
      },
    ],
    appeals: [],
    review: { ready: false, blockers: [] },
  };
}

function renderPanel(decisionView = makeDecisionView()) {
  const run = makeRun();
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnMount: false },
      mutations: { retry: false },
    },
  });
  const projection: GraphProjectionResponse = {
    run_id: run.id,
    event_count: 2,
    run_state: 'active',
    node_states: {},
    task_states: {},
    leases: {},
    ready_nodes: [],
  };
  queryClient.setQueryData(['graphProjection', run.id], projection);
  queryClient.setQueryData(['graphDecisions', run.id], decisionView);
  queryClient.setQueryData(['graphEvents', run.id, undefined], []);
  queryClient.setQueryData(['graphScheduler', run.id], {
    run_id: run.id,
    event_count: 2,
    scheduler: { ready: [], blocked: [], waiting_resources: [], waiting_gates: [] },
    leases: { active: [], suspended: [] },
  });
  queryClient.setQueryData(['graphFileState', run.id], {
    run_id: run.id,
    event_count: 2,
    gatekeeper: { gatekeeper_resolved: 0, unresolved_residue: 0 },
    nodes: [],
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <GraphPanel runId={run.id} run={run} open onClose={() => undefined} />
    </QueryClientProvider>,
  );
}

function graphApiResponse(input: RequestInfo | URL, init?: RequestInit): Response {
  const url = String(input);
  if (init?.method === 'POST') {
    return new Response(JSON.stringify({
      run_id: 'run-1',
      graph_position: 3,
      events: [],
      decision_view: { ...makeDecisionView(), pending_gates: [] },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }
  if (url.endsWith('/graph/decisions')) {
    return new Response(JSON.stringify({ ...makeDecisionView(), pending_gates: [] }), { status: 200 });
  }
  if (url.endsWith('/graph/scheduler')) {
    return new Response(JSON.stringify({
      run_id: 'run-1',
      event_count: 3,
      scheduler: { ready: [], blocked: [], waiting_resources: [], waiting_gates: [] },
      leases: { active: [], suspended: [] },
    }), { status: 200 });
  }
  if (url.endsWith('/graph/events')) return new Response(JSON.stringify([]), { status: 200 });
  if (url.endsWith('/graph')) {
    return new Response(JSON.stringify({
      run_id: 'run-1', event_count: 3, run_state: 'active', node_states: {}, task_states: {}, leases: {}, ready_nodes: [],
    }), { status: 200 });
  }
  return new Response(JSON.stringify(makeRun()), { status: 200 });
}

describe('GraphPanel human-gate decisions', () => {
  it('moves focus into the modal and restores it to the review trigger on close', () => {
    renderPanel();
    const trigger = screen.getByRole('button', { name: 'Review decision' });
    trigger.focus();

    fireEvent.click(trigger);

    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(trigger).toHaveFocus();
  });

  it('keeps keyboard focus trapped within the modal', () => {
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Review decision' }));
    const close = screen.getByRole('button', { name: 'Close' });
    const approve = screen.getByRole('button', { name: 'Approve' });

    approve.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(close).toHaveFocus();

    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(approve).toHaveFocus();
  });

  it('keeps approve and reject actions in a modal and excludes authority requests', () => {
    renderPanel();

    expect(screen.getAllByRole('button', { name: 'Review decision' })).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Review decision' }));

    const dialog = screen.getByRole('dialog', { name: 'Review graph decision' });
    expect(dialog).toHaveTextContent('Approve the verified candidate?');
    expect(dialog).toHaveTextContent('Approval releases the waiting successor; rejection blocks it.');
    expect(screen.getByLabelText('Note (optional)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument();
  });

  it('renders review decision only for human approval gates', () => {
    const decisionView = makeDecisionView();
    decisionView.pending_gates.push({
      node_id: 'automatic-policy-gate-1',
      gate_type: 'automatic_policy',
      prompt: 'Policy engine is evaluating this change.',
    });
    renderPanel(decisionView);

    expect(screen.getAllByRole('button', { name: 'Review decision' })).toHaveLength(1);
    expect(screen.getByText('automatic-policy-gate-1').closest('li')).not.toHaveTextContent('Review decision');
  });

  it('restores the pre-existing body overflow value after the modal closes', () => {
    document.body.style.overflow = 'clip';
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Review decision' }));
    expect(document.body.style.overflow).toBe('hidden');

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(document.body.style.overflow).toBe('clip');
  });

  it('submits an approval with the typed human actor and omits a blank reason', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = async (input, init) => {
      if (init?.method === 'POST') requests.push({ url: String(input), init });
      return graphApiResponse(input, init);
    };
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Review decision' }));
    fireEvent.change(screen.getByLabelText('Note (optional)'), { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].url).toContain('/api/runs/run-1/graph/decisions');
    expect(requests[0].init?.method).toBe('POST');
    expect(JSON.parse(String(requests[0].init?.body))).toEqual({
      decision_type: 'approval',
      node_id: 'human-gate-1',
      decision: 'approved',
      decider: { kind: 'human', id: 'human-operator', role: 'operator' },
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('submits a rejection with a trimmed reason', async () => {
    const requests: RequestInit[] = [];
    globalThis.fetch = async (input, init) => {
      if (init?.method === 'POST') requests.push(init);
      return graphApiResponse(input, init);
    };
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'Review decision' }));
    fireEvent.change(screen.getByLabelText('Note (optional)'), { target: { value: '  Unsafe output  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(JSON.parse(String(requests[0].body))).toEqual({
      decision_type: 'approval',
      node_id: 'human-gate-1',
      decision: 'rejected',
      decider: { kind: 'human', id: 'human-operator', role: 'operator' },
      reason: 'Unsafe output',
    });
  });
});
