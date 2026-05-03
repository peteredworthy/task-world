import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TaskDetailCard } from '../../src/components/detail/TaskDetailCard';
import type { GradeSummaryItem, AttemptOutcome, ActivityEvent } from '../../src/types';

afterEach(cleanup);

function makeGrade(grade: string | null, priority: 'critical' | 'expected' | 'nice' = 'expected'): GradeSummaryItem {
  return { grade, priority };
}

function makeAttemptOutcome(attempt_num: number, outcome: string | null = null): AttemptOutcome {
  return { attempt_num, outcome };
}

/**
 * Wrap component with QueryClientProvider so useTask/useTaskPrompt hooks can mount.
 * In the collapsed state these hooks receive `undefined` as taskId, so they
 * never fire a request -- no network/mocking needed.
 */
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

describe('TaskDetailCard', () => {
  describe('collapsed state', () => {
    it('renders the task title', () => {
      renderCard({ taskTitle: 'Write unit tests' });
      expect(screen.getByText('Write unit tests')).toBeInTheDocument();
    });

    it('renders the step title', () => {
      renderCard({ stepTitle: 'Verification' });
      expect(screen.getByText('Verification')).toBeInTheDocument();
    });

    it('renders a status badge for pending status', () => {
      renderCard({ status: 'pending' });
      expect(screen.getByText('pending')).toBeInTheDocument();
    });

    it('renders a status badge for building status', () => {
      renderCard({ status: 'building' });
      expect(screen.getByText('building')).toBeInTheDocument();
    });

    it('renders a status badge for completed status', () => {
      renderCard({ status: 'completed' });
      expect(screen.getByText('completed')).toBeInTheDocument();
    });

    it('renders a status badge for failed status', () => {
      renderCard({ status: 'failed' });
      expect(screen.getByText('failed')).toBeInTheDocument();
    });

    it('renders compact grade badges when grades are present', () => {
      renderCard({
        gradeSummary: [
          makeGrade('A', 'critical'),
          makeGrade('B', 'expected'),
        ],
      });
      expect(screen.getByText('A')).toBeInTheDocument();
      expect(screen.getByText('B')).toBeInTheDocument();
    });

    it('does not render grade badges when all grades are null', () => {
      renderCard({
        gradeSummary: [
          makeGrade(null, 'critical'),
          makeGrade(null, 'expected'),
        ],
      });
      // The CompactGradeBadges filters out null/"-" grades, so no badge text appears
      expect(screen.queryByTitle(/critical/)).not.toBeInTheDocument();
    });

    it('does not render grade badges when grade is "-"', () => {
      renderCard({
        gradeSummary: [makeGrade('-', 'critical')],
      });
      // "-" is filtered by CompactGradeBadges
      expect(screen.queryByTitle(/critical/)).not.toBeInTheDocument();
    });

    it('shows attempt count when more than 1 attempt', () => {
      renderCard({
        attemptsSummary: [
          makeAttemptOutcome(1, 'revision'),
          makeAttemptOutcome(2, null),
          makeAttemptOutcome(3, null),
        ],
      });
      expect(screen.getByText('x3')).toBeInTheDocument();
    });

    it('does not show attempt count when only 1 attempt', () => {
      renderCard({
        attemptsSummary: [makeAttemptOutcome(1, null)],
      });
      expect(screen.queryByText('x1')).not.toBeInTheDocument();
    });

    it('does not show attempt count when no attempts', () => {
      renderCard({ attemptsSummary: [] });
      expect(screen.queryByText(/^x\d+$/)).not.toBeInTheDocument();
    });

    it('shows a chevron indicator', () => {
      renderCard({});
      // The chevron is an svg with a path; it's inside the button.
      // We can verify the toggle button exists via its aria-label.
      const toggleBtn = screen.getByRole('button', { name: /Toggle details for task/ });
      expect(toggleBtn).toBeInTheDocument();
      // The chevron svg is inside the button - verify it has an svg child
      const svgs = toggleBtn.querySelectorAll('svg');
      // At least one SVG should be the chevron (the last one)
      expect(svgs.length).toBeGreaterThan(0);
    });

    it('starts with aria-expanded=false', () => {
      renderCard({ taskTitle: 'My task' });
      const toggleBtn = screen.getByRole('button', { name: /Toggle details for task: My task/ });
      expect(toggleBtn).toHaveAttribute('aria-expanded', 'false');
    });
  });

  describe('expand/collapse', () => {
    it('sets aria-expanded to true when clicked', async () => {
      renderCard({ taskTitle: 'Expand me' });
      const toggleBtn = screen.getByRole('button', { name: /Toggle details for task: Expand me/ });

      expect(toggleBtn).toHaveAttribute('aria-expanded', 'false');

      await userEvent.click(toggleBtn);

      expect(toggleBtn).toHaveAttribute('aria-expanded', 'true');
    });

    it('toggles back to collapsed on second click', async () => {
      renderCard({ taskTitle: 'Toggle me' });
      const toggleBtn = screen.getByRole('button', { name: /Toggle details for task: Toggle me/ });

      await userEvent.click(toggleBtn); // expand
      expect(toggleBtn).toHaveAttribute('aria-expanded', 'true');

      await userEvent.click(toggleBtn); // collapse
      expect(toggleBtn).toHaveAttribute('aria-expanded', 'false');
    });
  });

  describe('multiple cards', () => {
    it('each card manages its own expanded state independently', async () => {
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });

      render(
        <QueryClientProvider client={queryClient}>
          <TaskDetailCard
            taskId="task-1"
            taskTitle="First task"
            stepTitle="Step 1"
            status="pending"
            events={[]}
            gradeSummary={[]}
            attemptsSummary={[]}
            runId="run-1"
          />
          <TaskDetailCard
            taskId="task-2"
            taskTitle="Second task"
            stepTitle="Step 1"
            status="completed"
            events={[]}
            gradeSummary={[]}
            attemptsSummary={[]}
            runId="run-1"
          />
        </QueryClientProvider>
      );

      const btn1 = screen.getByRole('button', { name: /Toggle details for task: First task/ });
      const btn2 = screen.getByRole('button', { name: /Toggle details for task: Second task/ });

      // Both start collapsed
      expect(btn1).toHaveAttribute('aria-expanded', 'false');
      expect(btn2).toHaveAttribute('aria-expanded', 'false');

      // Expand first card only
      await userEvent.click(btn1);
      expect(btn1).toHaveAttribute('aria-expanded', 'true');
      expect(btn2).toHaveAttribute('aria-expanded', 'false');

      // Expand second card too - both should be expanded
      await userEvent.click(btn2);
      expect(btn1).toHaveAttribute('aria-expanded', 'true');
      expect(btn2).toHaveAttribute('aria-expanded', 'true');
    });
  });

  describe('grade badge tooltips', () => {
    it('renders grade badges with priority in title attribute', () => {
      renderCard({
        gradeSummary: [
          makeGrade('A', 'critical'),
          makeGrade('C', 'nice'),
        ],
      });

      const gradeA = screen.getByText('A');
      expect(gradeA).toHaveAttribute('title', 'critical: A');

      const gradeC = screen.getByText('C');
      expect(gradeC).toHaveAttribute('title', 'nice: C');
    });
  });

  describe('per-attempt agent display', () => {
    // Note: These tests verify the component structure in collapsed state.
    // The expanded state would require mocking the useTask hook which is
    // beyond the scope of these unit tests. The rendering logic for
    // attempt agent info is tested through integration tests.

    it('component accepts events prop with agent data', () => {
      const events: ActivityEvent[] = [
        {
          id: 'evt-1',
          run_id: 'run-1',
          task_id: 'task-1',
          timestamp: new Date().toISOString(),
          event_type: 'task_status_changed',
          payload: {
            old_status: 'pending',
            new_status: 'building',
            agent_runner_type: 'openhands_local',
          },
        },
      ];

      renderCard({ events });
      // Component should render without errors
      expect(screen.getByText('Implement feature')).toBeInTheDocument();
    });

    it('component structure includes attempt summary data', () => {
      const attemptsSummary: AttemptOutcome[] = [
        { attempt_num: 1, outcome: 'pass' },
        { attempt_num: 2, outcome: 'revision' },
      ];

      renderCard({ attemptsSummary });
      // Multiple attempts should show count badge
      expect(screen.getByText('x2')).toBeInTheDocument();
    });
  });
});
