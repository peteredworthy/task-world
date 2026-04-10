import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { PendingAction } from '../types';

export interface PendingActionsData {
  pendingActions: PendingAction[];
  badgeCount: number;
}

export function usePendingActions(runId: string | undefined) {
  return useQuery<PendingActionsData>({
    queryKey: ['pending-actions', runId],
    queryFn: async () => {
      const pendingActions = await api.getPendingActions(runId!);

      return {
        pendingActions,
        badgeCount: pendingActions.length,
      };
    },
    enabled: !!runId,
    refetchInterval: 10000,
  });
}
