/**
 * Visual regression tests for the Review & Merge workbench.
 *
 * Each test navigates to the review tab with pre-configured API route mocks
 * and captures a screenshot baseline with expect(page).toHaveScreenshot().
 *
 * On the first run these create the baseline snapshots stored under
 *   tests/e2e/__snapshots__/
 * Subsequent runs compare against those baselines.
 *
 * 8 snapshots captured:
 *   1. visual_review_tab_clean      – review tab with no file changes
 *   2. visual_review_tab_file_list  – review tab with a populated file list
 *   3. visual_diff_dialog_inline    – diff dialog in unified (inline) mode
 *   4. visual_diff_dialog_split     – diff dialog in split mode
 *   5. visual_prune_mode_active     – prune toolbar visible
 *   6. visual_conflict_resolver     – conflict resolver dialog open
 *   7. visual_merge_readiness_ready – readiness bar with all gates passing
 *   8. visual_merge_readiness_blocked – readiness bar with failing gates
 */

import { test, expect, type Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Fixture data
// ---------------------------------------------------------------------------

const RUN_ID = 'test-run-visual';

const MOCK_RUN = {
  id: RUN_ID,
  repo_name: 'test-org/test-repo',
  status: 'active',
  routine_id: null,
  routine_sha: null,
  routine_source: null,
  routine_embedded: { name: 'Test Routine', steps: [] },
  agent_type: 'claude',
  agent_type_display: 'Claude',
  agent_icon: 'claude',
  agent_config: {},
  worktree_enabled: true,
  worktree_path: '/tmp/test-worktree',
  source_branch: 'main',
  merge_strategy: 'merge',
  config: {},
  env_file_specs: [],
  env_source_dir: null,
  steps: [],
  current_step_index: 0,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:01:00Z',
  started_at: '2026-01-01T00:00:00Z',
  completed_at: null,
  agent_started_at: null,
  total_tokens_read: 1234,
  total_tokens_write: 567,
  total_tokens_cache: 89,
  total_duration_ms: 45000,
  estimated_cost_usd: 0.012,
  cost_disclaimer: null,
};

const MOCK_BRANCH_STATUS = {
  behind_count: 0,
  ahead_count: 3,
  can_merge_cleanly: true,
  has_conflicts: false,
  source_branch: 'main',
  run_branch: 'orchestrator/run-test-visual',
  predicted_conflict_count: 0,
  merge_readiness: { status: 'ready', blocking_reasons: [] },
};

const MOCK_FILES = [
  { path: 'src/orchestrator/core.py', status: 'modified', additions: 25, deletions: 8 },
  { path: 'tests/test_core.py', status: 'added', additions: 47, deletions: 0 },
  { path: 'docs/README.md', status: 'modified', additions: 5, deletions: 2 },
  { path: 'src/utils/helpers.py', status: 'deleted', additions: 0, deletions: 14 },
];

// A valid unified diff that react-diff-view can parse.
// @@ -1,4 +1,5 @@ means: old hunk starts at line 1 with 4 lines; new hunk starts at line 1 with 5 lines.
const MOCK_DIFF = `\
diff --git a/src/orchestrator/core.py b/src/orchestrator/core.py
index abc1234..def5678 100644
--- a/src/orchestrator/core.py
+++ b/src/orchestrator/core.py
@@ -1,4 +1,5 @@
 import os
+import sys

 def main():
-    print("Hello, World!")
+    print("Hello, orchestrator!")
`;

const MOCK_COMMITS = [
  {
    sha: 'abc123400000000',
    short_sha: 'abc1234',
    message: 'Add core orchestration logic',
    author: 'Test User',
    timestamp: '2026-01-01T00:00:00Z',
  },
  {
    sha: 'def567800000000',
    short_sha: 'def5678',
    message: 'Add test coverage',
    author: 'Test User',
    timestamp: '2026-01-01T00:01:00Z',
  },
];

const MOCK_READINESS_READY = {
  ready: true,
  gates: [
    { name: 'no_conflicts', description: 'No merge conflicts', status: 'pass' },
    { name: 'tests_pass', description: 'Tests pass', status: 'pass' },
    { name: 'changes_reviewed', description: 'Changes reviewed', status: 'pass' },
  ],
};

const MOCK_READINESS_BLOCKED = {
  ready: false,
  gates: [
    { name: 'no_conflicts', description: 'No merge conflicts', status: 'pass' },
    { name: 'tests_pass', description: 'Tests pass', status: 'fail' },
    { name: 'changes_reviewed', description: 'Changes reviewed', status: 'pending' },
  ],
};

const MOCK_CONFLICTS = [
  {
    path: 'src/orchestrator/core.py',
    status: 'unresolved',
    block_count: 2,
    blocks: [
      {
        index: 0,
        ours_content: 'def hello():\n    return "ours version"',
        theirs_content: 'def hello():\n    return "theirs version"',
        base_content: null,
      },
      {
        index: 1,
        ours_content: 'VERSION = "1.0.0"',
        theirs_content: 'VERSION = "2.0.0"',
        base_content: null,
      },
    ],
  },
  {
    path: 'tests/test_core.py',
    status: 'unresolved',
    block_count: 1,
    blocks: [
      {
        index: 0,
        ours_content: 'def test_hello():\n    assert hello() == "ours version"',
        theirs_content: 'def test_hello():\n    assert hello() == "theirs version"',
        base_content: null,
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Route setup helpers
// ---------------------------------------------------------------------------

interface RouteOverrides {
  files?: unknown[];
  conflicts?: unknown[];
  readiness?: unknown;
}

/**
 * Install page.route() intercepts for all API calls used by the review tab.
 * Individual tests can override specific responses via the `overrides` param.
 *
 * Key: pending-actions MUST return a plain array [], not a wrapped object — the
 *      hook calls .find() on the result during render and crashes otherwise.
 */
async function setupRoutes(page: Page, overrides: RouteOverrides = {}) {
  // Health check — ConnectionBanner polls this; return OK to suppress the banner.
  await page.route('**/health', (route) =>
    route.fulfill({ json: { status: 'ok' } }),
  );

  // App config
  await page.route('**/api/config', (route) =>
    route.fulfill({ json: { auth_enabled: false, auth_token: null } }),
  );

  // Sidebar quota polling; not relevant to the review workbench.
  await page.route('**/api/agent-runners', (route) =>
    route.fulfill({ json: [] }),
  );

  // Run detail (polled by RunDetail)
  await page.route(`**/api/runs/${RUN_ID}`, (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: MOCK_RUN });
    }
    return route.continue();
  });

  // Activity feed — must match ActivityResponse shape { run_id, events, has_more }
  await page.route(`**/api/runs/${RUN_ID}/activity**`, (route) =>
    route.fulfill({
      json: { run_id: RUN_ID, events: [], has_more: false },
    }),
  );

  // Pending actions — MUST be a plain array (PendingAction[]), not an object.
  // RunDetail calls .find() on this directly during render.
  await page.route(`**/api/runs/${RUN_ID}/pending-actions**`, (route) =>
    route.fulfill({ json: [] }),
  );

  // Branch status (used by BranchStatusSection and BackMergeModal)
  await page.route(`**/api/runs/${RUN_ID}/branch-status`, (route) =>
    route.fulfill({ json: MOCK_BRANCH_STATUS }),
  );

  // Diff content (used by DiffDialog) — registered first so the more-specific
  // diff/files route (registered next) takes precedence for file-list requests.
  await page.route(`**/api/runs/${RUN_ID}/review/diff**`, (route) =>
    route.fulfill({
      json: { diff: MOCK_DIFF, scope: 'aggregate', file_path: null },
    }),
  );

  // Diff file list — registered AFTER the general diff route so Playwright's
  // LIFO ordering gives it higher priority for /review/diff/files requests.
  await page.route(`**/api/runs/${RUN_ID}/review/diff/files**`, (route) =>
    route.fulfill({ json: overrides.files ?? MOCK_FILES }),
  );

  // Commit list (used by HistoryPanel and DiffDialog commit scope)
  await page.route(`**/api/runs/${RUN_ID}/review/commits**`, (route) =>
    route.fulfill({ json: MOCK_COMMITS }),
  );

  // Conflicts
  await page.route(`**/api/runs/${RUN_ID}/review/conflicts**`, (route) =>
    route.fulfill({ json: overrides.conflicts ?? [] }),
  );

  // Merge readiness bar
  await page.route(`**/api/runs/${RUN_ID}/review/merge-readiness**`, (route) =>
    route.fulfill({ json: overrides.readiness ?? MOCK_READINESS_READY }),
  );

  // Guidance / env files / routines — not needed for the review tab
  await page.route(`**/api/runs/${RUN_ID}/guidance**`, (route) => route.abort());
  await page.route(`**/api/runs/${RUN_ID}/env-files**`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route('**/api/routines/**', (route) => route.abort());
}

/**
 * Navigate to the run detail page and wait for the Review & Merge workbench.
 */
async function openReviewTab(page: Page) {
  await page.goto(`/runs/${RUN_ID}`);

  // Wait for at least one review panel to become visible.
  // Use .first() to avoid strict-mode failure when both headings render together.
  await expect(
    page.getByText('Branch Status').or(page.getByText('Modified Files')).first(),
  ).toBeVisible({ timeout: 15_000 });
}

function coreFileEntry(page: Page) {
  return page.getByTitle('src/orchestrator/core.py').first();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Review & Merge workbench – visual regression', () => {
  // Increase timeout per test since we start a dev server and navigate the app
  test.setTimeout(60_000);

  /**
   * 1. Clean review tab — no file changes, empty file list state
   */
  test('visual_review_tab_clean', async ({ page }) => {
    await setupRoutes(page, { files: [], conflicts: [], readiness: MOCK_READINESS_READY });
    await openReviewTab(page);

    // Wait for the "Nothing to review" empty-state text to appear
    await expect(page.getByText('Nothing to review')).toBeVisible();

    await expect(page).toHaveScreenshot('visual-review-tab-clean.png');
  });

  /**
   * 2. Review tab with a populated file list
   */
  test('visual_review_tab_file_list', async ({ page }) => {
    await setupRoutes(page);
    await openReviewTab(page);

    // Wait for at least one file path to render in the file list
    await expect(coreFileEntry(page)).toBeVisible();

    await expect(page).toHaveScreenshot('visual-review-tab-file-list.png');
  });

  /**
   * 3. Diff dialog – unified (inline) mode
   */
  test('visual_diff_dialog_inline', async ({ page }) => {
    await setupRoutes(page);
    await openReviewTab(page);

    // Wait for the file list to load
    await expect(coreFileEntry(page)).toBeVisible();

    // Click the file row button in FileListSection.
    // FileListSection renders each file as a button containing the path text.
    await page
      .getByRole('button')
      .filter({ hasText: 'core.py' })
      .first()
      .click();

    // Wait for the selected diff to render in the main review panel.
    await expect(page.getByText('Review selected file diff')).toBeVisible({ timeout: 10_000 });

    // Switch to inline mode.
    await page.getByRole('button', { name: 'Inline' }).click();

    await expect(page).toHaveScreenshot('visual-diff-dialog-inline.png');
  });

  /**
   * 4. Diff dialog – split mode
   */
  test('visual_diff_dialog_split', async ({ page }) => {
    await setupRoutes(page);
    await openReviewTab(page);

    await expect(coreFileEntry(page)).toBeVisible();
    await page
      .getByRole('button')
      .filter({ hasText: 'core.py' })
      .first()
      .click();

    // Wait for the selected diff to render in the main review panel.
    await expect(page.getByText('Review selected file diff')).toBeVisible({ timeout: 10_000 });

    // Switch to split mode
    await page.getByRole('button', { name: 'Split' }).click();

    await expect(page).toHaveScreenshot('visual-diff-dialog-split.png');
  });

  /**
   * 5. Prune mode active — toolbar is visible
   */
  test('visual_prune_mode_active', async ({ page }) => {
    await setupRoutes(page);
    await openReviewTab(page);

    // Wait for file list to load first
    await expect(coreFileEntry(page)).toBeVisible();

    // Activate prune mode via the header button
    await page.getByRole('button', { name: /Prune Mode/i }).click();

    // The button label changes to "Exit Prune Mode" when active
    await expect(page.getByRole('button', { name: /Exit Prune Mode/i })).toBeVisible();

    await expect(page).toHaveScreenshot('visual-prune-mode-active.png');
  });

  /**
   * 6. Conflict resolver dialog
   */
  test('visual_conflict_resolver', async ({ page }) => {
    await setupRoutes(page, { conflicts: MOCK_CONFLICTS });
    await openReviewTab(page);

    // ConflictFileList renders an amber-bordered section with the "Conflicts" heading
    // when there are unresolved conflicts.
    await expect(page.getByText('Conflicts').first()).toBeVisible({ timeout: 10_000 });

    // The conflict file buttons appear below the "Conflicts" heading.
    // There may also be a same-named file in the regular FileListSection above,
    // so we take the last occurrence of the button with this path.
    const conflictFileBtn = page
      .getByRole('button')
      .filter({ hasText: /src\/orchestrator\/core\.py/ })
      .last();

    await expect(conflictFileBtn).toBeVisible({ timeout: 10_000 });
    await conflictFileBtn.click();

    // Wait for the conflict resolver dialog to open
    await expect(page.getByText('Conflict Resolver')).toBeVisible({ timeout: 10_000 });

    await expect(page).toHaveScreenshot('visual-conflict-resolver.png');
  });

  /**
   * 7. Merge readiness bar — all gates passing (ready state)
   */
  test('visual_merge_readiness_ready', async ({ page }) => {
    await setupRoutes(page, { readiness: MOCK_READINESS_READY });
    await openReviewTab(page);

    // Wait for gate labels to appear in the readiness bar
    await expect(page.getByText('No merge conflicts')).toBeVisible();
    await expect(page.getByText('Tests pass').first()).toBeVisible();

    // Capture the readiness bar element — it contains the "Commit Merge Back" button
    const readinessBar = page.locator('[aria-label="Merge readiness"]');

    await expect(readinessBar).toBeVisible();
    await expect(readinessBar).toHaveScreenshot('visual-merge-readiness-ready.png');
  });

  /**
   * 8. Merge readiness bar — gates blocked (not ready)
   */
  test('visual_merge_readiness_blocked', async ({ page }) => {
    await setupRoutes(page, { readiness: MOCK_READINESS_BLOCKED });
    await openReviewTab(page);

    // Wait for gate labels (including the failing one)
    await expect(page.getByText('Tests pass').first()).toBeVisible();

    // "Commit Merge Back" button should be disabled when not ready
    const mergeBtn = page.getByRole('button', { name: 'Commit Merge Back' });
    await expect(mergeBtn).toBeVisible();
    await expect(mergeBtn).toBeDisabled();

    const readinessBar = page.locator('[aria-label="Merge readiness"]');

    await expect(readinessBar).toBeVisible();
    await expect(readinessBar).toHaveScreenshot('visual-merge-readiness-blocked.png');
  });
});
