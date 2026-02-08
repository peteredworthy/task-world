import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
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
    routine_id: 'my-routine',
    routine_sha: null,
    routine_source: null,
    routine_embedded: null,
    agent_type: null,
    agent_type_display: 'No Agent',
    agent_icon: 'none',
    agent_config: {},
    worktree_enabled: false,
    worktree_path: null,
    config: {},
    steps: [],
    current_step_index: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    started_at: null,
    completed_at: null,
    agent_started_at: null,
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
  onDelete: vi.fn(),
  onToggle: vi.fn(),
};

function renderCard(run: RunResponse, props: Partial<Parameters<typeof RunCard>[0]> = {}) {
  const routineName = props.routineName ?? run.routine_id ?? 'Unknown routine';
  const expanded = props.expanded ?? false;
  return render(
    <MemoryRouter>
      <RunCard run={run} routineName={routineName} expanded={expanded} {...defaultHandlers} {...props} />
    </MemoryRouter>
  );
}

describe('RunCard', () => {
  it('renders routine name and repo_name', () => {
    const run = makeRun({ routine_id: 'test-routine', repo_name: '/tmp/proj' });
    renderCard(run, { routineName: 'Test Routine' });
    expect(screen.getByText('Test Routine')).toBeInTheDocument();
    expect(screen.getByText('/tmp/proj')).toBeInTheDocument();
  });

  it('renders status badge', () => {
    const run = makeRun({ status: 'active' });
    renderCard(run);
    expect(screen.getByText('active')).toBeInTheDocument();
  });

  it('shows Start button for draft status', () => {
    const run = makeRun({ status: 'draft' });
    renderCard(run);
    expect(screen.getByText('Start')).toBeInTheDocument();
  });

  it('calls onStart when Start button is clicked', async () => {
    const onStart = vi.fn();
    const run = makeRun({ status: 'draft', id: 'run-42' });
    renderCard(run, { onStart });
    await userEvent.click(screen.getByText('Start'));
    expect(onStart).toHaveBeenCalledWith('run-42');
  });

  it('shows Pause button for active status', () => {
    const run = makeRun({ status: 'active' });
    renderCard(run);
    expect(screen.getByText('Pause')).toBeInTheDocument();
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

  it('shows Delete button for draft status', () => {
    const run = makeRun({ status: 'draft' });
    renderCard(run);
    expect(screen.getByText('Delete')).toBeInTheDocument();
  });

  it('shows Delete button for completed status', () => {
    const run = makeRun({ status: 'completed' });
    renderCard(run);
    expect(screen.getByText('Delete')).toBeInTheDocument();
  });

  it('shows Delete button for failed status', () => {
    const run = makeRun({ status: 'failed' });
    renderCard(run);
    expect(screen.getByText('Delete')).toBeInTheDocument();
  });

  it('calls onDelete when Delete button is clicked', async () => {
    const onDelete = vi.fn();
    const run = makeRun({ status: 'draft', id: 'run-42' });
    renderCard(run, { onDelete });
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
      <MemoryRouter>
        <RunCard run={run} routineName={run.routine_id!} expanded={true} onToggle={onToggle} onStart={defaultHandlers.onStart} onPause={defaultHandlers.onPause} onResume={defaultHandlers.onResume} onDelete={defaultHandlers.onDelete} />
      </MemoryRouter>
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
    renderCard(run, { loading: { start: true } });
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
    renderCard(run, { loading: { delete: true } });
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
    it('renders agent icon and name when agent is set in expanded view', () => {
      const run = makeRun({
        agent_type: 'openhands_local',
        agent_type_display: 'OpenHands',
        agent_icon: 'openhands',
      });
      renderCard(run, { expanded: true });

      expect(screen.getByText('OpenHands')).toBeInTheDocument();

      // AgentIcon should be rendered (check for svg)
      const container = screen.getByText('OpenHands').closest('span');
      expect(container).toBeInTheDocument();
    });

    it('renders CLI agent icon and name', () => {
      const run = makeRun({
        agent_type: 'cli_subprocess',
        agent_type_display: 'CLI Agent',
        agent_icon: 'cli',
      });
      renderCard(run, { expanded: true });
      expect(screen.getByText('CLI Agent')).toBeInTheDocument();
    });

    it('renders Docker agent icon and name', () => {
      const run = makeRun({
        agent_type: 'openhands_docker',
        agent_type_display: 'OpenHands Docker',
        agent_icon: 'docker',
      });
      renderCard(run, { expanded: true });
      expect(screen.getByText('OpenHands Docker')).toBeInTheDocument();
    });

    it('renders external agent icon and name', () => {
      const run = makeRun({
        agent_type: 'user_managed',
        agent_type_display: 'User Managed',
        agent_icon: 'external',
      });
      renderCard(run, { expanded: true });
      expect(screen.getByText('User Managed')).toBeInTheDocument();
    });

    it('hides agent info when agent_icon is none', () => {
      const run = makeRun({
        agent_type: null,
        agent_type_display: 'No Agent',
        agent_icon: 'none',
      });
      renderCard(run, { expanded: true });

      // Agent display text should not be in the expanded meta section
      expect(screen.queryByText('No Agent')).not.toBeInTheDocument();
    });

    it('shows agent info with separator pipe in expanded view', () => {
      const run = makeRun({
        agent_type: 'openhands_local',
        agent_type_display: 'OpenHands',
        agent_icon: 'openhands',
        routine_id: 'my-routine',
      });
      const { container } = renderCard(run, { expanded: true });

      // Should have pipe separator before agent info
      const metaSection = container.querySelector('.font-mono');
      expect(metaSection?.textContent).toContain('|');
      expect(metaSection?.textContent).toContain('OpenHands');
    });

    it('shows agent info in collapsed view too', () => {
      const run = makeRun({
        agent_type: 'openhands_local',
        agent_type_display: 'OpenHands',
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
});
