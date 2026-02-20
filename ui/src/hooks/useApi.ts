import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, getConfig, validateRoutine } from '../api/client';
import type { CreateRunRequest, RecoverRequest, SetGradeRequest, UpdateChecklistRequest } from '../types';

export function useRuns(params?: { status?: string; repo_name?: string; limit?: number }) {
  return useQuery({
    queryKey: ['runs', params],
    queryFn: () => api.listRuns(params),
    refetchInterval: 10000,
  });
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return (status === 'completed' || status === 'failed') ? false : 10000;
    },
  });
}

export function useBranchStatus(runId: string | undefined) {
  return useQuery({
    queryKey: ['branchStatus', runId],
    queryFn: () => api.getBranchStatus(runId!),
    enabled: !!runId,
    refetchInterval: 30_000,
  });
}

export function useGuidance(runId: string | undefined) {
  return useQuery({
    queryKey: ['guidance', runId],
    queryFn: () => api.getGuidance(runId!),
    enabled: !!runId,
  });
}

export function useEnvFiles(runId: string | undefined) {
  return useQuery({
    queryKey: ['envFiles', runId],
    queryFn: () => api.getEnvFiles(runId!),
    enabled: !!runId,
  });
}

export function useEnvSnapshots(runId: string | undefined) {
  return useQuery({
    queryKey: ['envSnapshots', runId],
    queryFn: () => api.getEnvSnapshots(runId!),
    enabled: !!runId,
  });
}

export function useEnvDefaultTarget(runId: string | undefined) {
  return useQuery({
    queryKey: ['envDefaultTarget', runId],
    queryFn: () => api.getEnvDefaultTarget(runId!),
    enabled: !!runId,
  });
}

export function useRoutines() {
  return useQuery({
    queryKey: ['routines'],
    queryFn: () => api.listRoutines(),
  });
}

export function useGlobalConfig() {
  return useQuery({
    queryKey: ['globalConfig'],
    queryFn: getConfig,
    staleTime: Infinity,
  });
}

export function useRoutine(routineId: string | undefined | null) {
  return useQuery({
    queryKey: ['routine', routineId],
    queryFn: () => api.getRoutine(routineId!),
    enabled: !!routineId,
  });
}

export function useValidateRoutine() {
  return useMutation({
    mutationFn: (yamlContent: string) => validateRoutine(yamlContent),
  });
}

export function useAgents() {
  return useQuery({
    queryKey: ['agents'],
    queryFn: () => api.listAgents(),
  });
}

export function useTask(runId: string, taskId: string | undefined) {
  return useQuery({
    queryKey: ['task', runId, taskId],
    queryFn: () => api.getTask(runId, taskId!),
    enabled: !!taskId,
    refetchInterval: 10000,
  });
}

export function useActivity(runId: string | undefined) {
  return useQuery({
    queryKey: ['activity', runId],
    queryFn: () => api.getActivity(runId!),
    enabled: !!runId,
    refetchInterval: (query) => {
      // Stop polling for terminal run states (no new events expected)
      const hasMore = query.state.data?.has_more;
      if (hasMore) return 10000;
      return 10000;
    },
  });
}

export function useTaskPrompt(runId: string, taskId: string | undefined) {
  return useQuery({
    queryKey: ['task-prompt', runId, taskId],
    queryFn: () => api.getTaskPrompt(runId, taskId!),
    enabled: !!taskId,
    retry: false,
  });
}

export function useCreateRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: CreateRunRequest) => api.createRun(req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['runs'] }),
  });
}

export function useStartRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.startRun(runId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['runs'] }),
  });
}

export function usePauseRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.pauseRun(runId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['runs'] }),
  });
}

export function useResumeRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, agentType, agentConfig }: {
      runId: string;
      agentType?: string;
      agentConfig?: Record<string, unknown>;
    }) => api.resumeRun(runId, agentType || agentConfig ? { agent_type: agentType, agent_config: agentConfig } : undefined),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['runs'] }),
  });
}

export function useCancelRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.cancelRun(runId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['runs'] }),
  });
}

export function useAgentStarted(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.agentStarted(runId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}

export function useAgentCancelled(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.agentCancelled(runId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}

export function useRecoverRun(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: RecoverRequest) => api.recoverRun(runId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}

export function useTransitionBack(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { target_step_index: number; reason?: string }) => api.transitionBack(runId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}

export function useBackMerge(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.backMerge(runId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['run', runId] });
      qc.invalidateQueries({ queryKey: ['branchStatus', runId] });
    },
  });
}

export function useRevertEnvSnapshot(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (snapshotId: string) => api.revertEnvSnapshot(runId, snapshotId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['envFiles', runId] });
      qc.invalidateQueries({ queryKey: ['envSnapshots', runId] });
    },
  });
}

export function useCopyBackEnvFiles(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (targetPath: string) => api.copyBackEnvFiles(runId, targetPath),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['envFiles', runId] });
    },
  });
}

export function useDeleteRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.deleteRun(runId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['runs'] }),
  });
}

export function useMergeBack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, strategy, dirty_action }: { runId: string; strategy?: string; dirty_action?: 'stash' | 'commit' }) =>
      api.mergeBack(runId, { strategy, dirty_action }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['runs'] }),
  });
}

export function useStartTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, taskId }: { runId: string; taskId: string }) =>
      api.startTask(runId, taskId),
    onSuccess: (_data, { runId }) => {
      qc.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}

export function useSubmitTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, taskId }: { runId: string; taskId: string }) =>
      api.submitTask(runId, taskId),
    onSuccess: (_data, { runId }) => {
      qc.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}

export function useApproveStep(runId: string, stepId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { approved_by: string; comment?: string }) =>
      api.approveStep(runId, stepId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}

export function useUpdateChecklist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, taskId, reqId, data }: { runId: string; taskId: string; reqId: string; data: UpdateChecklistRequest }) =>
      api.updateChecklist(runId, taskId, reqId, data),
    onSuccess: (_data, { runId, taskId }) => {
      qc.invalidateQueries({ queryKey: ['task', runId, taskId] });
      qc.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}

export function useSetGrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, taskId, reqId, data }: { runId: string; taskId: string; reqId: string; data: SetGradeRequest }) =>
      api.setGrade(runId, taskId, reqId, data),
    onSuccess: (_data, { runId, taskId }) => {
      qc.invalidateQueries({ queryKey: ['task', runId, taskId] });
      qc.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}

export function useCompleteVerification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, taskId }: { runId: string; taskId: string }) =>
      api.completeVerification(runId, taskId),
    onSuccess: (_data, { runId, taskId }) => {
      qc.invalidateQueries({ queryKey: ['task', runId, taskId] });
      qc.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}

export function useAttemptLogs(runId: string, taskId: string, attemptNum: number | undefined) {
  return useQuery({
    queryKey: ['attempt-logs', runId, taskId, attemptNum],
    queryFn: () => api.getAttemptLogs(runId, taskId, attemptNum!),
    enabled: attemptNum !== undefined,
    staleTime: 30000, // Logs don't change once attempt is complete
  });
}

// Repos hooks
export function useRepos() {
  return useQuery({
    queryKey: ['repos'],
    queryFn: () => api.listRepos(),
  });
}

export function useRepo(name: string | undefined) {
  return useQuery({
    queryKey: ['repo', name],
    queryFn: () => api.getRepo(name!),
    enabled: !!name,
  });
}

export function useBranches(repoName: string | undefined, params?: { pattern?: string; include_remote?: boolean }) {
  return useQuery({
    queryKey: ['branches', repoName, params],
    queryFn: () => api.listBranches(repoName!, params),
    enabled: !!repoName,
  });
}

export function useBranchCount(repoName: string | undefined, params?: { pattern?: string; include_remote?: boolean }) {
  return useQuery({
    queryKey: ['branch-count', repoName, params],
    queryFn: () => api.countBranches(repoName!, params),
    enabled: !!repoName,
  });
}

export function useRepoRoutines(repoName: string | undefined, branch: string | undefined) {
  return useQuery({
    queryKey: ['repo-routines', repoName, branch],
    queryFn: () => api.listRepoRoutines(repoName!, branch!),
    enabled: !!repoName && !!branch,
  });
}

export function useRepoBranches(repoName: string | undefined, params?: { pattern?: string; include_remote?: boolean }) {
  return useQuery({
    queryKey: ['repo-branches', repoName, params],
    queryFn: () => api.getRepoBranches(repoName!, params),
    enabled: !!repoName,
  });
}

export function useRepoStats(repoName: string | undefined) {
  return useQuery({
    queryKey: ['repo-stats', repoName],
    queryFn: () => api.getRepoStats(repoName!),
    enabled: !!repoName,
  });
}
