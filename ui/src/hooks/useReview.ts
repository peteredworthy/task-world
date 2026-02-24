import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getDiffFiles, getTaskDiffFiles, getCommits, getDiff, prunePreview, pruneApply, revertFile, runTests, getTestResult, agentFixTests, getConflicts, resolveConflict, agentResolveConflicts, revertBackMerge, triggerBackMerge, getMergeReadiness, finalMergeBack } from '../api/reviewClient';
import { api } from '../api/client';
import type { DiffFileEntry, CommitEntry, BranchStatusResponse } from '../types';
import type { PruneSelection, TestRunResult, BlockResolution, FinalMergeBackResponse, MergeReadiness } from '../types/review';

export function useDiffFiles(runId: string | undefined) {
  return useQuery({
    queryKey: ['diffFiles', runId],
    queryFn: () => getDiffFiles(runId!),
    enabled: !!runId,
    staleTime: 30_000,
  });
}

export function useTaskDiffFiles(runId: string | undefined, ref: string | undefined) {
  return useQuery({
    queryKey: ['taskDiffFiles', runId, ref],
    queryFn: () => getTaskDiffFiles(runId!, ref!),
    enabled: !!runId && !!ref,
    staleTime: 60_000,
  });
}

export function useCommits(runId: string | undefined) {
  return useQuery({
    queryKey: ['commits', runId],
    queryFn: () => getCommits(runId!),
    enabled: !!runId,
    staleTime: 30_000,
  });
}

export function useBranchStatus(runId: string | undefined) {
  return useQuery<BranchStatusResponse>({
    queryKey: ['branchStatus', runId],
    queryFn: () => api.getBranchStatus(runId!),
    enabled: !!runId,
    refetchInterval: 30_000,
  });
}

export function useDiff(runId: string | undefined, scope: string, ref?: string) {
  return useQuery({
    queryKey: ['diff', runId, scope, ref],
    queryFn: () => getDiff(runId!, scope, ref),
    enabled: !!runId,
    staleTime: 30_000,
  });
}

export function usePrunePreview(runId: string) {
  return useMutation({
    mutationFn: (selection: PruneSelection) => prunePreview(runId, selection),
  });
}

export function usePruneApply(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (selection: PruneSelection) => pruneApply(runId, selection),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['diffFiles', runId] });
      void queryClient.invalidateQueries({ queryKey: ['diff', runId] });
      void queryClient.invalidateQueries({ queryKey: ['commits', runId] });
      void queryClient.invalidateQueries({ queryKey: ['mergeReadiness', runId] });
    },
  });
}

export function useRevertFile(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (filePath: string) => revertFile(runId, filePath),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['diffFiles', runId] });
      void queryClient.invalidateQueries({ queryKey: ['diff', runId] });
    },
  });
}

export function useRunTests(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => runTests(runId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['testResult', runId] });
      void queryClient.invalidateQueries({ queryKey: ['mergeReadiness', runId] });
    },
  });
}

export function useTestResult(runId: string, testRunId: string | null) {
  const queryClient = useQueryClient();
  return useQuery<TestRunResult>({
    queryKey: ['testResult', runId, testRunId],
    queryFn: () => getTestResult(runId, testRunId!),
    enabled: !!testRunId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && data.status !== 'running') return false;
      return 2_000;
    },
    select: (data) => {
      // When a test run completes, invalidate merge readiness
      if (data.status !== 'running') {
        void queryClient.invalidateQueries({ queryKey: ['mergeReadiness', runId] });
      }
      return data;
    },
  });
}

export function useAgentFixTests(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentType, agentConfig }: { agentType?: string; agentConfig?: object } = {}) =>
      agentFixTests(runId, agentType, agentConfig),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['diffFiles', runId] });
      void queryClient.invalidateQueries({ queryKey: ['testResult', runId] });
      void queryClient.invalidateQueries({ queryKey: ['mergeReadiness', runId] });
    },
  });
}

export function useConflicts(runId: string | undefined) {
  return useQuery({
    queryKey: ['conflicts', runId],
    queryFn: () => getConflicts(runId!),
    enabled: !!runId,
    staleTime: 15_000,
  });
}

export function useResolveConflict(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ filePath, resolutions }: { filePath: string; resolutions: BlockResolution[] }) =>
      resolveConflict(runId, filePath, resolutions),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['conflicts', runId] });
      void queryClient.invalidateQueries({ queryKey: ['mergeReadiness', runId] });
    },
  });
}

export function useAgentResolveConflicts(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ agentType }: { agentType?: string } = {}) =>
      agentResolveConflicts(runId, agentType),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['conflicts', runId] });
      void queryClient.invalidateQueries({ queryKey: ['diffFiles', runId] });
      void queryClient.invalidateQueries({ queryKey: ['mergeReadiness', runId] });
    },
  });
}

export function useRevertBackMerge(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => revertBackMerge(runId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['branchStatus', runId] });
      void queryClient.invalidateQueries({ queryKey: ['conflicts', runId] });
      void queryClient.invalidateQueries({ queryKey: ['diffFiles', runId] });
      void queryClient.invalidateQueries({ queryKey: ['mergeReadiness', runId] });
    },
  });
}

export function useBackMerge(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => triggerBackMerge(runId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['branchStatus', runId] });
      void queryClient.invalidateQueries({ queryKey: ['conflicts', runId] });
      void queryClient.invalidateQueries({ queryKey: ['diffFiles', runId] });
      void queryClient.invalidateQueries({ queryKey: ['commits', runId] });
      void queryClient.invalidateQueries({ queryKey: ['mergeReadiness', runId] });
    },
  });
}

export function useMergeReadiness(runId: string | undefined) {
  return useQuery<MergeReadiness>({
    queryKey: ['mergeReadiness', runId],
    queryFn: () => getMergeReadiness(runId!),
    enabled: !!runId,
    refetchInterval: 30_000,
  });
}

export function useFinalMergeBack(runId: string) {
  const queryClient = useQueryClient();
  return useMutation<FinalMergeBackResponse, Error, 'squash' | 'merge'>({
    mutationFn: (strategy: 'squash' | 'merge') => finalMergeBack(runId, strategy),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['branchStatus', runId] });
      void queryClient.invalidateQueries({ queryKey: ['mergeReadiness', runId] });
    },
  });
}

export type { DiffFileEntry, CommitEntry, BranchStatusResponse };
