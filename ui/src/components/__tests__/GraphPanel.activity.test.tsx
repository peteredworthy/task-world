import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GraphPanel } from '../GraphPanel';
import { NodeDetailPanel } from '../NodeDetailPanel';
import { ActivityFeed } from '../detail/ActivityFeed';
import type {
  ActivityEvent,
  GraphEventResponse,
  NodeDetailResponse,
  GraphProjectionResponse,
  RunResponse,
} from '../../types';

afterEach(cleanup);

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
    steps: [
      {
        id: 'step-runtime-1',
        config_id: 'step-1',
        title: 'Step 1',
        completed: false,
        has_approval_gate: false,
        approval_status: null,
        skipped: false,
        skip_reason: null,
        condition: null,
        tasks: [
          {
            id: 'task-runtime-1',
            config_id: 'task-1',
            title: 'Emit output',
            status: 'building',
            current_attempt: 1,
            max_attempts: 3,
            grade_summary: [],
            attempts_summary: [],
            pending_action_type: null,
            pending_clarification_count: null,
            parent_task_id: null,
          },
        ],
      },
    ],
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

function makeActivityEvent(): ActivityEvent {
  return {
    id: 1,
    event_type: 'agent_output',
    timestamp: '2026-01-01T00:00:01Z',
    payload: {
      task_id: 'task-1',
      attempt_num: 1,
      lines: ['worker line one', 'worker line two'],
      line_offset: 0,
    },
    task_title: 'Emit output',
    step_title: 'Step 1',
  };
}

function renderGraphPanel(run: RunResponse, activityEvents: ActivityEvent[]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const projection: GraphProjectionResponse = {
    run_id: run.id,
    event_count: 2,
    run_state: 'active',
    node_states: { 'worker-1': 'running' },
    task_states: { 'step-1/task-1': 'in_progress' },
    leases: {
      'lease-1': {
        lease_id: 'lease-1',
        node_id: 'worker-1',
        state: 'active',
      },
    },
    ready_nodes: [],
  };
  const graphEvents: GraphEventResponse[] = [
    {
      event_id: 'event-1',
      event_type: 'node_created',
      run_id: run.id,
      position: 1,
      timestamp: '2026-01-01T00:00:00Z',
      payload: {
        node_id: 'worker-1',
        task_id: 'task-1',
        task_region_id: 'step-1/task-1',
      },
    },
  ];

  queryClient.setQueryData(['graphProjection', run.id], projection);
  queryClient.setQueryData(['graphEvents', run.id, undefined], graphEvents);
  queryClient.setQueryData(['graphNodeDetail', run.id, 'worker-1'], makeNodeDetail(run.id));

  return render(
    <QueryClientProvider client={queryClient}>
      <GraphPanel
        runId={run.id}
        run={run}
        open
        onClose={() => undefined}
        activityEvents={activityEvents}
      />
    </QueryClientProvider>,
  );
}

function makeNodeDetail(runId: string): NodeDetailResponse {
  return {
    run_id: runId,
    node_id: 'worker-1',
    kind: 'worker',
    role: 'builder',
    state: 'running',
    input_ports: {
      context: ['record-input-1'],
    },
    output_records: [
      {
        record_id: 'candidate-1',
        record_kind: 'output',
        producer_node_id: 'worker-1',
        port: 'candidate',
        value: { summary: 'implemented' },
      },
    ],
    file_state_records: [
      {
        record_id: 'fs-1',
        record_kind: 'file_state',
        verdict: 'captured',
        classification_summary: {
          total_paths: 1,
          classifications: { source: 1 },
        },
        patch_bundle_id: 'patch-1',
      },
    ],
    active_lease: {
      lease_id: 'lease-1',
      state: 'active',
    },
    callback_history: [
      {
        event_id: 'event-ack',
        event_type: 'node_state_changed',
        run_id: runId,
        position: 2,
        timestamp: '2026-01-01T00:00:02Z',
        payload: { node_id: 'worker-1', trigger: 'runtime_start_acknowledged' },
      },
      {
        event_id: 'event-callback',
        event_type: 'callback_accepted',
        run_id: runId,
        position: 3,
        timestamp: '2026-01-01T00:00:03Z',
        payload: { node_id: 'worker-1' },
      },
    ],
    events: [],
  };
}

describe('GraphPanel activity', () => {
  it('renders live node activity and activity feed agent output lines', () => {
    const run = makeRun();
    const outputEvent = makeActivityEvent();

    renderGraphPanel(run, [outputEvent]);

    expect(screen.getByText('live activity')).toBeInTheDocument();
    expect(screen.getByText('worker line two')).toBeInTheDocument();

    cleanup();

    render(
      <ActivityFeed
        events={[outputEvent]}
        activeTasks={[]}
        onSelectTask={() => undefined}
      />,
    );

    expect(screen.getByText(/worker line one/)).toBeInTheDocument();
    expect(screen.getByText(/worker line two/)).toBeInTheDocument();
  });

  it('renders node detail sections from fixture data', () => {
    const run = makeRun();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(['graphNodeDetail', run.id, 'worker-1'], makeNodeDetail(run.id));

    render(
      <QueryClientProvider client={queryClient}>
        <NodeDetailPanel runId={run.id} nodeId="worker-1" onClose={() => undefined} />
      </QueryClientProvider>,
    );

    expect(screen.getByText('Node detail')).toBeInTheDocument();
    expect(screen.getByText('Inputs')).toBeInTheDocument();
    expect(screen.getByText('record-input-1')).toBeInTheDocument();
    expect(screen.getByText('Outputs')).toBeInTheDocument();
    expect(screen.getByText('candidate-1')).toBeInTheDocument();
    expect(screen.getByText('File-state')).toBeInTheDocument();
    expect(screen.getByText(/patch-1/)).toBeInTheDocument();
    expect(screen.getByText('Callback history')).toBeInTheDocument();
    expect(screen.getByText('callback_accepted')).toBeInTheDocument();
  });

  it('opens node detail when a node row is clicked', () => {
    const run = makeRun();
    renderGraphPanel(run, []);

    fireEvent.click(screen.getByRole('button', { name: 'worker-1' }));

    expect(screen.getByTestId('node-detail-panel')).toBeInTheDocument();
    expect(screen.getByText('candidate-1')).toBeInTheDocument();
  });

  it('task card graph label opens the linked node facts', () => {
    const run = makeRun();
    const opened: string[] = [];
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ActivityFeed
          events={[makeActivityEvent()]}
          run={run}
          graphTaskStates={{ 'task-runtime-1': 'in_progress' }}
          graphTaskNodeIds={{ 'task-runtime-1': 'worker-1' }}
          onOpenGraphNode={(nodeId) => opened.push(nodeId)}
        />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'graph: in_progress' }));

    expect(opened).toEqual(['worker-1']);
  });
});
