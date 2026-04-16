export interface ClarificationQuestion {
  id: string;
  question: string;
  context: string;
  options: string[];
  question_type: 'single_select' | 'multi_select' | 'free_text' | 'number';
  allow_other: boolean;
  required: boolean;
  min?: number | null;
  max?: number | null;
  placeholder?: string | null;
}

export interface ClarificationAnswer {
  question_id: string;
  selected_option: string | null;
  free_text: string | null;
  selected_options?: string[];
  skipped?: boolean;
  skip_reason?: string | null;
}

export interface ClarificationRequest {
  id: string;
  run_id: string;
  task_id: string;
  attempt_num: number;
  questions: ClarificationQuestion[];
  created_at: string;
  responded_at: string | null;
}

export interface RespondToClarificationRequest {
  answers: ClarificationAnswer[];
  skipped?: boolean;
  skip_reason?: string | null;
}

export interface ClarificationResponse {
  request_id?: string;
  answers: ClarificationAnswer[];
  responded_at?: string;
  skipped?: boolean;
  skip_reason?: string | null;
}

export interface ClarificationHistoryItem {
  request: ClarificationRequest;
  response: ClarificationResponse | null;
}

export interface ClarificationHistoryResponse {
  items: ClarificationHistoryItem[];
}

export interface PendingAction {
  task_id: string;
  step_id: string;
  action_type: 'clarification' | 'approval';
  clarification_request: ClarificationRequest | null;
  summary_artifact: string | null;
  approval_prompt: string | null;
  is_gate_approval: boolean;
}

export interface ApproveTaskRequest {
  comment?: string;
}

export interface RejectTaskRequest {
  reason?: string;
}

export interface ForceAcceptTaskRequest {
  comment?: string;
}
