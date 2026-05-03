export interface RecoverRequest {
  target_task_id: string;
  additional_attempts?: number;
  agent_runner_type?: string;
  agent_runner_config?: Record<string, unknown>;
  preserve_checklist?: boolean;
  guidance?: string;
  reset_branch?: boolean;
}

export interface RecoverResponse {
  run_id: string;
  status: string;
  pause_reason: string | null;
  current_step_index: number | null;
}
