import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { PendingAction, StepSummary } from '../types';

interface StepApprovalGateAction {
  action_type: 'step_approval_gate';
  step_id: string;
  step_title: string;
}

export interface PendingActionsData {
  pendingActions: PendingAction[];
  pendingApprovalGates: StepSummary[];
  actionList: Array<PendingAction | StepApprovalGateAction>;
  badgeCount: number;
}

export function usePendingActions(runId: string | undefined) {
  return useQuery<PendingActionsData>({
    queryKey: ['pending-actions', runId],
    queryFn: async () => {
      const [pendingActions, run] = await Promise.all([
        api.getPendingActions(runId!),
        api.getRun(runId!),
      ]);

      const pendingApprovalGates = run.steps.filter(
        (step) => step.has_approval_gate && step.approval_status === 'pending',
      );

      const actionList: Array<PendingAction | StepApprovalGateAction> = [
        ...pendingActions,
        ...pendingApprovalGates.map((step) => ({
          action_type: 'step_approval_gate' as const,
          step_id: step.id,
          step_title: step.title || step.config_id,
        })),
      ];

      return {
        pendingActions,
        pendingApprovalGates,
        actionList,
        badgeCount: actionList.length,
      };
    },
    enabled: !!runId,
    refetchInterval: 10000,
  });
}
