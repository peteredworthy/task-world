/**
 * State transition smoke tests for RunDetail.
 *
 * Tests verify:
 * - All pause_reason variants render the correct banner text
 * - manual_pause does NOT show a banner
 * - The "stopping" status hides Pause/Resume/Abort buttons
 * - Active run with a failed-at-max-attempts task shows the "Run blocked" warning
 * - A WS approval_requested event triggers a pending-actions refetch and shows the banner
 * - A pending action on load auto-opens the approval modal (autoOpenedRef behaviour)
 * - A second different pending action auto-opens after the first is dismissed
 *
 * Route strategy: page.route() intercepts all API calls (no real backend needed).
 * WebSocket: page.routeWebSocket() silently accepts the WS so the hook sees "connected"
 * without trying to reach a real server. The injection test captures the WS handle to
 * send synthetic frames.
 */
import { test, expect, type Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Shared fixture data
// ---------------------------------------------------------------------------

const RUN_ID = 'test-run-transitions';

const BASE_RUN = {
  id: RUN_ID,
  repo_name: 'test-org/test-repo',
  status: 'active',
  pause_reason: null,
  last_error: null,
  routine_id: null,
  routine_sha: null,
  routine_source: null,
  routine_embedded: { name: 'Test Routine', steps: [] },
  agent_runner_type: 'claude',
  agent_runner_type_display: 'Claude',
  agent_icon: 'claude',
  agent_runner_config: {},
  worktree_enabled: false,
  worktree_path: null,
  source_branch: 'main',
  merge_strategy: 'merge',
  config: {},
  env_file_specs: [],
  env_source_dir: null,
  steps: [] as unknown[],
  current_step_index: 0,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:01:00Z',
  started_at: '2026-01-01T00:00:00Z',
  completed_at: null,
  agent_runner_started_at: null,
  total_tokens_read: 0,
  total_tokens_write: 0,
  total_tokens_cache: 0,
  total_duration_ms: 0,
  total_num_actions: 0,
  token_usage_by_model: [],
  estimated_cost_usd: null,
  cost_disclaimer: null,
};

const STUCK_STEP = {
  id: 'step-1',
  config_id: 'step-1',
  title: 'Step 1',
  completed: false,
  has_approval_gate: false,
  approval_status: null,
  skipped: false,
  skip_reason: null,
  condition: null,
  tasks: [
    {
      id: 'task-stuck-1',
      config_id: 'failing-task',
      title: 'Implement feature',
      status: 'failed',
      current_attempt: 3,
      max_attempts: 3,
      grade_summary: [],
      attempts_summary: [],
      pending_action_type: null,
      pending_clarification_count: null,
      parent_task_id: null,
    },
  ],
};

const APPROVAL_ACTION_A = {
  task_id: 'task-1',
  step_id: 'step-1',
  action_type: 'approval',
  clarification_request: null,
  summary_artifact: null,
  approval_prompt: 'Please review and approve this change.',
  is_gate_approval: false,
};

const APPROVAL_ACTION_B = {
  task_id: 'task-2',
  step_id: 'step-1',
  action_type: 'approval',
  clarification_request: null,
  summary_artifact: null,
  approval_prompt: 'Please review the second change.',
  is_gate_approval: false,
};


// ---------------------------------------------------------------------------
// Route helpers
// ---------------------------------------------------------------------------

async function setupRoutes(
  page: Page,
  runOverride: Record<string, unknown> = {},
  pendingActions: unknown[] = [],
) {
  await page.route('**/health', (route) =>
    route.fulfill({ json: { status: 'ok' } }),
  );
  await page.route('**/api/config', (route) =>
    route.fulfill({ json: { auth_enabled: false, auth_token: null } }),
  );
  await page.route('**/api/agent-runners', (route) =>
    route.fulfill({ json: [] }),
  );

  await page.route(`**/api/runs/${RUN_ID}`, (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: { ...BASE_RUN, ...runOverride } });
    }
    return route.continue();
  });

  await page.route(`**/api/runs/${RUN_ID}/pending-actions**`, (route) =>
    route.fulfill({ json: pendingActions }),
  );

  await page.route(`**/api/runs/${RUN_ID}/activity**`, (route) =>
    route.fulfill({ json: { run_id: RUN_ID, events: [], has_more: false } }),
  );

  await page.route(`**/api/runs/${RUN_ID}/trace`, (route) =>
    route.fulfill({ json: { run_id: RUN_ID, attempts: [] } }),
  );

  await page.route(`**/api/runs/${RUN_ID}/branch-status`, (route) =>
    route.fulfill({
      json: {
        behind_count: 0,
        ahead_count: 0,
        can_merge_cleanly: true,
        has_conflicts: false,
        source_branch: 'main',
        run_branch: 'test',
        predicted_conflict_count: 0,
        merge_readiness: { status: 'ready', blocking_reasons: [] },
      },
    }),
  );

  // Review tab endpoints — minimal shapes to prevent rendering errors
  await page.route(`**/api/runs/${RUN_ID}/review/diff/files**`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/runs/${RUN_ID}/review/diff**`, (route) =>
    route.fulfill({ json: { diff: '', scope: 'aggregate', file_path: null } }),
  );
  await page.route(`**/api/runs/${RUN_ID}/review/commits**`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/runs/${RUN_ID}/review/conflicts**`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/runs/${RUN_ID}/review/merge-readiness**`, (route) =>
    route.fulfill({ json: { ready: true, gates: [] } }),
  );

  // Task detail endpoints — abort to prevent proxy errors
  await page.route(`**/api/runs/${RUN_ID}/tasks/**`, (route) => route.abort());

  await page.route(`**/api/runs/${RUN_ID}/guidance**`, (route) => route.abort());
  await page.route(`**/api/runs/${RUN_ID}/env-files**`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route('**/api/routines/**', (route) => route.abort());
}

/** Navigate and wait for the run header (routine name) to appear. */
async function openRunPage(page: Page) {
  await page.goto(`/runs/${RUN_ID}`);
  await expect(page.getByRole('heading', { name: 'Test Routine' })).toBeVisible({
    timeout: 15_000,
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('RunDetail — state transition smoke tests', () => {
  test.setTimeout(60_000);

  // ── Pause reason banner — render path smoke test ─────────────────────────
  // getPauseReasonMessage() is a pure function tested exhaustively in
  // tests/lib/pauseReason.test.ts. This single E2E test only verifies the
  // render path: that RunDetail actually passes pause_reason to the function
  // and renders the result to the DOM.

  test('paused_run_shows_pause_reason_banner', async ({ page }) => {
    await page.routeWebSocket(`**/ws/runs/${RUN_ID}`, () => {});

    await setupRoutes(page, { status: 'paused', pause_reason: 'gate_blocked' });
    await openRunPage(page);

    await expect(page.getByText('Paused — checklist gate not satisfied')).toBeVisible();
  });

  // manual_pause is the one case excluded from banner display — verify the
  // condition in RunDetail is wired correctly.
  test('paused_manual_pause_shows_no_banner', async ({ page }) => {
    await page.routeWebSocket(`**/ws/runs/${RUN_ID}`, () => {});

    await setupRoutes(page, { status: 'paused', pause_reason: 'manual_pause' });
    await openRunPage(page);

    await expect(page.getByText(/^Paused —/)).not.toBeVisible();
  });

  // ── Stopping state ───────────────────────────────────────────────────────

  test('stopping_state_has_no_pause_resume_abort_buttons', async ({ page }) => {
    await page.routeWebSocket(`**/ws/runs/${RUN_ID}`, () => {});

    await setupRoutes(page, { status: 'stopping' });
    await openRunPage(page);

    await expect(page.getByText('stopping')).toBeVisible();
    await expect(page.getByRole('button', { name: /pause/i })).not.toBeVisible();
    await expect(page.getByRole('button', { name: /resume/i })).not.toBeVisible();
    await expect(page.getByRole('button', { name: /abort/i })).not.toBeVisible();
  });

  // ── Stuck run warning ────────────────────────────────────────────────────

  test('stuck_run_shows_run_blocked_warning', async ({ page }) => {
    await page.routeWebSocket(`**/ws/runs/${RUN_ID}`, () => {});

    await setupRoutes(page, {
      status: 'active',
      steps: [STUCK_STEP],
    });
    await openRunPage(page);

    await expect(page.getByText('Run blocked')).toBeVisible();
    await expect(page.getByText(/failed after exhausting all attempts/)).toBeVisible();
    await expect(page.getByText('Implement feature')).toBeVisible();
  });

  // ── Active/paused button presence ────────────────────────────────────────

  test('active_run_shows_pause_button_not_resume', async ({ page }) => {
    await page.routeWebSocket(`**/ws/runs/${RUN_ID}`, () => {});

    await setupRoutes(page, { status: 'active' });
    await openRunPage(page);

    await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Resume' })).not.toBeVisible();
  });

  test('paused_run_shows_resume_button_not_pause', async ({ page }) => {
    await page.routeWebSocket(`**/ws/runs/${RUN_ID}`, () => {});

    await setupRoutes(page, { status: 'paused', pause_reason: 'manual_pause' });
    await openRunPage(page);

    await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Pause' })).not.toBeVisible();
  });

  // ── WS-driven pending-actions update ─────────────────────────────────────

  test('approval_requested_ws_event_shows_pending_actions_banner', async ({ page }) => {
    const state = { pendingActions: [] as unknown[] };

    let mockWs: Awaited<Parameters<Parameters<typeof page.routeWebSocket>[1]>[0]> | null = null;
    await page.routeWebSocket(`**/ws/runs/${RUN_ID}`, (ws) => {
      mockWs = ws;
    });

    await setupRoutes(page, { status: 'active' });

    // Override pending-actions with dynamic closure AFTER setupRoutes (LIFO priority)
    await page.route(`**/api/runs/${RUN_ID}/pending-actions**`, (route) =>
      route.fulfill({ json: state.pendingActions }),
    );

    await openRunPage(page);

    await expect.poll(() => mockWs !== null, { timeout: 5000 }).toBeTruthy();

    // No banner initially
    await expect(page.getByTestId('pending-actions-badge')).not.toBeVisible();

    // Update API state, then inject WS frame → queryClient.invalidateQueries → refetch
    state.pendingActions = [APPROVAL_ACTION_A];
    mockWs!.send(JSON.stringify({ event_type: 'approval_requested' }));

    // Banner appears after React Query refetches (data-testid set on the outer div)
    await expect(page.getByTestId('pending-actions-badge')).toBeVisible({ timeout: 3000 });
  });

  // ── Auto-open modal (autoOpenedRef behaviour) ─────────────────────────────

  test('pending_action_auto_opens_approval_modal_on_load', async ({ page }) => {
    await page.routeWebSocket(`**/ws/runs/${RUN_ID}`, () => {});

    await setupRoutes(page, { status: 'paused', pause_reason: 'waiting_for_approval' }, [
      APPROVAL_ACTION_A,
    ]);
    await openRunPage(page);

    await expect(page.getByRole('heading', { name: 'Approval Required' })).toBeVisible({
      timeout: 5000,
    });
  });

  test('second_pending_action_auto_opens_after_first_dismissed', async ({ page }) => {
    const state = { pendingActions: [APPROVAL_ACTION_A] as unknown[] };

    let mockWs: Awaited<Parameters<Parameters<typeof page.routeWebSocket>[1]>[0]> | null = null;
    await page.routeWebSocket(`**/ws/runs/${RUN_ID}`, (ws) => {
      mockWs = ws;
    });

    await setupRoutes(page, { status: 'active' });

    await page.route(`**/api/runs/${RUN_ID}/pending-actions**`, (route) =>
      route.fulfill({ json: state.pendingActions }),
    );

    await openRunPage(page);

    // First modal auto-opens
    await expect(page.getByRole('heading', { name: 'Approval Required' })).toBeVisible({
      timeout: 5000,
    });

    // Dismiss the first modal
    await page.getByRole('button', { name: 'Close' }).click();
    await expect(page.getByRole('heading', { name: 'Approval Required' })).not.toBeVisible();

    await expect.poll(() => mockWs !== null, { timeout: 5000 }).toBeTruthy();

    // Replace with a DIFFERENT pending action (different task_id)
    state.pendingActions = [APPROVAL_ACTION_B];
    mockWs!.send(JSON.stringify({ event_type: 'approval_requested' }));

    // autoOpenedRef key changes (task-2:approval ≠ task-1:approval) → modal auto-opens
    await expect(page.getByRole('heading', { name: 'Approval Required' })).toBeVisible({
      timeout: 5000,
    });
  });
});
