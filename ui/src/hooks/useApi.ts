import { useInfiniteQuery, useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { useMemo } from 'react';
import { api, getConfig, isExpectedGraphPositionMismatch, isRetryableGraphReadError, validateRoutine } from '../api/client';
import type {
  CreateRunRequest,
  RecoverRequest,
  SetGradeRequest,
  UpdateChecklistRequest,
  GraphProjectionResponse,
  DecisionViewResponse,
  GraphEventsPage,
  GraphPatchAttemptsPage,
  FileStateReportResponse,
  SchedulerViewResponse,
  GraphHealthResponse,
  GraphTopologyResponse,
  FinalInvariantBlockersResponse,
  GraphRegionsResponse,
  NodeDetailResponse,
  RunEvidenceDigestResponse,
  RecordGraphDecisionRequest,
} from '../types';

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'stopping']);

/** Graph owners may briefly lag their authority stream; obsolete positions never will recover. */
export function retryGraphRead(failureCount: number, error: unknown): boolean {
  if (isExpectedGraphPositionMismatch(error)) return false;
  return isRetryableGraphReadError(error) && failureCount < 3;
}

export function useRuns(params?: { status?: string; repo_name?: string; limit?: number }) {
  return useQuery({
    queryKey: ['runs', params],
    queryFn: () => api.listRuns(params),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => {
      const runs = query.state.data?.runs;
      if (!runs?.length) return 10000;
      // Use a slower interval when the list contains only terminal runs
      const hasActiveRuns = runs.some((r) => !TERMINAL_STATUSES.has(r.status));
      return hasActiveRuns ? 10000 : 60000;
    },
  });
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return (status === 'completed' || status === 'failed' || status === 'cancelled')
        ? false
        : 10000;
    },
  });
}

export function useRunEvidenceDigest(
  runId: string | undefined,
  params?: { max_nodes?: number; include_node_evidence?: boolean; enabled?: boolean },
) {
  return useQuery<RunEvidenceDigestResponse>({
    queryKey: ['runEvidenceDigest', runId, params?.max_nodes, params?.include_node_evidence],
    queryFn: () =>
      api.getRunEvidenceDigest(runId!, {
        max_nodes: params?.max_nodes,
        include_node_evidence: params?.include_node_evidence,
      }),
    enabled: !!runId && (params?.enabled ?? true),
    staleTime: 5000,
  });
}

export function useGraphProjection(runId: string | undefined) {
  return useQuery<GraphProjectionResponse>({
    queryKey: ['graphProjection', runId],
    queryFn: () => api.getRunGraphProjection(runId!),
    enabled: !!runId,
    staleTime: 5000,
    retry: retryGraphRead,
  });
}

export interface ArchivalGraphSnapshot {
  position: number;
  topology: GraphTopologyResponse;
  finalBlockers: FinalInvariantBlockersResponse;
  regions: GraphRegionsResponse;
}

/**
 * Load the three coupled archival views from one graph position.  A 409 is
 * never retried against its obsolete position: the query obtains a new anchor
 * and restarts all siblings together.  A 503 remains a catch-up retry.
 */
export function useArchivalGraphSnapshot(runId: string | undefined) {
  return useQuery<ArchivalGraphSnapshot>({
    queryKey: ['archivalGraphSnapshot', runId],
    queryFn: async () => {
      let lastMismatch: unknown = null;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        const anchor = await api.getRunGraphProjection(runId!);
        try {
          const [topology, finalBlockers, regions] = await Promise.all([
            api.getRunGraphTopology(runId!, { expectedPosition: anchor.event_count }),
            api.getRunGraphFinalBlockers(runId!, { expectedPosition: anchor.event_count }),
            api.getRunGraphRegions(runId!, { expectedPosition: anchor.event_count }),
          ]);
          return { position: anchor.event_count, topology, finalBlockers, regions };
        } catch (error) {
          if (!isExpectedGraphPositionMismatch(error)) throw error;
          lastMismatch = error;
        }
      }
      throw lastMismatch;
    },
    enabled: !!runId,
    staleTime: 5000,
    retry: retryGraphRead,
  });
}

export function useGraphEvents(
  runId: string | undefined,
  params?: { fromPosition?: number; limit?: number; payloadMode?: 'summary' | 'full' },
) {
  const fromPosition = params?.fromPosition ?? 0;
  const limit = params?.limit ?? 50;
  const payloadMode = params?.payloadMode ?? 'summary';
  const query = useInfiniteQuery<GraphEventsPage>({
    queryKey: ['graphEvents', runId, fromPosition, limit, payloadMode],
    queryFn: ({ pageParam }) => api.getRunGraphEvents(runId!, {
      fromPosition: pageParam as number,
      limit,
      payloadMode,
    }),
    initialPageParam: fromPosition,
    getNextPageParam: (lastPage) => (
      lastPage.has_more && lastPage.next_position !== null
        ? lastPage.next_position
        : undefined
    ),
    enabled: !!runId,
    staleTime: 5000,
  });

  const events = useMemo(() => {
    const positions = new Set<number>();
    return query.data?.pages.flatMap((page) => page.events.filter((event) => {
      if (positions.has(event.position)) return false;
      positions.add(event.position);
      return true;
    })) ?? [];
  }, [query.data]);

  return { ...query, events };
}

/** Patch attempts are intentionally user-paged; never automatically exhaust history. */
export function useGraphPatchAttempts(
  runId: string | undefined,
  params?: { fromPosition?: number; limit?: number },
) {
  const fromPosition = params?.fromPosition ?? 0;
  const limit = params?.limit ?? 25;
  const query = useInfiniteQuery<GraphPatchAttemptsPage>({
    queryKey: ['graphPatchAttempts', runId, fromPosition, limit],
    queryFn: ({ pageParam }) => api.getRunGraphPatchAttempts(runId!, {
      fromPosition: pageParam as number,
      limit,
    }),
    initialPageParam: fromPosition,
    getNextPageParam: (lastPage) => (
      lastPage.has_more && lastPage.next_position !== null ? lastPage.next_position : undefined
    ),
    enabled: !!runId,
    staleTime: 5000,
  });
  const attempts = useMemo(() => {
    const seen = new Set<string>();
    return query.data?.pages.flatMap((page, pageIndex) => page.attempts.filter((attempt, attemptIndex) => {
      const identity = graphPatchAttemptIdentity(attempt, pageIndex, attemptIndex);
      if (seen.has(identity)) return false;
      seen.add(identity);
      return true;
    })) ?? [];
  }, [query.data]);
  const partial = query.data?.pages.some((page) => page.partial) ?? false;
  const orphanOutcomeCount = query.data?.pages.reduce(
    (count, page) => count + page.orphan_outcome_count,
    0,
  ) ?? 0;
  return { ...query, attempts, partial, orphanOutcomeCount };
}

function graphPatchAttemptIdentity(
  attempt: GraphPatchAttemptsPage['attempts'][number],
  pageIndex: number,
  attemptIndex: number,
): string {
  if (!attempt.patch_id_truncated) return `id:${attempt.patch_id}`;
  if (attempt.patch_id_sha256) {
    return `sha256:${attempt.patch_id_original_chars ?? 'unknown'}:${attempt.patch_id_sha256}`;
  }
  // A malformed truncated response has no stable identity. Keep it visible
  // rather than merging two distinct long IDs by their shared prefix.
  return `invalid-truncated:${pageIndex}:${attemptIndex}`;
}

export function useSchedulerView(runId: string | undefined) {
  return useQuery<SchedulerViewResponse>({
    queryKey: ['graphScheduler', runId],
    queryFn: () => api.getRunGraphScheduler(runId!),
    enabled: !!runId,
    staleTime: 5000,
    retry: retryGraphRead,
  });
}

export function useGraphHealth(runId: string | undefined, enabled = true) {
  return useQuery<GraphHealthResponse>({
    queryKey: ['graphHealth', runId],
    queryFn: () => api.getRunGraphHealth(runId!),
    enabled: enabled && !!runId,
    staleTime: 5000,
  });
}

export function useDecisionView(runId: string | undefined) {
  return useQuery<DecisionViewResponse>({
    queryKey: ['graphDecisions', runId],
    queryFn: () => api.getRunGraphDecisions(runId!),
    enabled: !!runId,
    staleTime: 5000,
    retry: retryGraphRead,
  });
}

export function useRecordGraphDecision(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: RecordGraphDecisionRequest) => api.recordRunGraphDecision(runId, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['graphDecisions', runId] });
      void queryClient.invalidateQueries({ queryKey: ['graphProjection', runId] });
      void queryClient.invalidateQueries({ queryKey: ['graphScheduler', runId] });
      void queryClient.invalidateQueries({ queryKey: ['graphEvents', runId] });
      void queryClient.invalidateQueries({ queryKey: ['graphNodeDetail', runId] });
      void queryClient.invalidateQueries({ queryKey: ['run', runId] });
    },
  });
}

export function mergeFileStateReportPages(
  pages: FileStateReportResponse[],
  hasMore: boolean,
): FileStateReportResponse | undefined {
    if (pages.length === 0) return undefined;
    const first = pages[0];
    const boundariesByNode = new Map<string, Map<string, FileStateReportResponse['nodes'][number]['boundaries'][number]>>();
    const uniquePages: FileStateReportResponse[] = [];
    const seenPageBoundaries = new Set<string>();
    for (const page of pages) {
      const boundaryIds = page.nodes.flatMap((node) => node.boundaries.map((boundary) => boundary.record_id));
      const pageKey = boundaryIds.slice().sort().join('\u0000');
      if (seenPageBoundaries.has(pageKey)) continue;
      seenPageBoundaries.add(pageKey);
      uniquePages.push(page);
      for (const node of page.nodes) {
        const boundaries = boundariesByNode.get(node.node_id) ?? new Map();
        for (const boundary of node.boundaries) boundaries.set(boundary.record_id, boundary);
        boundariesByNode.set(node.node_id, boundaries);
      }
    }
    const numericGatekeeperFields = [
      'boundary_count', 'deterministic_classifications', 'gatekeeper_consults',
      'gatekeeper_resolved', 'unresolved_residue', 'total_classified',
      'gen_ai_usage_input_tokens', 'gen_ai_usage_output_tokens',
      'gen_ai_usage_cache_read_input_tokens', 'gen_ai_usage_cache_creation_input_tokens',
      'cost_usd', 'wall_time_ms',
    ];
    const gatekeeper = uniquePages.reduce<Record<string, unknown> | null>((total, page) => {
      if (page.gatekeeper === null) return total;
      const next = total ? { ...total } : {};
      for (const field of numericGatekeeperFields) {
        next[field] = Number(next[field] ?? 0) + Number(page.gatekeeper[field] ?? 0);
      }
      const models = { ...(next.models as Record<string, Record<string, unknown>> | undefined) };
      const pageModels = page.gatekeeper.models as Record<string, Record<string, unknown>> | undefined;
      for (const [modelId, model] of Object.entries(pageModels ?? {})) {
        const aggregate = { ...(models[modelId] ?? { model_id: modelId, executions: [] }) };
        for (const field of ['consults', ...numericGatekeeperFields.slice(6)]) {
          aggregate[field] = Number(aggregate[field] ?? 0) + Number(model[field] ?? 0);
        }
        aggregate.executions = [...new Set([
          ...((aggregate.executions as string[] | undefined) ?? []),
          ...((model.executions as string[] | undefined) ?? []),
        ])];
        models[modelId] = aggregate;
      }
      next.models = models;
      return next;
    }, null);
    if (gatekeeper !== null) {
      const totalClassified = Number(gatekeeper.total_classified ?? 0);
      gatekeeper.hit_rate = totalClassified > 0
        ? Number(gatekeeper.deterministic_classifications ?? 0) / totalClassified
        : 0;
    }
    return {
      ...first,
      event_count: pages.reduce((count, page) => count + page.event_count, 0),
      nodes: [...boundariesByNode.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([node_id, boundaries]) => ({
          node_id,
          boundaries: [...boundaries.values()].sort((left, right) => left.record_id.localeCompare(right.record_id)),
        })),
      orphan_gatekeeper_fact_count: pages[0].orphan_gatekeeper_fact_count,
      gatekeeper,
      // Keep incompleteness sticky even when React Query presents a refreshed
      // duplicate boundary page that is later deduplicated for metrics.
      gatekeeper_metrics_truncated: pages.some((page) => page.gatekeeper_metrics_truncated),
      has_more: hasMore,
      next_position: hasMore ? pages.at(-1)?.next_position ?? null : null,
    };
}

export function useFileStateReport(runId: string | undefined) {
  const query = useInfiniteQuery<FileStateReportResponse>({
    queryKey: ['graphFileState', runId],
    queryFn: ({ pageParam }) => api.getRunGraphFileState(runId!, { fromPosition: pageParam as number }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => (
      lastPage?.has_more && lastPage.next_position !== null ? lastPage.next_position : undefined
    ),
    enabled: !!runId,
    staleTime: 5000,
  });
  const report = useMemo(
    () => mergeFileStateReportPages(query.data?.pages ?? [], query.hasNextPage),
    [query.data, query.hasNextPage],
  );
  return { ...query, data: report };
}

export function useGraphNodeDetail(runId: string | undefined, nodeId: string | undefined) {
  return useQuery<NodeDetailResponse>({
    queryKey: ['graphNodeDetail', runId, nodeId],
    queryFn: () => api.getRunGraphNodeDetail(runId!, nodeId!),
    enabled: !!runId && !!nodeId,
    staleTime: 5000,
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

export function useRoutines(options?: { includeArchived?: boolean }) {
  return useQuery({
    queryKey: ['routines', options],
    queryFn: () => api.listRoutines(options),
  });
}

export function useArchiveRoutine() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (routineId: string) => api.archiveRoutine(routineId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['routines'] }),
  });
}

export function useUnarchiveRoutine() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (routineId: string) => api.unarchiveRoutine(routineId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['routines'] }),
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

export function useAgentRunners() {
  return useQuery({
    queryKey: ['agent-runners'],
    queryFn: () => api.listAgentRunners(),
    refetchInterval: 60_000,
    staleTime: 30_000,
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

export function useActivity(runId: string | undefined, runStatus?: string) {
  return useQuery({
    queryKey: ['activity', runId],
    queryFn: () => api.getActivity(runId!, { payload_mode: 'full' }),
    enabled: !!runId,
    refetchInterval: () => {
      // Stop polling once the run reaches a terminal state — no new events will arrive
      if (runStatus && TERMINAL_STATUSES.has(runStatus)) return false;
      return 10000;
    },
  });
}

export function useRunTrace(runId: string | undefined) {
  return useQuery({
    queryKey: ['run-trace', runId],
    queryFn: () => api.getRunTrace(runId!),
    enabled: !!runId,
    staleTime: 30000,
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
    mutationFn: ({ runId, agentType, agentConfig, resumeStrategy }: {
      runId: string;
      agentType?: string;
      agentConfig?: Record<string, unknown>;
      resumeStrategy?: string;
    }) => {
      const hasPayload = agentType || agentConfig || resumeStrategy;
      return api.resumeRun(runId, hasPayload ? {
        agent_runner_type: agentType,
        agent_runner_config: agentConfig,
        resume_strategy: resumeStrategy,
      } : undefined);
    },
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

export function useSkipStep(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stepId: string) => api.skipStep(runId, stepId),
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
