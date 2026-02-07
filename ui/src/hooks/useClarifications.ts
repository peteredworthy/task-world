import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { RespondToClarificationRequest } from '../types';

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
