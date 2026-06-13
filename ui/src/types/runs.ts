import type { AgentRunnerType, Priority, RunStatus, TaskStatus } from './enums';

export interface GradeSummaryItem {
  grade: string | null;
  priority: Priority;
}

export interface AttemptOutcome {
  attempt_num: number;
  outcome: string | null;
}

export interface TaskSummary {
  id: string;
  config_id: string;
  title: string;
  status: TaskStatus;
  current_attempt: number;
  max_attempts: number;
  grade_summary: GradeSummaryItem[];
  attempts_summary: AttemptOutcome[];
  pending_action_type: 'clarification' | 'approval' | null;
  pending_clarification_count: number | null;
  parent_task_id: string | null;
}

export interface StepSummary {
  id: string;
  config_id: string;
  title: string;
  completed: boolean;
  tasks: TaskSummary[];
  has_approval_gate: boolean;
  approval_status: 'pending' | 'approved' | 'rejected' | null;
  skipped: boolean;
  skip_reason: string | null;
  condition: { when: string | null; repeat_for: string | null } | null;
}

export interface ModelTokenUsage {
  model: string;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost_per_m_cache_read: number;
  cost_per_m_cache_creation: number;
  cost_per_m_input: number;
  cost_per_m_output: number;
  total_cost_usd: number;
}

export interface EnvFileSpec {
  path: string;
  promote_on_success: boolean;
}

export interface OversightEvidenceSummary {
  path: string;
  slice_id: string;
  routine_id: string;
  outcome: string;
  next_recommendation: string;
  target_bug_reproduced: string;
  summary: string;
}

export interface ChildOversightSummary {
  run_id: string;
  slice_id: string;
  status: RunStatus;
  routine_id: string | null;
  created_at: string;
  evidence: OversightEvidenceSummary[];
  invalid_evidence_paths: string[];
  blocking_reasons: string[];
}

export interface OversightAttentionItem {
  kind: 'child' | 'slice' | 'parent';
  run_id: string | null;
  slice_id: string | null;
  reason: string;
}

export interface OversightTerminalGuard {
  can_complete: boolean;
  blocking_reasons: string[];
  blocking_child_run_ids: string[];
}

export interface ParentOversightState {
  schema_version?: string;
  parent_run_id?: string;
  parent_status?: RunStatus;
  current_understanding?: unknown;
  target_inventory?: Record<string, unknown>[];
  decisions?: Record<string, unknown>[];
  accepted_child_run_ids?: string[];
  accepted_children?: Record<string, unknown>[];
  rejected_child_run_ids?: string[];
  abandoned_child_run_ids?: string[];
  merge_conflicts?: Record<string, unknown>[];
  max_child_runs?: number;
  child_count?: number;
  child_counts?: Record<string, number>;
  child_summaries?: ChildOversightSummary[];
  attempt_counts_by_slice?: Record<string, Record<string, number>>;
  active_child_run_ids?: string[];
  merge_queue?: string[];
  attention_items?: OversightAttentionItem[];
  stalled_slices?: Record<string, unknown>[];
  illegal_state_reasons?: string[];
  terminal_guard?: OversightTerminalGuard;
  next_parent_action?: string;
  slices?: Record<string, unknown>[];
}

export interface RunResponse {
  id: string;
  repo_name: string;
  status: RunStatus;
  pause_reason: string | null;
  last_error: string | null;
  is_graph_backed: boolean;
  routine_id: string | null;
  routine_sha: string | null;
  routine_source: string | null;
  routine_embedded: Record<string, unknown> | null;
  routine_path: string | null;
  routine_commit: string | null;
  parent_run_id: string | null;
  parent_slice_id: string | null;
  oversight_state: ParentOversightState;
  agent_runner_type: AgentRunnerType | null;
  agent_runner_type_display: string;
  agent_icon: string;
  agent_runner_config: Record<string, unknown>;
  verifier_model: string | null;
  worktree_enabled: boolean;
  worktree_path: string | null;
  worktree_relative_path: string | null;
  source_branch: string | null;
  source_branch_sha: string | null;
  merge_strategy: string | null;
  config: Record<string, unknown>;
  env_file_specs: EnvFileSpec[];
  env_source_dir: string | null;
  steps: StepSummary[];
  current_step_index: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  agent_runner_started_at: string | null;
  total_tokens_read: number;
  total_tokens_write: number;
  total_tokens_cache: number;
  total_duration_ms: number;
  total_num_actions: number;
  token_usage_by_model: ModelTokenUsage[];
  estimated_cost_usd: number | null;
  cost_disclaimer: string | null;
}

export interface GraphEventResponse {
  event_id: string;
  event_type: string;
  run_id: string;
  position: number;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface GraphProjectionResponse {
  run_id: string;
  event_count: number;
  run_state: string | null;
  node_states: Record<string, string>;
  task_states: Record<string, string>;
  leases: Record<string, Record<string, unknown>>;
  ready_nodes: string[];
}

export interface SchedulerBlockedNode {
  node_id: string;
  reason: string;
}

export interface SchedulerLease {
  lease_id: string;
  node_id: string;
  generation: number | null;
  state: string;
  execution_id: string | null;
  expires_at: string | null;
}

export interface SchedulerViewResponse {
  run_id: string;
  event_count: number;
  scheduler: {
    ready: string[];
    blocked: SchedulerBlockedNode[];
    waiting_resources: SchedulerBlockedNode[];
    waiting_gates: SchedulerBlockedNode[];
  };
  leases: {
    active: SchedulerLease[];
    suspended: SchedulerLease[];
  };
}

export interface PendingGateDecision {
  node_id: string;
  gate_type: string;
  prompt: string | null;
}

export interface AppealDecision {
  node_id: string;
  state: string;
  outcome: string | null;
}

export interface DecisionViewResponse {
  run_id: string;
  event_count: number;
  pending_gates: PendingGateDecision[];
  appeals: AppealDecision[];
  review: {
    ready: boolean;
    blockers: string[];
  };
}

export interface NodeDetailResponse {
  run_id: string;
  node_id: string;
  kind: string | null;
  role: string | null;
  state: string | null;
  input_ports: Record<string, string[]>;
  output_records: Record<string, unknown>[];
  file_state_records: Record<string, unknown>[];
  active_lease: Record<string, unknown> | null;
  callback_history: GraphEventResponse[];
  events: GraphEventResponse[];
  prompt_summary?: Record<string, unknown> | null;
}

export interface FileStatePath {
  path: string;
  classification: string | null;
  reason: string | null;
  source: string | null;
  matched_rule: string | null;
  needs_gatekeeper: boolean;
}

export interface FileStateGatekeeperVerdict {
  path: string;
  verdict: string;
  classification: string | null;
  rationale: string | null;
  confidence: number | null;
  model_id: string | null;
}

export interface FileStateDiffSummary {
  files_changed: number;
  additions: number | null;
  deletions: number | null;
}

export interface FileStateBoundary {
  record_id: string;
  node_id: string | null;
  snapshot_id: string;
  snapshot_type: string;
  verdict: string | null;
  classification_counts: Record<string, number>;
  captured_paths: FileStatePath[];
  rejected_paths: FileStatePath[];
  gatekeeper_verdicts: FileStateGatekeeperVerdict[];
  diff_summary: FileStateDiffSummary | null;
}

export interface FileStateNodeReport {
  node_id: string;
  boundaries: FileStateBoundary[];
}

export interface FileStateReportResponse {
  run_id: string;
  event_count: number;
  nodes: FileStateNodeReport[];
  gatekeeper: Record<string, unknown> | null;
}

export interface RunListResponse {
  runs: RunResponse[];
}

export interface CreateRunRequest {
  routine_id?: string;
  repo_name: string;
  branch: string;
  routine_embedded?: Record<string, unknown>;
  config?: Record<string, unknown>;
  agent_runner_type?: string;
  agent_runner_config?: Record<string, unknown>;
  execution_mode?: 'legacy' | 'graph';
}
