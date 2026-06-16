import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GraphPanel } from '../GraphPanel';
import { NodeDetailPanel } from '../NodeDetailPanel';
import { ActivityFeed } from '../detail/ActivityFeed';
import type {
  ActivityEvent,
  DecisionViewResponse,
  FileStateReportResponse,
  GraphEventResponse,
  NodeDetailResponse,
  GraphProjectionResponse,
  RunResponse,
  SchedulerViewResponse,
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

function makeGraphActivityEvents(): ActivityEvent[] {
  return [
    {
      id: 2,
      event_type: 'graph_patch_accepted',
      timestamp: '2026-01-01T00:00:02Z',
      payload: {
        decision: 'accepted',
        patch_id: 'patch-accepted',
        proposed_by_node_id: 'planner-1',
        actor_role: 'planner',
        successor_planner_node_ids: ['planner-2'],
      },
      task_title: null,
      step_title: null,
    },
    {
      id: 3,
      event_type: 'graph_patch_rejected',
      timestamp: '2026-01-01T00:00:03Z',
      payload: {
        decision: 'rejected',
        patch_id: 'patch-rejected',
        proposed_by_node_id: 'planner-1',
        actor_role: 'planner',
        reason: 'read_set_changed',
      },
      task_title: null,
      step_title: null,
    },
    {
      id: 4,
      event_type: 'verification_failed',
      timestamp: '2026-01-01T00:00:04Z',
      payload: {
        verdict: 'failed',
        candidate_id: 'candidate-1',
        task_region_id: 'step-1/task-1',
        evidence: 'raw verifier evidence must not render',
        grades: [
          { requirement_id: 'R-01', grade: 'A' },
          { requirement_id: 'R-02', grade: 'C', reason: 'missing coverage' },
        ],
      },
      task_title: null,
      step_title: null,
    },
    {
      id: 5,
      event_type: 'command_rejected',
      timestamp: '2026-01-01T00:00:05Z',
      payload: {
        command_type: 'submit_patch',
        reason: 'malformed patch: missing patch_id',
      },
      task_title: null,
      step_title: null,
    },
    {
      id: 6,
      event_type: 'node_created',
      timestamp: '2026-01-01T00:00:06Z',
      payload: {
        summary: 'Graph final invariant blocked: node=review-final; reason=unresolved gap evidence',
        node_id: 'review-final',
        kind: 'review',
        reason: 'unresolved gap evidence',
      },
      task_title: null,
      step_title: null,
    },
    {
      id: 7,
      event_type: 'node_created',
      timestamp: '2026-01-01T00:00:07Z',
      payload: {
        node_id: 'worker-raw',
        kind: 'worker',
        prompt: 'raw prompt transcript must not render',
      },
      task_title: null,
      step_title: null,
    },
  ];
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
  const schedulerView: SchedulerViewResponse = {
    run_id: run.id,
    event_count: 2,
    scheduler: {
      ready: ['planner-ready'],
      blocked: [{ node_id: 'verifier-blocked', reason: 'missing_required_input:candidate' }],
      waiting_resources: [{ node_id: 'worker-resource', reason: 'resource_conflict:write:write' }],
      waiting_gates: [{ node_id: 'gate-wait', reason: 'gate_not_approved:gate-1' }],
    },
    leases: {
      active: [
        {
          lease_id: 'lease-1',
          node_id: 'worker-1',
          generation: 1,
          state: 'active',
          execution_id: 'exec-1',
          expires_at: '2026-01-01T00:10:00Z',
        },
      ],
      suspended: [
        {
          lease_id: 'lease-suspended',
          node_id: 'worker-paused',
          generation: 2,
          state: 'suspended',
          execution_id: 'exec-suspended',
          expires_at: '2026-01-01T00:15:00Z',
        },
      ],
    },
  };
  const decisionView: DecisionViewResponse = {
    run_id: run.id,
    event_count: 5,
    pending_gates: [
      {
        node_id: 'gate-planner-budget-planner-1',
        gate_type: 'planner_generation_budget_exhausted',
        prompt: 'planner_generation_budget_exhausted',
      },
    ],
    appeals: [
      {
        node_id: 'appeal-1',
        state: 'completed',
        outcome: 'invalid_test_accepted',
      },
    ],
    review: {
      ready: false,
      blockers: ['review-1: merge_conflicts'],
    },
  };

  queryClient.setQueryData(['graphProjection', run.id], projection);
  queryClient.setQueryData(['graphScheduler', run.id], schedulerView);
  queryClient.setQueryData(['graphDecisions', run.id], decisionView);
  queryClient.setQueryData(['graphFileState', run.id], makeFileStateReport(run.id));
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

function makeFileStateReport(runId: string): FileStateReportResponse {
  return {
    run_id: runId,
    event_count: 4,
    gatekeeper: {
      gatekeeper_resolved: 1,
      unresolved_residue: 0,
    },
    nodes: [
      {
        node_id: 'worker-1',
        boundaries: [
          {
            record_id: 'file-state-1',
            node_id: 'worker-1',
            snapshot_id: 'snapshot-1',
            snapshot_type: 'git_commit',
            verdict: 'captured',
            classification_counts: {
              source: 1,
              test_artifact: 1,
              tool_cache: 1,
            },
            captured_paths: [
              {
                path: 'src/app.py',
                classification: 'source',
                reason: null,
                source: 'tracked',
                matched_rule: 'tracked_source',
                needs_gatekeeper: false,
              },
              {
                path: 'reports/result.xml',
                classification: 'test_artifact',
                reason: null,
                source: 'untracked',
                matched_rule: 'gatekeeper:fake-small-model',
                needs_gatekeeper: false,
              },
            ],
            rejected_paths: [
              {
                path: 'tmp/cache.bin',
                classification: 'tool_cache',
                reason: 'ignored cache outside manifest',
                source: 'ignored',
                matched_rule: null,
                needs_gatekeeper: false,
              },
            ],
            gatekeeper_verdicts: [
              {
                path: 'reports/result.xml',
                verdict: 'allow',
                classification: 'test_artifact',
                rationale: 'metadata shape matches test output',
                confidence: 0.92,
                model_id: 'fake-small-model',
              },
            ],
            diff_summary: {
              files_changed: 2,
              additions: 7,
              deletions: 1,
            },
          },
        ],
      },
    ],
  };
}

describe('GraphPanel activity', () => {
  it('renders graph operator summary and compact DG activity rows', () => {
    const run = makeRun();
    renderGraphPanel(run, [makeActivityEvent(), ...makeGraphActivityEvents()]);

    expect(screen.getByText('Operator summary')).toBeInTheDocument();
    expect(screen.getByText('Graph state')).toBeInTheDocument();
    expect(screen.getByText('Active leases')).toBeInTheDocument();
    expect(screen.getByText('Suspended leases')).toBeInTheDocument();
    expect(screen.getByText('Patches accepted')).toBeInTheDocument();
    expect(screen.getByText('Patches rejected')).toBeInTheDocument();
    expect(screen.getByText('Verifier pass/fail')).toBeInTheDocument();
    expect(screen.getByText('Activity blockers')).toBeInTheDocument();
    expect(screen.getByText('0/1')).toBeInTheDocument();

    expect(screen.getByText('Patch decisions')).toBeInTheDocument();
    expect(screen.getByText('patch-accepted')).toBeInTheDocument();
    expect(screen.getByText('patch-rejected')).toBeInTheDocument();
    expect(screen.getByText('successors: planner-2')).toBeInTheDocument();
    expect(screen.getByText('reason: read_set_changed')).toBeInTheDocument();

    expect(screen.getByText('Verifier results')).toBeInTheDocument();
    expect(screen.getByText('candidate-1')).toBeInTheDocument();
    expect(screen.getByText('requirements: R-02=C')).toBeInTheDocument();

    expect(screen.getByText('Commands and blockers')).toBeInTheDocument();
    expect(screen.getByText('submit_patch')).toBeInTheDocument();
    expect(screen.getByText('malformed patch: missing patch_id')).toBeInTheDocument();
    expect(screen.getByText('review-final')).toBeInTheDocument();
    expect(screen.getByText('unresolved gap evidence')).toBeInTheDocument();

    expect(screen.queryByText('raw verifier evidence must not render')).not.toBeInTheDocument();
    expect(screen.queryByText('raw prompt transcript must not render')).not.toBeInTheDocument();
    expect(screen.queryByText('worker-raw')).not.toBeInTheDocument();
  });

  it('renders live node activity and activity feed agent output lines', () => {
    const run = makeRun();
    const outputEvent = makeActivityEvent();

    renderGraphPanel(run, [outputEvent]);

    expect(screen.getByText('live activity')).toBeInTheDocument();
    expect(screen.getByText('worker line two')).toBeInTheDocument();
    expect(screen.getByText('Decisions')).toBeInTheDocument();
    expect(screen.getByText('gate-planner-budget-planner-1')).toBeInTheDocument();
    expect(screen.getAllByText('planner_generation_budget_exhausted')).toHaveLength(2);
    expect(screen.getByText('appeal-1')).toBeInTheDocument();
    expect(screen.getByText('invalid_test_accepted')).toBeInTheDocument();
    expect(screen.getByText('Review readiness')).toBeInTheDocument();
    expect(screen.getByText('review-1: merge_conflicts')).toBeInTheDocument();
    expect(screen.getByTestId('file-state-viewer')).toBeInTheDocument();
    expect(screen.getByText('snapshot-1')).toBeInTheDocument();
    expect(screen.getByText('test_artifact: 1')).toBeInTheDocument();
    expect(screen.getByText('tmp/cache.bin')).toBeInTheDocument();
    expect(screen.getByText('ignored cache outside manifest')).toBeInTheDocument();
    expect(screen.getByText('allow / test_artifact')).toBeInTheDocument();
    expect(screen.getByText('metadata shape matches test output')).toBeInTheDocument();
    expect(screen.getByText('diff summary: 2 files changed / +7 -1')).toBeInTheDocument();

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
