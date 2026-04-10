import { describe, it, expect } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RecoveryPanel } from '../RecoveryPanel';
import type { RunResponse } from '../../../../types';
import { afterEach } from 'vitest';

afterEach(cleanup);

function makeRun(status: RunResponse['status']): RunResponse {
  const taskWithTimeline = {
    id: 'task-1',
    config_id: 'task_cfg',
    title: 'Build API',
    status: 'failed',
    current_attempt: 1,
    max_attempts: 3,
    grade_summary: [],
    attempts_summary: [{ attempt_num: 1, outcome: 'failed' }],
    pending_action_type: null,
    pending_clarification_count: null,
    end_commit: 'commit-sha-placeholder',
  } as unknown as RunResponse['steps'][number]['tasks'][number];

  return {
    id: 'run-1',
    repo_name: 'repo',
    status,
    routine_id: 'routine-1',
    routine_sha: 'sha',
    routine_source: 'git',
    routine_embedded: null,
    agent_type: null,
    agent_type_display: 'None',
    agent_icon: 'bot',
    agent_config: {},
    worktree_enabled: true,
    worktree_path: '/tmp/worktree',
    source_branch: 'main',
    merge_strategy: null,
    config: {},
    env_file_specs: [],
    env_source_dir: null,
    steps: [
      {
        id: 'step-1',
        config_id: 'step_cfg',
        title: 'Step One',
        completed: false,
        has_approval_gate: false,
        approval_status: null,
        tasks: [
          taskWithTimeline,
        ],
      },
    ],
    current_step_index: 0,
    created_at: '2026-02-19T00:00:00Z',
    updated_at: '2026-02-19T00:00:00Z',
    started_at: '2026-02-19T00:00:00Z',
    completed_at: null,
    agent_started_at: null,
    total_tokens_read: 0,
    total_tokens_write: 0,
    total_tokens_cache: 0,
    total_duration_ms: 0,
    estimated_cost_usd: null,
    cost_disclaimer: null,
  };
}

function renderPanel(run: RunResponse) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <RecoveryPanel run={run} />
    </QueryClientProvider>,
  );
}

describe('RecoveryPanel', () => {
  it('renders task timeline for FAILED run', () => {
    renderPanel(makeRun('failed'));

    expect(screen.getByText('Recovery')).toBeInTheDocument();
    expect(screen.getByText('end_commit: commit-sha-p')).toBeInTheDocument();
  });

  it('opens confirmation dialog on task click', async () => {
    renderPanel(makeRun('failed'));

    await userEvent.click(screen.getByRole('button', { name: /Recover to task Build API/i }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Confirm recovery')).toBeInTheDocument();
    expect(screen.getByText(/Selected task:/i)).toBeInTheDocument();
    expect(screen.getByText('Build API')).toBeInTheDocument();
    expect(screen.getByText('All downstream tasks will be reset to PENDING.')).toBeInTheDocument();
  });
});
