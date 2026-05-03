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
  note: string | null;
}

// --- Structured Action Log types ---

export type ActionEntryKind =
  | 'system_init'
  | 'assistant_text'
  | 'thinking'
  | 'tool_use'
  | 'tool_result'
  | 'result'
  | 'error';

export interface ToolUseDetail {
  tool_use_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  summary: string | null;
}

export interface ToolResultDetail {
  tool_use_id: string;
  output: string;
  exit_code: number | null;
  success: boolean;
  output_length: number;
}

export interface TurnMetrics {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  cost_usd: number;
}

export interface ActionLogEntry {
  sequence_num: number;
  kind: ActionEntryKind;
  timestamp: string | null;
  text: string | null;
  tool_use: ToolUseDetail | null;
  tool_result: ToolResultDetail | null;
  metrics: TurnMetrics | null;
  raw_type: string | null;
}

export interface ActionLog {
  entries: ActionLogEntry[];
  session_id: string | null;
  agent_model: string | null;
  tools_available: string[];
  total_turns: number;
  total_cost_usd: number;
  total_duration_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cache_read_tokens: number;
  total_cache_creation_tokens: number;
}

// --- Attempt and Task types ---

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
  agent_runner_type: string | null;
  agent_model: string | null;
  agent_settings: Record<string, unknown>;
  error: string | null;
  has_output: boolean;
  has_action_log: boolean;
  start_commit: string | null;
  end_commit: string | null;
}

export interface FanOutChildSummary {
  id: string | null;
  title: string;
  status: TaskStatus;
  current_attempt: number;
  fan_out_input: string | null;
  fan_out_output: string | null;
  is_synthetic: boolean;
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

  // Fan-out fields
  parent_task_id: string | null;
  fan_out_index: number | null;
  fan_out_input: string | null;
  fan_out_output: string | null;
  fan_out_children: FanOutChildSummary[];
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
  action_log: ActionLog | null;
}
