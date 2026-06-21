import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GraphPanel } from '../GraphPanel';
import type {
  ActivityEvent,
  DecisionViewResponse,
  FileStateReportResponse,
  GraphEventResponse,
  GraphProjectionResponse,
  NodeDetailResponse,
  RunResponse,
  SchedulerViewResponse,
} from '../../types';

afterEach(cleanup);

const RAW_SENTINEL = 'S3_RAW_SENTINEL_DO_NOT_RENDER';

function makeRun(): RunResponse {
  return {
    id: 's3-ui-run',
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
            title: 'Graph diagnostics',
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
    created_at: '2026-06-21T12:00:00Z',
    updated_at: '2026-06-21T12:00:00Z',
    started_at: '2026-06-21T12:00:00Z',
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

function makeProjection(runId: string): GraphProjectionResponse {
  return {
    run_id: runId,
    event_count: 24,
    run_state: 'active',
    node_states: {
      'worker-1': 'completed',
      'verifier-expired': 'failed',
      'review-final': 'blocked',
      'gate-human': 'blocked',
    },
    task_states: { 'step-1/task-1': 'in_progress' },
    leases: {
      'lease-expired': {
        lease_id: 'lease-expired',
        node_id: 'verifier-expired',
        state: 'expired',
      },
    },
    ready_nodes: [],
  };
}

function makeScheduler(runId: string): SchedulerViewResponse {
  return {
    run_id: runId,
    event_count: 24,
    scheduler: {
      ready: [],
      blocked: [
        { node_id: 'review-final', reason: 'missing_required_input:verification_evidence' },
      ],
      waiting_resources: [],
      waiting_gates: [{ node_id: 'gate-human', reason: 'gate_not_approved:gate-human' }],
    },
    leases: {
      active: [],
      suspended: [],
    },
  };
}

function makeDecision(runId: string): DecisionViewResponse {
  return {
    run_id: runId,
    event_count: 24,
    pending_gates: [
      {
        node_id: 'gate-human',
        gate_type: 'human_approval',
        prompt: 'Review diagnostics evidence',
      },
    ],
    appeals: [],
    review: {
      ready: false,
      blockers: ['review-final: final invariant missing verification_evidence'],
    },
  };
}

function makeFileState(runId: string): FileStateReportResponse {
  return {
    run_id: runId,
    event_count: 24,
    gatekeeper: null,
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
            classification_counts: { source: 1, test_artifact: 1 },
            captured_paths: [
              {
                path: 'src/orchestrator/api/routers/graph.py',
                classification: 'source',
                reason: null,
                source: 'tracked',
                matched_rule: 'tracked_source',
                needs_gatekeeper: false,
              },
            ],
            rejected_paths: [],
            gatekeeper_verdicts: [],
            diff_summary: { files_changed: 2, additions: 30, deletions: 4 },
          },
        ],
      },
    ],
  };
}

function makeGraphEvents(runId: string): GraphEventResponse[] {
  return [
    {
      event_id: 'evt-worker',
      event_type: 'node_created',
      run_id: runId,
      position: 2,
      timestamp: '2026-06-21T12:00:00Z',
      payload: { node_id: 'worker-1', task_id: 'task-runtime-1' },
    },
    {
      event_id: 'evt-expired',
      event_type: 'node_created',
      run_id: runId,
      position: 3,
      timestamp: '2026-06-21T12:00:00Z',
      payload: { node_id: 'verifier-expired' },
    },
  ];
}

function makeActivityEvents(): ActivityEvent[] {
  return [
    {
      id: 1,
      event_type: 'graph_patch_accepted',
      timestamp: '2026-06-21T12:01:00Z',
      payload: { patch_id: 'patch-health-summary', proposed_by_node_id: 'planner-1' },
      task_title: null,
      step_title: null,
    },
    {
      id: 2,
      event_type: 'graph_patch_rejected',
      timestamp: '2026-06-21T12:02:00Z',
      payload: { patch_id: 'patch-too-broad', reason: 'read_set_changed' },
      task_title: null,
      step_title: null,
    },
    {
      id: 3,
      event_type: 'verification_failed',
      timestamp: '2026-06-21T12:03:00Z',
      payload: {
        verifier_node_id: 'verifier-expired',
        candidate_id: 'candidate-1',
        evidence: RAW_SENTINEL,
        grades: [{ requirement_id: 'req-2', grade: 'C' }],
      },
      task_title: null,
      step_title: null,
    },
  ];
}

function makeNodeDetail(runId: string): NodeDetailResponse {
  return {
    run_id: runId,
    node_id: 'verifier-expired',
    kind: 'verifier',
    role: 'verifier',
    state: 'failed',
    input_ports: { candidate_under_test: ['candidate-1'] },
    output_records: [
      {
        record_id: 'verification-failed',
        record_kind: 'verification',
        verdict: 'failed',
        port: 'verification_report',
      },
    ],
    file_state_records: [
      {
        record_id: 'file-state-1',
        record_kind: 'file_state',
        classification_summary: {
          total_paths: 2,
          classifications: { source: 1, test_artifact: 1 },
        },
        patch_bundle_id: 'patch-1',
      },
    ],
    active_lease: {
      lease_id: 'lease-expired',
      state: 'expired',
    },
    callback_history: [
      {
        event_id: 'evt-lease-expired',
        event_type: 'lease_expired',
        run_id: runId,
        position: 20,
        timestamp: '2026-06-21T12:05:00Z',
        payload: { node_id: 'verifier-expired' },
      },
    ],
    events: [],
  };
}

function makeHealth(runId: string) {
  return {
    run_id: runId,
    event_count: 24,
    run_state: 'active',
    status: 'blocked',
    counts: {
      ready: 0,
      blocked: 2,
      waiting_resources: 0,
      waiting_gates: 1,
      active_leases: 0,
      suspended_leases: 0,
      expired_leases: 1,
      failed_nodes: 1,
      final_blockers: 1,
      patches_accepted: 1,
      patches_rejected: 1,
      verifier_passed: 1,
      verifier_failed: 1,
      pending_gates: 1,
    },
    failed_nodes: [{ node_id: 'verifier-expired', reason: 'lease_expired_without_callback' }],
    expired_leases: [
      {
        lease_id: 'lease-expired',
        node_id: 'verifier-expired',
        reason: 'lease_expired_without_callback',
      },
    ],
    blockers: [
      {
        node_id: 'review-final',
        kind: 'final_invariant',
        reason: 'missing_required_input:verification_evidence',
      },
    ],
    recent_patch_decisions: [
      { patch_id: 'patch-health-summary', decision: 'accepted' },
      { patch_id: 'patch-too-broad', decision: 'rejected', reason: 'read_set_changed' },
    ],
    verifier: {
      passed: 1,
      failed: 1,
      recent: [{ node_id: 'verifier-expired', candidate_id: 'candidate-1', verdict: 'failed' }],
    },
    pending_gates: [{ node_id: 'gate-human', gate_type: 'human_approval' }],
    review_blockers: ['review-final: final invariant missing verification_evidence'],
  };
}

function renderGraphPanel() {
  const run = makeRun();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  queryClient.setQueryData(['graphProjection', run.id], makeProjection(run.id));
  queryClient.setQueryData(['graphScheduler', run.id], makeScheduler(run.id));
  queryClient.setQueryData(['graphDecisions', run.id], makeDecision(run.id));
  queryClient.setQueryData(['graphFileState', run.id], makeFileState(run.id));
  queryClient.setQueryData(['graphEvents', run.id, undefined], makeGraphEvents(run.id));
  queryClient.setQueryData(['graphHealth', run.id], makeHealth(run.id));
  queryClient.setQueryData(['graphNodeDetail', run.id, 'verifier-expired'], makeNodeDetail(run.id));

  render(
    <QueryClientProvider client={queryClient}>
      <GraphPanel
        runId={run.id}
        run={run}
        open
        onClose={() => undefined}
        activityEvents={makeActivityEvents()}
      />
    </QueryClientProvider>,
  );
}

describe('S3 graph diagnostics hidden oracle', () => {
  it('renders compact graph health and opens causal node detail without raw payloads', () => {
    renderGraphPanel();

    expect(screen.getByText('Graph health')).toBeInTheDocument();
    expect(screen.getByText('Expired leases')).toBeInTheDocument();
    expect(screen.getByText('lease_expired_without_callback')).toBeInTheDocument();
    expect(screen.getByText('Final blockers')).toBeInTheDocument();
    expect(screen.getByText('missing_required_input:verification_evidence')).toBeInTheDocument();
    expect(screen.getByText('patch-health-summary')).toBeInTheDocument();
    expect(screen.getByText('patch-too-broad')).toBeInTheDocument();
    expect(screen.getByText('Verifier pass/fail')).toBeInTheDocument();
    expect(screen.getByText('1/1')).toBeInTheDocument();
    expect(screen.getByText('gate-human')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'verifier-expired' }));

    expect(screen.getByTestId('node-detail-panel')).toBeInTheDocument();
    expect(screen.getByText('candidate_under_test')).toBeInTheDocument();
    expect(screen.getByText('verification-failed')).toBeInTheDocument();
    expect(screen.getByText(/patch-1/)).toBeInTheDocument();
    expect(screen.getByText('lease_expired')).toBeInTheDocument();
    expect(screen.queryByText(RAW_SENTINEL)).not.toBeInTheDocument();
  });
});
