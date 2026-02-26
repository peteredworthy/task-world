/**
 * API client functions for the review endpoints.
 * Endpoints: /api/runs/{id}/review/diff, /diff/files, /commits, /prune, /revert-file
 */

import { fetchApi } from './client';
import type { AgentJobResponse, BackMergeResponse, CommitEntry, ConflictFile, BlockResolution, ConflictResolutionResponse, RevertBackMergeResponse, DiffFileEntry, DiffResponse, FinalMergeBackResponse, MergeReadiness, PruneSelection, PrunePreviewResponse, PruneApplyResponse, TestRunResponse, TestRunResult } from '../types/review';

export async function getDiffFiles(
  runId: string,
  scope: string = 'aggregate',
  ref?: string,
): Promise<DiffFileEntry[]> {
  const sp = new URLSearchParams({ scope });
  if (ref) sp.set('ref', ref);
  return fetchApi<DiffFileEntry[]>(`/api/runs/${runId}/review/diff/files?${sp.toString()}`);
}

export async function getTaskDiffFiles(runId: string, ref: string): Promise<DiffFileEntry[]> {
  const sp = new URLSearchParams({ scope: 'task', ref });
  return fetchApi<DiffFileEntry[]>(`/api/runs/${runId}/review/diff/files?${sp.toString()}`);
}

export async function getCommits(runId: string): Promise<CommitEntry[]> {
  return fetchApi<CommitEntry[]>(`/api/runs/${runId}/review/commits`);
}

export async function getDiff(
  runId: string,
  scope: string = 'aggregate',
  ref?: string,
): Promise<DiffResponse> {
  const sp = new URLSearchParams({ scope });
  if (ref) sp.set('ref', ref);
  return fetchApi<DiffResponse>(`/api/runs/${runId}/review/diff?${sp.toString()}`);
}

export async function prunePreview(runId: string, selection: PruneSelection): Promise<PrunePreviewResponse> {
  return fetchApi<PrunePreviewResponse>(`/api/runs/${runId}/review/prune/preview`, {
    method: 'POST',
    body: JSON.stringify(selection),
  });
}

export async function pruneApply(runId: string, selection: PruneSelection): Promise<PruneApplyResponse> {
  return fetchApi<PruneApplyResponse>(`/api/runs/${runId}/review/prune/apply`, {
    method: 'POST',
    body: JSON.stringify(selection),
  });
}

export async function revertFile(runId: string, filePath: string): Promise<{ commit_sha: string; file_path: string; reverted_to: string }> {
  return fetchApi<{ commit_sha: string; file_path: string; reverted_to: string }>(
    `/api/runs/${runId}/review/revert-file`,
    {
      method: 'POST',
      body: JSON.stringify({ file_path: filePath }),
    },
  );
}

export async function runTests(runId: string): Promise<TestRunResponse> {
  return fetchApi<TestRunResponse>(`/api/runs/${runId}/review/test`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export async function getTestResult(runId: string, testRunId: string): Promise<TestRunResult> {
  return fetchApi<TestRunResult>(`/api/runs/${runId}/review/test/${testRunId}`);
}

export async function agentFixTests(
  runId: string,
  agentType?: string,
  agentConfig?: object,
): Promise<AgentJobResponse> {
  return fetchApi<AgentJobResponse>(`/api/runs/${runId}/review/agent-fix-tests`, {
    method: 'POST',
    body: JSON.stringify({ agent_type: agentType, agent_config: agentConfig }),
  });
}

export async function getConflicts(runId: string): Promise<ConflictFile[]> {
  return fetchApi<ConflictFile[]>(`/api/runs/${runId}/review/conflicts`);
}

export async function resolveConflict(
  runId: string,
  filePath: string,
  resolutions: BlockResolution[],
): Promise<ConflictResolutionResponse> {
  return fetchApi<ConflictResolutionResponse>(
    `/api/runs/${runId}/review/conflicts/${filePath}/resolve`,
    {
      method: 'POST',
      body: JSON.stringify({ resolutions }),
    },
  );
}

export async function agentResolveConflicts(
  runId: string,
  agentType?: string,
): Promise<AgentJobResponse> {
  return fetchApi<AgentJobResponse>(`/api/runs/${runId}/review/conflicts/agent-resolve`, {
    method: 'POST',
    body: JSON.stringify({ agent_type: agentType }),
  });
}

export async function revertBackMerge(runId: string): Promise<RevertBackMergeResponse> {
  return fetchApi<RevertBackMergeResponse>(`/api/runs/${runId}/review/revert-back-merge`, {
    method: 'POST',
  });
}

export async function triggerBackMerge(runId: string): Promise<BackMergeResponse> {
  return fetchApi<BackMergeResponse>(`/api/runs/${runId}/back-merge`, {
    method: 'POST',
  });
}

export async function getMergeReadiness(runId: string): Promise<MergeReadiness> {
  return fetchApi<MergeReadiness>(`/api/runs/${runId}/review/merge-readiness`);
}

export async function finalMergeBack(
  runId: string,
  strategy: 'squash' | 'merge',
): Promise<FinalMergeBackResponse> {
  return fetchApi<FinalMergeBackResponse>(`/api/runs/${runId}/merge-back`, {
    method: 'POST',
    body: JSON.stringify({ strategy }),
  });
}
