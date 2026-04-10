import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ClarificationModal } from '../../src/components/detail/ClarificationModal';
import * as clarificationHooks from '../../src/hooks/useClarifications';
import type { ClarificationRequest } from '../../src/types/clarifications';

function renderModal() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  const request: ClarificationRequest = {
    id: 'clar-1',
    run_id: 'run-1',
    task_id: 'task-1',
    attempt_num: 1,
    created_at: new Date().toISOString(),
    responded_at: null,
    questions: [
      {
        id: 'q1',
        question: 'Should snake wrap at edges?',
        context: 'Gameplay rule',
        options: ['Wrap', 'Game over'],
      },
    ],
  };

  return render(
    <QueryClientProvider client={queryClient}>
      <ClarificationModal
        open={true}
        onClose={() => {}}
        clarificationRequest={request}
        runId="run-1"
        taskId="task-1"
      />
    </QueryClientProvider>
  );
}

describe('ClarificationModal', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('submits selected answers', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ success: true });
    vi.spyOn(clarificationHooks, 'useRespondToClarification').mockReturnValue({
      mutateAsync,
      isPending: false,
      isError: false,
    } as ReturnType<typeof clarificationHooks.useRespondToClarification>);

    renderModal();

    await userEvent.click(screen.getByRole('radio', { name: /Wrap/i }));
    await userEvent.click(screen.getByRole('button', { name: 'Submit Answers' }));

    expect(mutateAsync).toHaveBeenCalledTimes(1);
    expect(mutateAsync).toHaveBeenCalledWith({
      requestId: 'clar-1',
      data: {
        answers: [
          {
            question_id: 'q1',
            selected_option: 'Wrap',
            free_text: null,
          },
        ],
      },
    });
  });
});
