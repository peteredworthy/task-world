export interface BranchStatusResponse {
  behind_count: number;
  ahead_count: number;
  can_merge_cleanly: boolean;
  has_conflicts: boolean;
  source_branch: string;
  run_branch: string;
}
