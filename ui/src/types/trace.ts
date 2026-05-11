import type { TaskStatus } from './enums';
import type { ModelTokenUsage } from './runs';
import type { ActionLog } from './tasks';

export interface RunTracePhase {
  phase: 'builder' | 'verifier';
  prompt: string | null;
  note: string | null;
  message_count: number;
  action_sequence_start: number | null;
  action_sequence_end: number | null;
}

export interface RunTraceAttempt {
  step_id: string;
  step_config_id: string;
  step_title: string;
  step_index: number;
  task_id: string;
  task_config_id: string;
  task_title: string;
  task_status: TaskStatus;
  task_index: number;
  attempt_id: string;
  attempt_num: number;
  started_at: string | null;
  completed_at: string | null;
  outcome: string | null;
  metrics: Record<string, unknown>;
  token_usage_by_model: ModelTokenUsage[];
  agent_runner_type: string | null;
  agent_model: string | null;
  agent_settings: Record<string, unknown>;
  builder_prompt: string | null;
  verifier_prompt: string | null;
  verifier_comment: string | null;
  error: string | null;
  phases: RunTracePhase[];
  action_log: ActionLog | null;
}

export interface RunTraceResponse {
  run_id: string;
  attempts: RunTraceAttempt[];
}
