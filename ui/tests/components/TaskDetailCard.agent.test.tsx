import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TaskDetailCard } from '../../src/components/detail/TaskDetailCard';
import type { GradeSummaryItem, AttemptOutcome, ActivityEvent, TaskDetail } from '../../src/types';
import * as apiHooks from '../../src/hooks/useApi';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function makeAttemptOutcome(attempt_num: number, outcome: string | null = null): AttemptOutcome {
  return { attempt_num, outcome };
}

function renderCard(props: {
  taskId?: string;
  taskTitle?: string;
  stepTitle?: string;
  status?: string;
  events?: ActivityEvent[];
  gradeSummary?: GradeSummaryItem[];
  attemptsSummary?: AttemptOutcome[];
  runId?: string;
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <TaskDetailCard
        taskId={props.taskId ?? 'task-1'}
        taskTitle={props.taskTitle ?? 'Implement feature'}
        stepTitle={props.stepTitle ?? 'Setup'}
        status={props.status ?? 'pending'}
        events={props.events ?? []}
        gradeSummary={props.gradeSummary ?? []}
        attemptsSummary={props.attemptsSummary ?? []}
        runId={props.runId ?? 'run-1'}
      />
    </QueryClientProvider>
  );
}

async function expandTaskAndAttempts() {
  const toggleBtn = screen.getByRole('button', { name: /Toggle details for task/ });
  await userEvent.click(toggleBtn);

  // New UI: attempts are always listed and each attempt is its own accordion row.
  // Backward-compatible fallback: if an Attempts section button exists, click it first.
  const attemptsButton = screen.queryByRole('button', { name: /Attempts/i });
  if (attemptsButton) {
    await userEvent.click(attemptsButton);
  }

  const attemptOneButton = screen.getByRole('button', { name: /Attempt #1/i });
  await userEvent.click(attemptOneButton);
}

describe('TaskDetailCard - Agent Display', () => {
  describe('attempt agent info rendering', () => {
    it('shows agent icon and type when attempt has agent_runner_type', async () => {
      // Mock the useTask hook to return attempt data with agent info
      const mockTaskDetail: TaskDetail = {
        id: 'task-1',
        run_id: 'run-1',
        step_id: 'step-1',
        config_id: 'tc1',
        title: 'Implement feature',
        status: 'building',
        current_attempt: 1,
        max_attempts: 3,
        checklist: [],
        attempts: [
          {
            id: 'att-1',
            task_id: 'task-1',
            attempt_num: 1,
            started_at: new Date().toISOString(),
            completed_at: null,
            outcome: null,
            agent_runner_type: 'openhands_local',
            agent_model: null,
            grade_snapshot: [],
            builder_prompt: null,
            verifier_prompt: null,
            verifier_comment: null,
            metrics: {},
            auto_verify_results: null,
            agent_settings: {},
          },
        ],
      };

      vi.spyOn(apiHooks, 'useTask').mockReturnValue({
        data: mockTaskDetail,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      } as any);

      renderCard({ taskId: 'task-1' });

      await expandTaskAndAttempts();

      // Wait for the attempt to be displayed
      await waitFor(() => {
        expect(screen.getByText('Attempt #1')).toBeInTheDocument();
      });

      // Check for agent runner type display (formatted)
      expect(screen.getByText('Openhands Local')).toBeInTheDocument();
    });

    it('shows agent model when present', async () => {
      const mockTaskDetail: TaskDetail = {
        id: 'task-1',
        run_id: 'run-1',
        step_id: 'step-1',
        config_id: 'tc1',
        title: 'Implement feature',
        status: 'building',
        current_attempt: 1,
        max_attempts: 3,
        checklist: [],
        attempts: [
          {
            id: 'att-1',
            task_id: 'task-1',
            attempt_num: 1,
            started_at: new Date().toISOString(),
            completed_at: null,
            outcome: null,
            agent_runner_type: 'openhands_local',
            agent_model: 'gpt-4o',
            grade_snapshot: [],
            builder_prompt: null,
            verifier_prompt: null,
            verifier_comment: null,
            metrics: {},
            auto_verify_results: null,
            agent_settings: {},
          },
        ],
      };

      vi.spyOn(apiHooks, 'useTask').mockReturnValue({
        data: mockTaskDetail,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      } as any);

      renderCard({ taskId: 'task-1' });

      await expandTaskAndAttempts();

      // Wait for the attempt with model to be displayed
      await waitFor(() => {
        expect(screen.getByText('gpt-4o')).toBeInTheDocument();
      });
    });

    it('shows token count when available', async () => {
      const mockTaskDetail: TaskDetail = {
        id: 'task-1',
        run_id: 'run-1',
        step_id: 'step-1',
        config_id: 'tc1',
        title: 'Implement feature',
        status: 'completed',
        current_attempt: 1,
        max_attempts: 3,
        checklist: [],
        attempts: [
          {
            id: 'att-1',
            task_id: 'task-1',
            attempt_num: 1,
            started_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
            outcome: 'pass',
            agent_runner_type: 'openhands_local',
            agent_model: 'gpt-4o',
            grade_snapshot: [],
            builder_prompt: null,
            verifier_prompt: null,
            verifier_comment: null,
            metrics: {
              tokens_read: 1500,
              tokens_write: 500,
            },
          },
        ],
      };

      vi.spyOn(apiHooks, 'useTask').mockReturnValue({
        data: mockTaskDetail,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      } as any);

      renderCard({ taskId: 'task-1' });

      await expandTaskAndAttempts();

      // Wait for token count to be displayed (shown in agent info line as total tokens)
      await waitFor(() => {
        // Total is 2000 tokens, formatted as "2.0k tokens"
        expect(screen.getByText(/2\.0k tokens/i)).toBeInTheDocument();
      });
    });

    it('handles null agent_runner_type gracefully', async () => {
      const mockTaskDetail: TaskDetail = {
        id: 'task-1',
        run_id: 'run-1',
        step_id: 'step-1',
        config_id: 'tc1',
        title: 'Implement feature',
        status: 'pending',
        current_attempt: 1,
        max_attempts: 3,
        checklist: [],
        attempts: [
          {
            id: 'att-1',
            task_id: 'task-1',
            attempt_num: 1,
            started_at: new Date().toISOString(),
            completed_at: null,
            outcome: null,
            agent_runner_type: null,
            agent_model: null,
            grade_snapshot: [],
            builder_prompt: null,
            verifier_prompt: null,
            verifier_comment: null,
            metrics: {},
            auto_verify_results: null,
            agent_settings: {},
          },
        ],
      };

      vi.spyOn(apiHooks, 'useTask').mockReturnValue({
        data: mockTaskDetail,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      } as any);

      renderCard({ taskId: 'task-1' });

      await expandTaskAndAttempts();

      // Wait for the attempt to be displayed
      await waitFor(() => {
        expect(screen.getByText('Attempt #1')).toBeInTheDocument();
      });

      // Should not show agent info section when agent_runner_type is null
      expect(screen.queryByText(/Openhands/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/CLI/i)).not.toBeInTheDocument();
    });

    it('shows different agent icons for different types', async () => {
      const mockTaskDetail: TaskDetail = {
        id: 'task-1',
        run_id: 'run-1',
        step_id: 'step-1',
        config_id: 'tc1',
        title: 'Implement feature',
        status: 'completed',
        current_attempt: 3,
        max_attempts: 3,
        checklist: [],
        attempts: [
          {
            id: 'att-1',
            task_id: 'task-1',
            attempt_num: 1,
            started_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
            outcome: 'revision',
            agent_runner_type: 'cli_subprocess',
            agent_model: null,
            grade_snapshot: [],
            builder_prompt: null,
            verifier_prompt: null,
            verifier_comment: null,
            metrics: {},
            auto_verify_results: null,
            agent_settings: {},
          },
          {
            id: 'att-2',
            task_id: 'task-1',
            attempt_num: 2,
            started_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
            outcome: 'revision',
            agent_runner_type: 'openhands_docker',
            agent_model: null,
            grade_snapshot: [],
            builder_prompt: null,
            verifier_prompt: null,
            verifier_comment: null,
            metrics: {},
            auto_verify_results: null,
            agent_settings: {},
          },
          {
            id: 'att-3',
            task_id: 'task-1',
            attempt_num: 3,
            started_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
            outcome: 'pass',
            agent_runner_type: 'cli_subprocess',
            agent_model: null,
            grade_snapshot: [],
            builder_prompt: null,
            verifier_prompt: null,
            verifier_comment: null,
            metrics: {},
            auto_verify_results: null,
            agent_settings: {},
          },
        ],
      };

      vi.spyOn(apiHooks, 'useTask').mockReturnValue({
        data: mockTaskDetail,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      } as any);

      renderCard({ taskId: 'task-1', attemptsSummary: [
        makeAttemptOutcome(1, 'revision'),
        makeAttemptOutcome(2, 'revision'),
        makeAttemptOutcome(3, 'pass'),
      ]});

      await expandTaskAndAttempts();

      // Wait for all attempts to be displayed
      await waitFor(() => {
        expect(screen.getAllByText('Cli Subprocess').length).toBeGreaterThanOrEqual(2);
        expect(screen.getByText('Openhands Docker')).toBeInTheDocument();
      });
    });
  });

  describe('agent label rendering', () => {
    it('uses CLI command name when present', async () => {
      const mockTaskDetail: TaskDetail = {
        id: 'task-1',
        run_id: 'run-1',
        step_id: 'step-1',
        config_id: 'tc1',
        title: 'Implement feature',
        status: 'building',
        current_attempt: 1,
        max_attempts: 3,
        checklist: [],
        attempts: [
          {
            id: 'att-1',
            task_id: 'task-1',
            attempt_num: 1,
            started_at: new Date().toISOString(),
            completed_at: null,
            outcome: null,
            agent_runner_type: 'cli_subprocess',
            agent_model: null,
            grade_snapshot: [],
            builder_prompt: null,
            verifier_prompt: null,
            verifier_comment: null,
            metrics: {},
            auto_verify_results: null,
            agent_settings: { command: 'codex' },
          },
        ],
      };

      vi.spyOn(apiHooks, 'useTask').mockReturnValue({
        data: mockTaskDetail,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      } as any);

      renderCard({ taskId: 'task-1' });

      await expandTaskAndAttempts();

      await waitFor(() => {
        expect(screen.getByText('Agent Runner:')).toBeInTheDocument();
        expect(screen.getByText('codex')).toBeInTheDocument();
      });
    });

    it('falls back to formatted agent runner type when command is unavailable', async () => {
      const mockTaskDetail: TaskDetail = {
        id: 'task-1',
        run_id: 'run-1',
        step_id: 'step-1',
        config_id: 'tc1',
        title: 'Implement feature',
        status: 'building',
        current_attempt: 1,
        max_attempts: 3,
        checklist: [],
        attempts: [
          {
            id: 'att-1',
            task_id: 'task-1',
            attempt_num: 1,
            started_at: new Date().toISOString(),
            completed_at: null,
            outcome: null,
            agent_runner_type: 'openhands_local',
            agent_model: null,
            grade_snapshot: [],
            builder_prompt: null,
            verifier_prompt: null,
            verifier_comment: null,
            metrics: {},
            auto_verify_results: null,
            agent_settings: {},
          },
        ],
      };

      vi.spyOn(apiHooks, 'useTask').mockReturnValue({
        data: mockTaskDetail,
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      } as any);

      renderCard({ taskId: 'task-1' });

      await expandTaskAndAttempts();

      await waitFor(() => {
        expect(screen.getByText('Openhands Local')).toBeInTheDocument();
      });
    });
  });
});
