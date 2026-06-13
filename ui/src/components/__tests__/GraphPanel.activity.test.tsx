import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GraphPanel } from '../GraphPanel';
import { ActivityFeed } from '../detail/ActivityFeed';
import type {
  ActivityEvent,
  GraphEventResponse,
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
});
