/**
 * TypeScript types matching backend review API schemas.
 * See: src/orchestrator/api/schemas/review.py
 */

export interface DiffResponse {
  diff: string;
  scope: string;
  file_path: string | null;
}

export interface DiffFileEntry {
  path: string;
  status: "added" | "modified" | "deleted" | "renamed";
  additions: number;
  deletions: number;
}

export interface CommitEntry {
  sha: string;
  short_sha: string;
  message: string;
  author: string;
  timestamp: string;
}

export interface LineRange {
  start: number;
  end: number;
}

export interface FilePrune {
  path: string;
  mode: 'file' | 'hunk' | 'line';
  hunks: number[] | null;
  lines: LineRange[] | null;
}

export interface PruneSelection {
  files: FilePrune[];
  scope: string;
}

export interface PrunePreviewResponse {
  resulting_diff: string;
  files_affected: number;
  hunks_removed: number;
  lines_removed: number;
}

export interface PruneApplyResponse {
  commit_sha: string;
  files_affected: number;
  hunks_removed: number;
  lines_removed: number;
  event_id: string;
}

export interface TestRunResponse {
  test_run_id: string;
  status: string; // "running"
}

export interface TestSummary {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
}

export interface TestRunResult {
  test_run_id: string;
  status: 'running' | 'passed' | 'failed' | 'error';
  summary: TestSummary | null;
  log_output: string;
  duration_ms: number | null;
  started_at: string;
  completed_at: string | null;
}

export interface AgentJobResponse {
  job_id: string;
  status: string;
}

export interface ConflictBlock {
  index: number;
  ours_content: string;
  theirs_content: string;
  base_content: string | null;
}

export interface ConflictFile {
  path: string;
  status: 'unresolved' | 'resolved';
  block_count: number;
  blocks: ConflictBlock[];
}

export interface BlockResolution {
  block_index: number;
  choice: 'ours' | 'theirs' | 'manual';
  manual_content?: string | null;
}

export interface ConflictResolutionResponse {
  path: string;
  status: string;
  remaining_conflicts: number;
}

export interface BackMergeResponse {
  status: 'clean' | 'conflicts';
  merge_commit_sha: string | null;
  conflict_files: string[];
  conflict_count: number;
}

export interface RevertBackMergeResponse {
  reverted_commit: string;
  new_head: string;
}

export interface Gate {
  name: string;
  status: 'pass' | 'fail' | 'pending';
  description: string;
}

export interface MergeReadiness {
  ready: boolean;
  gates: Gate[];
}

export interface FinalMergeBackResponse {
  merge_commit: string;
  strategy: string;
  message: string;
}
