export interface ClarificationQuestion {
  id: string;
  question: string;
  context: string;
  options: string[];
}

export interface ClarificationAnswer {
  question_id: string;
  selected_option: string | null;
  free_text: string | null;
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
}

export interface PendingAction {
  task_id: string;
  step_id: string;
  action_type: 'clarification' | 'approval';
  clarification_request: ClarificationRequest | null;
  summary_artifact: string | null;
  approval_prompt: string | null;
}

export interface ApproveTaskRequest {
  comment?: string;
}

export interface RejectTaskRequest {
  reason?: string;
}
