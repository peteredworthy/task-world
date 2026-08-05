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
  gen_ai_usage_cache_read_input_tokens: number;
  gen_ai_usage_cache_creation_input_tokens: number;
  gen_ai_usage_input_tokens: number;
  gen_ai_usage_output_tokens: number;
  gen_ai_usage_reasoning_output_tokens: number;
  gen_ai_response_finish_reasons: string[];
  cost_usd: number;
  latency_ms: number;
  rate_missing: boolean;
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
  intended_seed_sha: string | null;
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

export interface RunEvidenceDigestRunSummary {
  routine_id: string | null;
  repo_name: string;
  current_step_index: number;
  step_count: number;
  task_count: number;
  task_status_counts: Record<string, number>;
  pause_reason: string | null;
  last_error: string | null;
}

export interface RunEvidenceDigestScheduler {
  graph_event_count: number;
  ready_count: number;
  blocked_count: number;
  waiting_resource_count: number;
  waiting_gate_count: number;
  active_lease_count: number;
  suspended_lease_count: number;
}

export interface RepresentativeNodeEvidence {
  node_id: string;
  state: string | null;
  role: string | null;
  title: string | null;
  evidence_summary: string | null;
  evidence_status?: 'complete' | 'partial' | 'unavailable' | 'not_requested';
  blockers: string[];
}

export interface RunEvidenceDigestMetrics {
  total_tokens_read: number;
  total_tokens_write: number;
  total_tokens_cache: number;
  total_duration_ms: number;
  total_num_actions: number;
  estimated_cost_usd: number | null;
  token_usage_by_model_count: number;
}

export interface RunEvidenceDigestResponse {
  run_id: string;
  status: RunStatus;
  execution_mode: 'legacy' | 'graph' | string;
  is_graph_backed: boolean;
  graph_facts_status?: 'complete' | 'partial' | 'unavailable';
  generated_at: string;
  run_summary: RunEvidenceDigestRunSummary;
  blockers: string[];
  scheduler: RunEvidenceDigestScheduler;
  representative_nodes: RepresentativeNodeEvidence[];
  metrics: RunEvidenceDigestMetrics;
}

export interface GraphEventResponse {
  event_id: string;
  event_type: string;
  run_id: string;
  position: number;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface GraphEventsPage {
  events: GraphEventResponse[];
  has_more: boolean;
  next_position: number | null;
}

export interface GraphPatchAttemptResponse {
  patch_id: string;
  patch_id_truncated: boolean;
  patch_id_original_chars: number | null;
  patch_id_sha256: string | null;
  proposed_by_node_id: string | null;
  proposed_by_node_id_truncated: boolean;
  proposed_by_node_id_original_chars: number | null;
  proposed_by_node_id_sha256: string | null;
  base_graph_position: number | null;
  current_graph_position: number;
  status: 'proposed' | 'accepted' | 'rejected' | 'superseded';
  rejection_reason: string | null;
  diagnostics: Record<string, unknown> | null;
  read_set_diff: Record<string, unknown> | null;
  accepted_event_id: string | null;
  accepted_position: number | null;
  rejected_event_id: string | null;
  rejected_position: number | null;
  created_node_ids: string[];
  created_node_ids_total: number;
  created_node_ids_truncated: boolean;
  created_node_id_truncations: GraphPatchIdentifierTruncation[];
  created_edge_ids: string[];
  created_edge_ids_total: number;
  created_edge_ids_truncated: boolean;
  created_edge_id_truncations: GraphPatchIdentifierTruncation[];
  operations: Record<string, unknown>[];
  operations_total: number;
  operations_truncated: boolean;
  requirements: unknown[];
  requirements_total: number;
  requirements_truncated: boolean;
  reasons: string[];
  reasons_total: number;
  reasons_truncated: boolean;
  evidence: unknown[];
  evidence_total: number;
  evidence_truncated: boolean;
  text_truncated: boolean;
  max_text_chars: number;
  payload_truncated: boolean;
  payload_truncation_reasons: string[];
  nested_identifier_truncations: GraphPatchNestedIdentifierTruncation[];
  nested_identifier_truncations_truncated: boolean;
}

export interface GraphPatchIdentifierTruncation {
  index: number;
  original_chars: number;
  sha256: string;
}

export interface GraphPatchNestedIdentifierTruncation {
  path: string;
  original_chars: number;
  sha256: string;
}

export interface GraphPatchAttemptsPage {
  run_id: string;
  current_graph_position: number;
  attempts: GraphPatchAttemptResponse[];
  has_more: boolean;
  next_position: number | null;
  limit: number;
  orphan_outcome_count: number;
  capped_fact_count: number;
  partial: boolean;
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

export interface GraphReadPageMetadata {
  owner?: string | null;
  truncated: boolean;
  total_known: number;
  next_cursor: string | number | null;
  original_bytes?: number | null;
  sha256?: string | null;
  fields: Record<string, GraphReadPageMetadata>;
}

export interface GraphTopologyResponse {
  run_id: string;
  event_count: number;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  truncated: boolean;
  total_known: number;
  next_cursor: number | null;
  partial: boolean;
  collection_meta: Record<string, GraphReadPageMetadata>;
}

export interface FinalInvariantBlockersResponse {
  run_id: string;
  event_count: number;
  blockers: Array<Record<string, unknown>>;
  truncated: boolean;
  total_known: number;
  next_cursor: string | number | null;
  partial: boolean;
  collection_meta: Record<string, GraphReadPageMetadata>;
}

export interface GraphRegionsResponse {
  run_id: string;
  event_count: number;
  regions: Array<Record<string, unknown>>;
  truncated: boolean;
  total_known: number;
  next_cursor: number | null;
  partial: boolean;
  collection_meta: Record<string, GraphReadPageMetadata>;
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

export interface GraphHealthResponse {
  run_id: string;
  event_count: number;
  run_state: string | null;
  status: string;
  health_status: 'partial' | 'complete' | 'unavailable';
  facts_status: 'partial' | 'complete' | 'unavailable';
  unavailable_checks: string[];
  section_status: Record<string, 'partial' | 'complete' | 'unavailable'>;
  counts: Record<string, number | null>;
  failed_nodes: Array<{ node_id: string; reason: string }>;
  expired_leases: Array<{ lease_id: string; node_id: string; reason: string }>;
  blockers: Array<{ node_id: string; kind: string; reason: string }>;
  recent_patch_decisions: Array<{ patch_id: string; decision: string; reason?: string | null }>;
  verifier: { passed: number | null; failed: number | null; recent: Array<{ node_id: string; candidate_id: string; verdict: string }> };
  pending_gates: Array<{ node_id: string; gate_type: string }>;
  review_blockers: string[];
  detail_meta: Record<string, { total: number; truncated: boolean }>;
}

export interface PendingGateDecision {
  node_id: string;
  gate_type: string;
  prompt: string | null;
  options?: string[];
  default_option?: string;
  consequence_summary?: string;
  expires_at?: string;
  requested_authority?: string[];
  target_node_id?: string;
  target_region_id?: string;
}

export type GraphApprovalDecision = 'approved' | 'rejected';

export interface RecordGraphDecisionRequest {
  decision_type: 'approval';
  node_id: string;
  decision: GraphApprovalDecision;
  decider: {
    kind: 'human';
    id: string;
    role: 'operator';
  };
  reason?: string;
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

export interface RecordGraphDecisionResponse {
  run_id: string;
  graph_position: number;
  events: GraphEventResponse[];
  decision_view: DecisionViewResponse;
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
  captured_source_entries_total: number;
  captured_paths_truncated: boolean;
  rejected_paths: FileStatePath[];
  rejected_source_entries_total: number;
  rejected_paths_truncated: boolean;
  gatekeeper_verdicts: FileStateGatekeeperVerdict[];
  gatekeeper_verdicts_total: number | null;
  gatekeeper_verdicts_truncated: boolean;
  gatekeeper_facts_total: number;
  gatekeeper_facts_truncated: boolean;
  diff_summary: FileStateDiffSummary | null;
  diff_summary_available: boolean;
}

export interface FileStateNodeReport {
  node_id: string;
  boundaries: FileStateBoundary[];
}

export interface FileStateReportResponse {
  run_id: string;
  event_count: number;
  from_position: number;
  has_more: boolean;
  next_position: number | null;
  path_limit: number;
  nodes: FileStateNodeReport[];
  gatekeeper_scope: 'page';
  gatekeeper_metrics_truncated: boolean;
  orphan_gatekeeper_fact_count: number;
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
