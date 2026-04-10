export interface StepSummarySchema {
  id: string;
  title: string;
  task_count: number;
}

export interface RoutineSummary {
  id: string;
  name: string;
  description: string | null;
  source: string;
  step_count: number;
  input_count: number;
  is_archived: boolean;
}

export interface RoutineDetail {
  id: string;
  name: string;
  description: string | null;
  source: string;
  inputs: Record<string, unknown>[];
  steps: StepSummarySchema[];
  is_archived: boolean;
}

export interface ArchiveRoutineResponse {
  id: string;
  source: string;
  is_archived: boolean;
}

export interface RoutineListResponse {
  routines: RoutineSummary[];
}
