import type { ChecklistStatus, Priority, TaskStatus } from './enums';

export interface ChecklistItemSchema {
  req_id: string;
  desc: string;
  priority: Priority;
  status: ChecklistStatus;
  note: string | null;
  grade: string | null;
  grade_reason: string | null;
}

export interface GradeSnapshotItem {
  req_id: string;
  grade: string | null;
  grade_reason: string | null;
}

export interface AttemptSchema {
  id: string;
  attempt_num: number;
  started_at: string | null;
  completed_at: string | null;
  builder_prompt: string | null;
  verifier_prompt: string | null;
  verifier_comment: string | null;
  outcome: string | null;
  metrics: Record<string, unknown>;
  grade_snapshot: GradeSnapshotItem[];
  auto_verify_results: Record<string, unknown>[] | null;
  agent_type: string | null;
  agent_model: string | null;
  agent_settings: Record<string, unknown>;
  error: string | null;
  has_output: boolean;
}

export interface TaskDetailResponse {
  id: string;
  config_id: string;
  title: string;
  status: TaskStatus;
  checklist: ChecklistItemSchema[];
  attempts: AttemptSchema[];
  current_attempt: number;
  max_attempts: number;
}

export interface TransitionResponse {
  success: boolean;
  new_status: string;
  error: string | null;
}

export interface UpdateChecklistRequest {
  status: string;
  note?: string;
}

export interface SetGradeRequest {
  grade: string;
  grade_reason?: string;
}

export interface CallbackInstructions {
  run_id: string;
  task_id: string;
  api_base_url: string;
  rest_instructions: string;
  mcp_instructions: string;
}

export interface PromptResponse {
  system: string;
  user: string;
  phase: string; // "building" or "verifying"
  callback: CallbackInstructions | null;
}

export interface AgentLogsResponse {
  run_id: string;
  task_id: string;
  attempt_num: number;
  output: string | null;
  error: string | null;
  line_count: number;
}
