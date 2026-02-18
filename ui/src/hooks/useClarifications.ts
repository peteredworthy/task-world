import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { ClarificationHistoryItem, ClarificationHistoryResponse, RespondToClarificationRequest } from '../types';

export function usePendingClarification(runId: string, taskId: string | undefined) {
  return useQuery({
    queryKey: ['pending-clarification', runId, taskId],
    queryFn: () => api.getPendingClarification(runId, taskId!),
    enabled: !!taskId,
    refetchInterval: 10000,
  });
}

export function useRespondToClarification(runId: string, taskId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ requestId, data }: { requestId: string; data: RespondToClarificationRequest }) =>
      api.respondToClarification(runId, taskId, requestId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pending-clarification', runId, taskId] });
      qc.invalidateQueries({ queryKey: ['task', runId, taskId] });
      qc.invalidateQueries({ queryKey: ['run', runId] });
      qc.invalidateQueries({ queryKey: ['pending-actions', runId] });
    },
  });
}

export function useClarificationHistory(
  runId: string | undefined,
  taskId: string | undefined,
) {
  return useQuery<ClarificationHistoryItem[]>({
    queryKey: ['clarification-history', runId, taskId],
    queryFn: async () => {
      const response = await fetch(`/api/runs/${runId}/tasks/${taskId}/clarifications`);
      if (!response.ok) {
        throw new Error(`Failed to fetch clarification history: ${response.status}`);
      }
      const data = (await response.json()) as ClarificationHistoryResponse;
      return data.items;
    },
    enabled: !!runId && !!taskId,
    staleTime: 30_000,
  });
}
