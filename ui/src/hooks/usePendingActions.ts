import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

export function usePendingActions(runId: string | undefined) {
  return useQuery({
    queryKey: ['pending-actions', runId],
    queryFn: () => api.getPendingActions(runId!),
    enabled: !!runId,
    refetchInterval: 10000,
  });
}
