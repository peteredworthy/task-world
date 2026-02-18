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

export interface ClarificationRequestedPayload {
  event_type: 'clarification_requested';
  run_id: string;
  task_id: string;
  request_id: string;
  question_count: number;
}

export interface ClarificationRespondedPayload {
  event_type: 'clarification_responded';
  run_id: string;
  task_id: string;
  request_id: string;
}
