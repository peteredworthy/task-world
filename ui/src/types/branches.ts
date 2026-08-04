export interface MergeReadinessSnapshot {
  status: string; // "ready" | "conflicts" | "behind"
  blocking_reasons: string[];
}

export type MergeDispositionStatus =
  | 'merged'
  | 'ready'
  | 'no_changes'
  | 'dirty'
  | 'unfinalized'
  | 'blocked';

export interface MergeDispositionSnapshot {
  status: MergeDispositionStatus;
  reason: string;
  merge_commit: string | null;
}

export interface BranchStatusResponse {
  behind_count: number;
  ahead_count: number;
  can_merge_cleanly: boolean;
  has_conflicts: boolean;
  source_branch: string;
  run_branch: string;
  predicted_conflict_count: number;
  merge_readiness: MergeReadinessSnapshot;
  merge_disposition: MergeDispositionSnapshot;
}
