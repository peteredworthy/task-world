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
}

export interface StepSummary {
  id: string;
  config_id: string;
  title: string;
  completed: boolean;
  tasks: TaskSummary[];
  has_approval_gate: boolean;
  approval_status: 'pending' | 'approved' | 'rejected' | null;
}

export interface EnvFileSpec {
  path: string;
  promote_on_success: boolean;
}

export interface RunResponse {
  id: string;
  repo_name: string;
  status: RunStatus;
  pause_reason: string | null;
  last_error: string | null;
  routine_id: string | null;
  routine_sha: string | null;
  routine_source: string | null;
  routine_embedded: Record<string, unknown> | null;
  agent_type: AgentRunnerType | null;
  agent_type_display: string;
  agent_icon: string;
  agent_config: Record<string, unknown>;
  worktree_enabled: boolean;
  worktree_path: string | null;
  source_branch: string | null;
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
  agent_started_at: string | null;
  total_tokens_read: number;
  total_tokens_write: number;
  total_tokens_cache: number;
  total_duration_ms: number;
  estimated_cost_usd: number | null;
  cost_disclaimer: string | null;
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
  agent_type?: string;
  agent_config?: Record<string, unknown>;
}
