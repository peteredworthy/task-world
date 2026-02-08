import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApprovalModal } from '../../src/components/detail/ApprovalModal';
import * as approvalHooks from '../../src/hooks/useApproval';
import type { PendingAction } from '../../src/types/clarifications';

function renderModal() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  const pendingAction: PendingAction = {
    task_id: 'task-1',
    step_id: 'step-1',
    action_type: 'approval',
    clarification_request: null,
    summary_artifact: null,
    approval_prompt: 'Review docs and approve to continue.',
  };

  return render(
    <QueryClientProvider client={queryClient}>
      <ApprovalModal
        open={true}
        onClose={() => {}}
        pendingAction={pendingAction}
        runId="run-1"
      />
    </QueryClientProvider>
  );
}

describe('ApprovalModal', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('submits approval', async () => {
    const approveMutateAsync = vi.fn().mockResolvedValue({ success: true });
    const rejectMutateAsync = vi.fn().mockResolvedValue({ success: true });

    vi.spyOn(approvalHooks, 'useApproveTask').mockReturnValue({
      mutateAsync: approveMutateAsync,
      isPending: false,
      isError: false,
    } as ReturnType<typeof approvalHooks.useApproveTask>);

    vi.spyOn(approvalHooks, 'useRejectTask').mockReturnValue({
      mutateAsync: rejectMutateAsync,
      isPending: false,
      isError: false,
    } as ReturnType<typeof approvalHooks.useRejectTask>);

    renderModal();

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));

    expect(approveMutateAsync).toHaveBeenCalledTimes(1);
    expect(approveMutateAsync).toHaveBeenCalledWith({
      comment: undefined,
    });
  });
});
