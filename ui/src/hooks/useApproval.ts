import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { ApproveTaskRequest, RejectTaskRequest } from '../types';

export function useApproveTask(runId: string, taskId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ApproveTaskRequest) => api.approveTask(runId, taskId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['task', runId, taskId] });
      qc.invalidateQueries({ queryKey: ['run', runId] });
      qc.invalidateQueries({ queryKey: ['pending-actions', runId] });
    },
  });
}

export function useRejectTask(runId: string, taskId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: RejectTaskRequest) => api.rejectTask(runId, taskId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['task', runId, taskId] });
      qc.invalidateQueries({ queryKey: ['run', runId] });
      qc.invalidateQueries({ queryKey: ['pending-actions', runId] });
    },
  });
}

export function useApproveStep(runId: string, stepId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { comment?: string }) =>
      api.approveStep(runId, stepId, { approved_by: 'user', ...data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['run', runId] });
      qc.invalidateQueries({ queryKey: ['pending-actions', runId] });
    },
  });
}
