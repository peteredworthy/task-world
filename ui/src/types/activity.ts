export interface ActivityEvent {
  id: number;
  event_type: string;
  timestamp: string;
  payload: Record<string, unknown>;
  task_title: string | null;
  step_title: string | null;
}

export interface ActivityResponse {
  run_id: string;
  events: ActivityEvent[];
  has_more: boolean;
}
