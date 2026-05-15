import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RunCard } from '../../src/components/dashboard/RunCard';
import type { RunResponse, TaskSummary, StepSummary } from '../../src/types';

afterEach(cleanup);

function makeTask(overrides: Partial<TaskSummary> & { id: string; config_id: string; status: TaskSummary['status'] }): TaskSummary {
  return {
    title: '',
    current_attempt: 1,
    max_attempts: 3,
    grade_summary: [],
    attempts_summary: [],
    ...overrides,
  };
}

function makeStep(overrides: Partial<StepSummary> & { id: string; config_id: string }): StepSummary {
  return {
    title: '',
    completed: false,
    tasks: [],
    ...overrides,
  };
}

function makeRun(overrides: Partial<RunResponse> = {}): RunResponse {
  return {
    id: 'run-1',
    repo_name: '/home/user/project',
    status: 'draft',
    pause_reason: null,
    routine_id: 'my-routine',
    routine_sha: null,
    routine_source: null,
    routine_embedded: null,
    agent_runner_type: null,
    agent_runner_type_display: 'No Agent Runner',
    agent_icon: 'none',
    agent_runner_config: {},
    worktree_enabled: false,
    worktree_path: null,
    source_branch: null,
    merge_strategy: null,
    config: {},
    steps: [],
    current_step_index: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    started_at: null,
    completed_at: null,
    agent_runner_started_at: null,
    total_tokens_read: 0,
    total_tokens_write: 0,
    total_tokens_cache: 0,
    total_duration_ms: 0,
    estimated_cost_usd: null,
    cost_disclaimer: null,
    ...overrides,
  };
}

const defaultHandlers = {
  onStart: vi.fn(),
  onPause: vi.fn(),
  onResume: vi.fn(),
  onCancel: vi.fn(),
  onDelete: vi.fn(),
  onToggle: vi.fn(),
};

function renderCard(run: RunResponse, props: Partial<Parameters<typeof RunCard>[0]> = {}) {
  const routineName = props.routineName ?? run.routine_id ?? 'Unknown routine';
  const expanded = props.expanded ?? false;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <RunCard run={run} routineName={routineName} expanded={expanded} {...defaultHandlers} {...props} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('RunCard', () => {
  it('renders routine name and repo_name', () => {
    const run = makeRun({ routine_id: 'test-routine', repo_name: '/tmp/proj' });
    renderCard(run, { routineName: 'Test Routine' });
    expect(screen.getByText('Test Routine')).toBeInTheDocument();
    expect(screen.getByText('/tmp/proj')).toBeInTheDocument();
  });

  it('renders expanded metadata strip with labeled details and metrics', () => {
    const run = makeRun({
      status: 'active',
      source_branch: 'mcp-ops-c',
      agent_runner_type_display: 'Codex Server',
      agent_icon: 'codex',
      started_at: '2026-03-03T12:00:00Z',
      total_tokens_read: 1200,
      total_tokens_write: 300,
      total_tokens_cache: 500,
      estimated_cost_usd: 0.012,
    });

    renderCard(run, { expanded: true, routineName: 'Test Routine' });

    expect(screen.getByText('Run ID')).toBeInTheDocument();
    expect(screen.getByText('Source Branch')).toBeInTheDocument();
    expect(screen.getByText('Agent Runner')).toBeInTheDocument();
    expect(screen.getByText('Started')).toBeInTheDocument();
    expect(screen.getByText('Total Tokens')).toBeInTheDocument();
    expect(screen.getByText('Est. Cost')).toBeInTheDocument();
    expect(screen.getByText('2.0k')).toBeInTheDocument();
    expect(screen.getByText('$0.01')).toBeInTheDocument();
  });

  it('renders status badge', () => {
    const run = makeRun({ status: 'active' });
    renderCard(run);
    expect(screen.getByText('active')).toBeInTheDocument();
  });

  it('does not show Start button for draft status in collapsed bar', () => {
    const run = makeRun({ status: 'draft' });
    renderCard(run);
    expect(screen.queryByText('Start')).not.toBeInTheDocument();
  });

  it('shows Start button for draft status in expanded footer', () => {
    const run = makeRun({ status: 'draft' });
    renderCard(run, { expanded: true });
    expect(screen.getByText('Start')).toBeInTheDocument();
  });

  it('calls onStart when Start button is clicked', async () => {
    const onStart = vi.fn();
    const run = makeRun({ status: 'draft', id: 'run-42' });
    renderCard(run, { onStart, expanded: true });
    await userEvent.click(screen.getByText('Start'));
    expect(onStart).toHaveBeenCalledWith('run-42');
  });

  it('shows Pause button for active status', () => {
    const run = makeRun({ status: 'active' });
    renderCard(run);
    expect(screen.getByText('Pause')).toBeInTheDocument();
  });

  it('does not show Abort Run button for active status in collapsed bar', () => {
    const run = makeRun({ status: 'active' });
    renderCard(run);
    expect(screen.queryByText('Abort Run')).not.toBeInTheDocument();
  });

  it('shows Abort Run button for active status in expanded footer', () => {
    const run = makeRun({ status: 'active' });
    renderCard(run, { expanded: true });
    expect(screen.getByText('Abort Run')).toBeInTheDocument();
  });

  it('calls onPause when Pause button is clicked', async () => {
    const onPause = vi.fn();
    const run = makeRun({ status: 'active', id: 'run-42' });
    renderCard(run, { onPause });
    await userEvent.click(screen.getByText('Pause'));
    expect(onPause).toHaveBeenCalledWith('run-42');
  });

  it('shows Resume button for paused status', () => {
    const run = makeRun({ status: 'paused' });
    renderCard(run);
    expect(screen.getByText('Resume')).toBeInTheDocument();
  });

  it('calls onResume when Resume button is clicked', async () => {
    const onResume = vi.fn();
    const run = makeRun({ status: 'paused', id: 'run-42' });
    renderCard(run, { onResume });
    await userEvent.click(screen.getByText('Resume'));
    expect(onResume).toHaveBeenCalledWith('run-42');
  });

  it('does not show Abort Run button for paused status in collapsed bar', () => {
    const run = makeRun({ status: 'paused' });
    renderCard(run);
    expect(screen.queryByText('Abort Run')).not.toBeInTheDocument();
  });

  it('shows Abort Run button for paused status in expanded footer', () => {
    const run = makeRun({ status: 'paused' });
    renderCard(run, { expanded: true });
    expect(screen.getByText('Abort Run')).toBeInTheDocument();
  });

  it('calls onCancel when Abort Run is clicked for paused status in expanded footer', async () => {
    const onCancel = vi.fn();
    const run = makeRun({ status: 'paused', id: 'run-42' });
    renderCard(run, { onCancel, expanded: true });
    await userEvent.click(screen.getByText('Abort Run'));
    expect(onCancel).toHaveBeenCalledWith('run-42');
  });

  it('does not show Abort Run button for failed status', () => {
    const run = makeRun({ status: 'failed' });
    renderCard(run);
    expect(screen.queryByText('Abort Run')).not.toBeInTheDocument();
  });

  it('does not show Delete button for draft status in collapsed bar', () => {
    const run = makeRun({ status: 'draft' });
    renderCard(run);
    expect(screen.queryByText('Delete')).not.toBeInTheDocument();
  });

  it('shows Delete button for draft status in expanded footer', () => {
    const run = makeRun({ status: 'draft' });
    renderCard(run, { expanded: true });
    expect(screen.getByText('Delete')).toBeInTheDocument();
  });

  it('does not show Delete button for completed status in collapsed bar', () => {
    const run = makeRun({ status: 'completed' });
    renderCard(run);
    expect(screen.queryByText('Delete')).not.toBeInTheDocument();
  });

  it('shows Delete button for completed status in expanded footer', () => {
    const run = makeRun({ status: 'completed' });
    renderCard(run, { expanded: true });
    expect(screen.getByText('Delete')).toBeInTheDocument();
  });

  it('shows Delete button for failed status', () => {
    const run = makeRun({ status: 'failed' });
    renderCard(run);
    expect(screen.getByText('Delete')).toBeInTheDocument();
  });

  it('calls onDelete when Delete button is clicked in expanded footer', async () => {
    const onDelete = vi.fn();
    const run = makeRun({ status: 'draft', id: 'run-42' });
    renderCard(run, { onDelete, expanded: true });
    await userEvent.click(screen.getByText('Delete'));
    expect(onDelete).toHaveBeenCalledWith('run-42');
  });

  it('does not show Delete button for active status', () => {
    const run = makeRun({ status: 'active' });
    renderCard(run);
    expect(screen.queryByText('Delete')).not.toBeInTheDocument();
  });

  it('does not show Delete button for paused status', () => {
    const run = makeRun({ status: 'paused' });
    renderCard(run);
    expect(screen.queryByText('Delete')).not.toBeInTheDocument();
  });

  it('expand/collapse toggle works', async () => {
    const onToggle = vi.fn();
    const run = makeRun({
      status: 'paused',
      steps: [
        makeStep({
          id: 's1',
          config_id: 'setup',
          title: 'setup',
          tasks: [
            makeTask({ id: 't1', config_id: 'tc1', status: 'building', title: 'tc1' }),
          ],
        }),
      ],
    });

    // Render collapsed
    const { rerender } = renderCard(run, { onToggle, expanded: false });

    // Click expand
    const expandBtn = screen.getByRole('button', { name: /Expand run/ });
    await userEvent.click(expandBtn);
    expect(onToggle).toHaveBeenCalled();

    // Re-render expanded
    rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
        <MemoryRouter>
          <RunCard run={run} routineName={run.routine_id!} expanded={true} onToggle={onToggle} onStart={defaultHandlers.onStart} onPause={defaultHandlers.onPause} onResume={defaultHandlers.onResume} onCancel={defaultHandlers.onCancel} onDelete={defaultHandlers.onDelete} />
        </MemoryRouter>
      </QueryClientProvider>
    );

    // Step detail should be visible
    expect(screen.getByText('setup')).toBeInTheDocument();

    // Click collapse
    const collapseBtn = screen.getByRole('button', { name: /Collapse run/ });
    await userEvent.click(collapseBtn);
    expect(onToggle).toHaveBeenCalledTimes(2);
  });

  it('shows "Starting..." when start loading state is true', () => {
    const run = makeRun({ status: 'draft' });
    renderCard(run, { expanded: true, loading: { start: true } });
    expect(screen.getByText('Starting...')).toBeInTheDocument();
    expect(screen.queryByText('Start')).not.toBeInTheDocument();
  });

  it('shows "Pausing..." when pause loading state is true', () => {
    const run = makeRun({ status: 'active' });
    renderCard(run, { loading: { pause: true } });
    expect(screen.getByText('Pausing...')).toBeInTheDocument();
    expect(screen.queryByText('Pause')).not.toBeInTheDocument();
  });

  it('shows "Resuming..." when resume loading state is true', () => {
    const run = makeRun({ status: 'paused' });
    renderCard(run, { loading: { resume: true } });
    expect(screen.getByText('Resuming...')).toBeInTheDocument();
    expect(screen.queryByText('Resume')).not.toBeInTheDocument();
  });

  it('shows "Deleting..." when delete loading state is true', () => {
    const run = makeRun({ status: 'draft' });
    renderCard(run, { expanded: true, loading: { delete: true } });
    expect(screen.getByText('Deleting...')).toBeInTheDocument();
    expect(screen.queryByText('Delete')).not.toBeInTheDocument();
  });

  it('renders routine_id in meta when routine_id is not null', () => {
    const run = makeRun({ routine_id: 'my-routine' });
    renderCard(run, { routineName: 'My Routine Display Name' });
    // routine_id appears in the meta line, separate from the display name
    expect(screen.getByText('my-routine')).toBeInTheDocument();
    expect(screen.getByText('My Routine Display Name')).toBeInTheDocument();
  });

  describe('agent display', () => {
    it('renders agent runner icon and name when agent is set in expanded view', () => {
      const run = makeRun({
        agent_runner_type: 'openhands_local',
        agent_runner_type_display: 'OpenHands',
        agent_icon: 'openhands',
      });
      renderCard(run, { expanded: true });

      expect(screen.getByText('OpenHands')).toBeInTheDocument();
      expect(screen.getByText('Agent Runner')).toBeInTheDocument();
    });

    it('renders CLI agent runner icon and name', () => {
      const run = makeRun({
        agent_runner_type: 'cli_subprocess',
        agent_runner_type_display: 'CLI Agent',
        agent_icon: 'cli',
      });
      renderCard(run, { expanded: true });
      expect(screen.getByText('CLI Agent')).toBeInTheDocument();
    });

    it('renders Docker agent runner icon and name', () => {
      const run = makeRun({
        agent_runner_type: 'openhands_docker',
        agent_runner_type_display: 'OpenHands Docker',
        agent_icon: 'docker',
      });
      renderCard(run, { expanded: true });
      expect(screen.getByText('OpenHands Docker')).toBeInTheDocument();
    });

    it('renders external agent runner icon and name', () => {
      const run = makeRun({
        agent_runner_type: 'cli_subprocess',
        agent_runner_type_display: 'CLI subprocess',
        agent_icon: 'external',
      });
      renderCard(run, { expanded: true });
      expect(screen.getByText('CLI subprocess')).toBeInTheDocument();
    });

    it('shows fallback agent text when agent_icon is none', () => {
      const run = makeRun({
        agent_runner_type: null,
        agent_runner_type_display: 'No Agent Runner',
        agent_icon: 'none',
      });
      renderCard(run, { expanded: true });

      expect(screen.getByText('No Agent Runner')).toBeInTheDocument();
    });

    it('shows agent runner info in the expanded details strip', () => {
      const run = makeRun({
        agent_runner_type: 'openhands_local',
        agent_runner_type_display: 'OpenHands',
        agent_icon: 'openhands',
        routine_id: 'my-routine',
      });
      renderCard(run, { expanded: true });

      expect(screen.getByText('Agent Runner')).toBeInTheDocument();
      expect(screen.getByText('OpenHands')).toBeInTheDocument();
    });

    it('shows agent runner info in collapsed view too', () => {
      const run = makeRun({
        agent_runner_type: 'openhands_local',
        agent_runner_type_display: 'OpenHands',
        agent_icon: 'openhands',
      });
      renderCard(run, { expanded: false });

      // Agent info is shown in meta line even when collapsed
      expect(screen.getByText('OpenHands')).toBeInTheDocument();
    });
  });

  describe('onTaskClick', () => {
    const runWithTasks = () =>
      makeRun({
        id: 'run-99',
        status: 'active',
        steps: [
          makeStep({
            id: 's1',
            config_id: 'setup',
            title: 'Setup',
            tasks: [
              makeTask({ id: 't1', config_id: 'tc1', status: 'building', title: 'Build widgets' }),
              makeTask({ id: 't2', config_id: 'tc2', status: 'pending', title: 'Verify widgets' }),
            ],
          }),
        ],
      });

    it('calls onTaskClick with runId and task when a task card is clicked', async () => {
      const onTaskClick = vi.fn();
      const run = runWithTasks();
      renderCard(run, { expanded: true, onTaskClick });

      // Task cards should have role="button" when onTaskClick is provided
      const taskButtons = screen.getAllByRole('button').filter(
        btn => btn.textContent?.includes('Build widgets') || btn.textContent?.includes('Verify widgets')
      );
      expect(taskButtons.length).toBeGreaterThan(0);

      // Click the first task
      await userEvent.click(taskButtons[0]);

      expect(onTaskClick).toHaveBeenCalledTimes(1);
      expect(onTaskClick).toHaveBeenCalledWith('run-99', run.steps[0].tasks[0]);
    });

    it('does not render task cards as buttons when onTaskClick is not provided', () => {
      const run = runWithTasks();
      renderCard(run, { expanded: true });

      // Task text should be visible but not in a button role
      expect(screen.getByText('Build widgets')).toBeInTheDocument();
      expect(screen.getByText('Verify widgets')).toBeInTheDocument();

      // No element with role="button" should contain the task title text
      // (there will be other buttons like Pause, Collapse, Abort, etc.)
      const allButtons = screen.getAllByRole('button');
      const taskButtons = allButtons.filter(
        btn => btn.textContent?.includes('Build widgets') || btn.textContent?.includes('Verify widgets')
      );
      expect(taskButtons).toHaveLength(0);
    });

    it('task click does not trigger onToggle', async () => {
      const onTaskClick = vi.fn();
      const onToggle = vi.fn();
      const run = runWithTasks();
      renderCard(run, { expanded: true, onTaskClick, onToggle });

      // Find the task button
      const taskButtons = screen.getAllByRole('button').filter(
        btn => btn.textContent?.includes('Build widgets')
      );
      expect(taskButtons).toHaveLength(1);

      await userEvent.click(taskButtons[0]);

      // onTaskClick should have been called
      expect(onTaskClick).toHaveBeenCalledTimes(1);

      // onToggle should NOT have been called (stopPropagation prevents bubbling)
      expect(onToggle).not.toHaveBeenCalled();
    });
  });

  it('shows approval CTA in expanded view when current step is awaiting gate approval', () => {
    const run = makeRun({
      status: 'active',
      steps: [
        makeStep({
          id: 's1',
          config_id: 'final-review',
          has_approval_gate: true,
          approval_status: 'pending',
          tasks: [
            makeTask({
              id: 't-approval',
              config_id: 'approval-task',
              status: 'pending',
              pending_action_type: null,
            }),
          ],
        }),
      ],
    });

    renderCard(run, { expanded: true });
    expect(screen.getByText('Review Approval')).toBeInTheDocument();
  });

  it('shows pending badge in collapsed view for step approval gate even without task-level pending action', () => {
    const run = makeRun({
      status: 'active',
      steps: [
        makeStep({
          id: 's1',
          config_id: 'final-review',
          has_approval_gate: true,
          approval_status: 'pending',
          tasks: [
            makeTask({
              id: 't-approval',
              config_id: 'approval-task',
              status: 'pending',
              pending_action_type: null,
            }),
          ],
        }),
      ],
    });

    renderCard(run, { expanded: false });
    expect(screen.getByRole('button', { name: /1 pending action - open now/i })).toBeInTheDocument();
  });

  describe('task action menu', () => {
    it('shows always-visible task actions button for revertable tasks and toggles menu', async () => {
      const run = makeRun({
        id: 'run-menu',
        status: 'active',
        current_step_index: 1,
        steps: [
          makeStep({
            id: 's1',
            config_id: 'step-one',
            title: 'Step one',
            completed: true,
            tasks: [
              makeTask({ id: 't1', config_id: 'task-one', status: 'completed', title: 'Completed task' }),
            ],
          }),
          makeStep({
            id: 's2',
            config_id: 'step-two',
            title: 'Step two',
            completed: false,
            tasks: [
              makeTask({ id: 't2', config_id: 'task-two', status: 'building', title: 'Current task' }),
            ],
          }),
        ],
      });

      renderCard(run, { expanded: true });

      const actionButtons = screen.getAllByRole('button', { name: 'Task actions' });
      expect(actionButtons).toHaveLength(1);

      await userEvent.click(actionButtons[0]);
      expect(screen.getByRole('button', { name: 'Revert to this step' })).toBeInTheDocument();

      await userEvent.keyboard('{Escape}');
      expect(screen.queryByRole('button', { name: 'Revert to this step' })).not.toBeInTheDocument();
    });

    it('shows task actions for a completed current (final) step', () => {
      const run = makeRun({
        id: 'run-final-step',
        status: 'completed',
        current_step_index: 1,
        steps: [
          makeStep({
            id: 's1',
            config_id: 'step-one',
            title: 'Step one',
            completed: true,
            tasks: [
              makeTask({ id: 't1', config_id: 'task-one', status: 'completed', title: 'Completed task 1' }),
            ],
          }),
          makeStep({
            id: 's2',
            config_id: 'step-two',
            title: 'Step two',
            completed: true,
            tasks: [
              makeTask({ id: 't2', config_id: 'task-two', status: 'completed', title: 'Completed final task' }),
            ],
          }),
        ],
      });

      renderCard(run, { expanded: true });

      // One action button per completed step, including current/final completed step.
      const actionButtons = screen.getAllByRole('button', { name: 'Task actions' });
      expect(actionButtons).toHaveLength(2);
    });
  });
});
