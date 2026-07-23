import { expect, test, type Page } from '@playwright/test';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const testDir = dirname(fileURLToPath(import.meta.url));
const artifactPath = resolve(
  testDir,
  '../../../outputs/jtbd-ui-directions/05-five-approach-interactive-comparison.html',
);
const artifactUrl = pathToFileURL(artifactPath).href;

async function openPresentation(page: Page, hash = '') {
  await page.goto(`${artifactUrl}${hash}`);
  await expect(page.locator('[data-presentation]')).toBeVisible();
}

test.describe('JTBD UI approaches presentation', () => {
  test('opens from the filesystem with seven addressable slides', async ({ page }) => {
    await openPresentation(page);
    await expect(page.locator('[data-slide]')).toHaveCount(7);
    await expect(page.getByRole('heading', { name: 'One operating loop, five interface models' })).toBeVisible();

    await page.keyboard.press('ArrowRight');
    await expect(page).toHaveURL(/#cartography$/);
    await expect(page.getByRole('heading', { name: 'Operational Cartography' })).toBeVisible();
    const liveRegion = page.locator('[data-live-region]');
    expect(await liveRegion.ariaSnapshot()).toContain('Slide: cartography');
    const liveRegionBox = await liveRegion.boundingBox();
    expect(
      liveRegionBox === null
        || liveRegionBox.x + liveRegionBox.width <= 0
        || liveRegionBox.y + liveRegionBox.height <= 0,
    ).toBe(true);

    await page.reload();
    await expect(page.getByRole('heading', { name: 'Operational Cartography' })).toBeVisible();
  });

  test('keeps rendered slides synchronized with browser history', async ({ page }) => {
    await openPresentation(page);
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');
    await expect(page).toHaveURL(/#causal$/);
    await expect(page.getByRole('heading', { name: 'Causal Spine' })).toBeVisible();

    await page.goBack();
    await expect(page).toHaveURL(/#cartography$/);
    await expect(page.getByRole('heading', { name: 'Operational Cartography' })).toBeVisible();

    await page.goForward();
    await expect(page).toHaveURL(/#causal$/);
    await expect(page.getByRole('heading', { name: 'Causal Spine' })).toBeVisible();
  });

  test('changes workspace state independently of deck navigation', async ({ page }) => {
    await openPresentation(page, '#cartography');
    await page.keyboard.press('3');
    await expect(page.locator('[data-workspace-state="cause"]')).toHaveAttribute('aria-pressed', 'true');
    await expect(page).toHaveURL(/#cartography$/);
  });

  test('cartography joins topology, readable requirements, grades, and vertical node statistics', async ({ page }) => {
    await openPresentation(page, '#cartography');
    await page.keyboard.press('3');

    await expect(page.locator('[data-slide="cartography"]').getByText('Recovery resumes suspended work exactly once after executor restart')).toBeVisible();
    await expect(page.locator('[data-slide="cartography"]').getByText('R2', { exact: true })).toBeVisible();
    await expect(page.locator('[data-node-stat-row]')).toHaveCount(5);
    await expect(page.locator('[data-node-stat-row]').first()).toContainText('Implement replay boundary');
    await expect(page.locator('[data-node-stat-row]').first()).toContainText('C');
    await expect(page.locator('.fleet-ribbon')).toHaveAttribute('aria-label', /2 need attention, 7 progressing, 1 waiting/);

    await page.locator('.graph-node[data-node-id="N14"]').click();
    const selectedNodeSummary = page.locator('[data-selected-node-summary]');
    await expect(selectedNodeSummary).toContainText('Implement replay boundary');
    await expect(selectedNodeSummary).toContainText('N14');
    await expect(page.locator('.capability--proposed').last()).toContainText('Proposed capability');
  });

  test('cartography presents a scenario-derived exception narrative with accessible node statistics', async ({ page }) => {
    await openPresentation(page, '#cartography');

    const inspector = page.locator('[data-selected-object]');
    const narrativeOrder = await inspector.locator('[data-exception-step]').evaluateAll((steps) =>
      steps.map((step) => step.getAttribute('data-exception-step')),
    );
    expect(narrativeOrder).toEqual(['constraint', 'evidence', 'consequence', 'action']);
    await expect(inspector.locator('[data-exception-step="constraint"]')).toContainText('Recovery resumes suspended work exactly once after executor restart');
    await expect(inspector.getByText('R2', { exact: true })).toBeVisible();
    await expect(page.locator('.fleet-run-name')).toContainText('Suspension replay recovery');
    await expect(page.locator('.fleet-run-meta')).toContainText('r314');
    await expect(inspector.locator('[data-exception-step="evidence"]')).toContainText('Deterministic suspension replay');
    await expect(inspector.locator('[data-exception-step="evidence"]')).toContainText('Incident record INC-042');
    await expect(inspector.locator('[data-exception-step="consequence"]')).toContainText('3 blocked successors · $1.05 retry cost · 1 attempt left');
    await expect(inspector.locator('[data-exception-step="action"]')).toContainText('bind Deterministic suspension replay and Incident record INC-042');

    await expect(page.locator('[data-node-stat-row]').first()).toHaveAttribute('role', 'row');
    await expect(page.locator('[data-node-stat-row]').first().locator('button')).not.toHaveAttribute('role');
    await expect(page.locator('.node-stat-head')).toHaveCSS('position', 'sticky');
  });

  test('evidence workbench uses canonical claim history, fixed node rows, and data-derived locator branches', async ({ page }) => {
    await openPresentation(page, '#evidence');
    await page.keyboard.press('3');
    const matrix = page.locator('.evidence-matrix');
    await expect(matrix.getByRole('columnheader')).toHaveText(['Node / attempt', 'Grade', 'Files', 'New evidence', 'Cost']);
    await expect(matrix.locator('[data-node-stat-row]')).toHaveCount(5);
    await expect(matrix).toContainText('Recovery resumes suspended work exactly once after executor restart');
    await expect(matrix).toContainText('R2 · node lineage');
    await expect(page.locator('.claim-index [data-claim-id="R2"]')).toContainText('R2 · required · C → C');
    await expect(matrix.locator('.node-stat-table')).toHaveCSS('max-height', '295px');
    await expect(matrix.locator('.node-stat-head')).toHaveCSS('position', 'sticky');
    await expect(page.locator('.packet-delta')).toContainText('Deterministic suspension replay');
    await expect(page.locator('.packet-delta')).toContainText('Incident record INC-042');
    await expect(page.locator('.graph-locator')).toHaveAttribute('aria-label', /3 blocked successors/);
    await expect(page.locator('[data-locator-successor]')).toHaveCount(3);
  });

  test('evidence workbench changes emphasis for every operating state', async ({ page }) => {
    await openPresentation(page, '#evidence');
    const workspace = page.locator('.evidence-workbench');
    const expected = [
      ['1', 'fleet', '.claim-index', '2 active runs need attention'],
      ['2', 'position', '.graph-locator', 'holds 3 successors'],
      ['3', 'cause', '.packet-delta', '2 C grades have the same omission'],
      ['4', 'action', '.evidence-records', 'Open the source records'],
      ['5', 'outcome', '.node-stat-table', 'needed to establish grade A'],
    ] as const;

    for (const [key, state, focus, note] of expected) {
      await page.keyboard.press(key);
      await expect(workspace).toHaveAttribute('data-state', state);
      await expect(workspace.locator('.evidence-state-note')).toContainText(note);
      await expect(workspace.locator(focus)).toHaveCSS('box-shadow', /rgb/);
    }
  });

  test('evidence records expose provenance before expansion and inspect real bodies in place', async ({ page }) => {
    await openPresentation(page, '#evidence');
    const records = [
      ['prompt-r2-replay', 'Full prompt packet', 'N14 · builder · attempt 1', 'routine/recovery-replay.md', 'Requirement: Recovery resumes suspended work exactly once after executor restart.'],
      ['transcript-n18-verdict', 'Verifier transcript', 'N18 · verifier · attempt 2', 'verifier/N18/transcript.jsonl', 'VERIFIER: Grade C — deterministic suspension replay is not demonstrated.'],
      ['diff-recovery-replay', 'Implementation diff', 'N17 · builder · attempt 2', 'git:r314:N17', '@@ -42,6 +42,24 @@ async def resume_suspended_work'],
    ] as const;

    for (const [id, label, node, source, body] of records) {
      const record = page.locator(`[data-evidence-record="${id}"]`);
      await expect(record).toContainText(label);
      await expect(record).toContainText(node);
      await expect(record).toContainText(source);
      const trigger = record.getByRole('button', { name: `Open ${label}` });
      await expect(trigger).toHaveAttribute('aria-expanded', 'false');
      await expect(trigger).toHaveAttribute('aria-controls', `evidence-layer-${id}`);
      await trigger.click();
      const layer = page.locator(`#evidence-layer-${id}`);
      await expect(layer).toBeFocused();
      await expect(layer).toContainText(body);
      await expect(trigger).toHaveAttribute('aria-expanded', 'true');
      await layer.getByRole('button', { name: `Close ${label}` }).click();
      await expect(trigger).toBeFocused();
      await expect(page.locator(`#evidence-layer-${id}`)).toHaveCount(0);
    }
  });

  test('evidence workbench validates claim selection and drills a node into Cartography', async ({ page }) => {
    await openPresentation(page, '#evidence');
    await page.evaluate(() => window.taskWorldPresentation.selectObject('evidence', 'unknown-claim'));
    await expect(page.locator('.claim-index [data-claim-id="R2"]')).toHaveAttribute('aria-pressed', 'false');
    await expect(page.locator('.evidence-selection-note')).toContainText('Selection unknown-claim is unavailable; showing canonical requirement R2.');

    await page.locator('.evidence-matrix [data-node-stat-row] [data-node-id="N14"]').click();
    await expect(page).toHaveURL(/#cartography$/);
    await expect(page.locator('[data-selected-node-summary]')).toContainText('N14');
  });

  test('evidence detail closes with Escape and restores trigger focus', async ({ page }) => {
    await openPresentation(page, '#evidence');
    const trigger = page.getByRole('button', { name: 'Open Full prompt packet' });
    await trigger.click();
    await expect(page.locator('#evidence-layer-prompt-r2-replay')).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(page.locator('#evidence-layer-prompt-r2-replay')).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });

  test('evidence workbench renders canonical successor branches and repeated grade history', async ({ page }) => {
    await openPresentation(page, '#evidence');
    await page.keyboard.press('3');
    await expect(page.locator('.packet-delta')).toContainText('C → C');
    await expect(page.locator('[data-locator-successor]')).toHaveCount(3);
    await expect(page.locator('.graph-locator')).toContainText('r314 · blast radius 3 successors');
  });

  test('mission weave resolves branches, grades, rework, directive, and convergence by state', async ({ page }) => {
    await openPresentation(page, '#weave');
    await page.keyboard.press('2');
    await expect(page.locator('.weave-lane')).toHaveCount(5);
    await expect(page.locator('[data-weave-segment="corrective-evidence"]')).toHaveCount(0);
    await expect(page.locator('[data-weave-segment="verify-correction"], [data-weave-segment="final-gate"], [data-weave-segment="merge"]')).toHaveCount(0);
    await expect(page.locator('[data-weave-final-invariant]')).toHaveCount(0);
    await expect(page.locator('[data-weave-grade-history]')).toHaveText('C → C');
    await expect(page.locator('.weave-routes [data-weave-relation][data-weave-from="verify-a1"][data-weave-to="build-a2"][data-weave-kind="rework"]')).toBeVisible();
    await page.keyboard.press('4');
    const corrective = page.locator('.weave-grid [data-weave-segment="corrective-evidence"]');
    await expect(corrective).toContainText('Proposed capability');
    await expect(corrective).toHaveClass(/weave-segment--proposed/);
    await expect(corrective).toHaveCSS('border-style', 'dashed');
    await expect(page.locator('.weave-grid [data-weave-segment="verify-correction"], .weave-grid [data-weave-segment="final-gate"], .weave-grid [data-weave-segment="merge"]')).toHaveCount(0);
    await expect(page.locator('[data-weave-final-invariant]')).toHaveCount(0);
    const correctionBranch = page.locator('.weave-routes [data-weave-relation][data-weave-from="recovery-verify-a2"][data-weave-to="corrective-evidence"][data-weave-kind="branch"]');
    await expect(correctionBranch).toHaveClass(/weave-route--proposed/);
    await expect(page.locator('.weave-routes [data-weave-relation][data-weave-from="verify-correction"][data-weave-to="final-gate"][data-weave-kind="join"], .weave-routes [data-weave-relation][data-weave-from="final-gate"][data-weave-to="merge"][data-weave-kind="converge"]')).toHaveCount(0);
    await corrective.click();
    await page.keyboard.press('5');
    await expect(corrective).toContainText('Replay + incident evidence bound');
    await expect(corrective).not.toContainText('Proposed capability');
    await expect(corrective).toHaveClass(/weave-segment--verified/);
    await expect(page.locator('[data-weave-selected-detail]')).toContainText('Replay + incident evidence bound');
    await expect(page.locator('[data-weave-selected-detail]')).toContainText('verified');
    await expect(page.locator('[data-weave-final-invariant]')).toContainText('Recovery invariants · A · merged');
    await expect(page.locator('[data-weave-segment="verify-correction"]')).toContainText('A');
    await expect(correctionBranch).not.toHaveClass(/weave-route--proposed/);
  });

  test('mission weave preserves labeled relations and vertical workstream rows on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openPresentation(page, '#weave');
    await page.keyboard.press('5');
    const mobileRelations = page.locator('.weave-mobile-relations [data-weave-relation]');
    await expect(mobileRelations).toHaveCount(8);
    await expect(mobileRelations.filter({ hasText: 'Verify: Suspension replay → Build: Revise recovery path' })).toBeVisible();
    await expect(mobileRelations.filter({ hasText: 'Rework' })).toHaveCount(1);
    await expect(mobileRelations.filter({ hasText: 'Gate: Recovery invariants → Settle: Merged' })).toBeVisible();
    await expect(page.locator('.weave-row[data-weave-row="3"]')).toBeVisible();
    const containment = await page.locator('.mission-weave').evaluate((workspace) => ({
      documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      relationsVisible: [...workspace.querySelectorAll<HTMLElement>('.weave-mobile-relation')].every((relation) => {
        const bounds = relation.getBoundingClientRect();
        return bounds.width > 0 && bounds.height > 0;
      }),
    }));
    expect(containment).toEqual({ documentFits: true, relationsVisible: true });
  });

  test('causal spine preserves parallel branches and opens evidence in place', async ({ page }) => {
    await openPresentation(page, '#causal');
    await page.keyboard.press('3');
    await expect(page.locator('.causal-track')).toHaveCount(3);
    await expect(page.getByText('Retry did not add evidence')).toBeVisible();
    await page.locator('[data-event-id="verdict-a1"]').click();
    await expect(page.locator('[data-causal-detail]')).toContainText('Attempt 1 verifier verdict');
    await expect(page.locator('[data-causal-detail]')).toContainText('C');
  });

  test('causal spine progressively extends its event horizon without changing slides', async ({ page }) => {
    await openPresentation(page, '#causal');
    await expect(page.locator('[data-event-id="directive"]')).toHaveCount(0);
    await expect(page.locator('[data-event-id="final-a"]')).toHaveCount(0);
    await expect(page.locator('[data-event-id="merge"]')).toHaveCount(0);

    await page.keyboard.press('2');
    await expect(page).toHaveURL(/#causal$/);
    await expect(page.locator('[data-event-id="directive"]')).toHaveCount(0);
    await page.keyboard.press('3');
    await expect(page.locator('[data-event-id="directive"]')).toHaveCount(0);

    await page.keyboard.press('4');
    await expect(page.locator('[data-event-id="directive"]')).toBeVisible();
    await expect(page.locator('[data-event-id="final-a"]')).toHaveCount(0);
    await expect(page.locator('[data-event-id="directive"]')).toContainText('Proposed capability');

    await page.keyboard.press('5');
    await expect(page.locator('[data-event-id="final-a"]')).toBeVisible();
    await expect(page.locator('[data-event-id="merge"]')).toBeVisible();
  });

  test('causal detail orders evidence and source navigation around the selected event', async ({ page }) => {
    await openPresentation(page, '#causal');
    await page.keyboard.press('4');
    await page.locator('[data-event-id="directive"]').click();
    const detail = page.locator('[data-causal-detail]');
    const detailOrder = await detail.locator('[data-causal-step]').evaluateAll((steps) =>
      steps.map((step) => step.getAttribute('data-causal-step')),
    );
    expect(detailOrder).toEqual(['constraint', 'evidence', 'consequence', 'action']);
    await expect(detail.locator('[data-causal-step="action"]')).toContainText('Proposed capability');

    await page.keyboard.press('3');
    await page.locator('[data-event-id="verdict-a1"]').click();
    await page.locator('[data-source-node-id="N15"]').click();
    await expect(page).toHaveURL(/#cartography$/);
    await expect(page.locator('[data-selected-node-summary]')).toContainText('N15');
  });

  test('causal categories resolve labels, branches, and distinct source records', async ({ page }) => {
    await openPresentation(page, '#causal');
    await expect(page.locator('[data-event-id="verdict-a2"]')).toContainText('Attempt 2 verifier verdict');
    await expect(page.locator('[data-branch-from="build-a1"][data-branch-to="verdict-a1"]')).toHaveAttribute('data-branch-kind', 'handoff');
    await expect(page.locator('[data-branch-from="verdict-a1"][data-branch-to="retry"]')).toHaveAttribute('data-branch-kind', 'retry');

    await page.keyboard.press('4');
    await expect(page.locator('[data-event-id="directive"]')).toContainText('Bind replay and incident evidence');
    await page.getByRole('button', { name: 'Requirement record R2' }).click();
    await expect(page).toHaveURL(/#cartography$/);
    await expect(page.locator('[data-requirement-id="R2"]')).toBeFocused();

    await openPresentation(page, '#causal');
    await page.getByRole('button', { name: 'Run record r314' }).click();
    await expect(page.locator('[data-causal-run-record]')).toBeFocused();
  });

  test('intervention desk ranks exceptions and keeps consequence beside action', async ({ page }) => {
    await openPresentation(page, '#intervention');
    const queue = page.locator('.case-queue');
    await expect(queue.locator('[data-case-id]')).toHaveCount(2);
    await expect(queue.locator('[data-case-id]').nth(0)).toHaveAttribute('data-case-id', 'case-r314');
    await expect(queue.locator('[data-case-id]').nth(1)).toHaveAttribute('data-case-id', 'case-auth-gate');
    await expect(page.locator('[data-case-id="case-r314"]')).toContainText('3 successors blocked');
    await expect(page.locator('[data-case-id="case-r314"]')).toContainText('Age · 23 min · process age · two verifier cycles');
    await page.locator('[data-case-id="case-r314"]').click();
    const packet = page.locator('.decision-packet');
    expect(await packet.locator('[data-packet-step]').evaluateAll((steps) => steps.map((step) => step.getAttribute('data-packet-step')))).toEqual(['trigger', 'evidence', 'consequence', 'options', 'authority', 'validation', 'action']);
    await expect(packet).toContainText('Recovery resumes suspended work exactly once after executor restart');
    await expect(packet).toContainText('R2');
    await expect(packet).toContainText('Another unchanged retry');
    await expect(packet).toContainText('$1.05');
    await expect(packet).toContainText('1 attempt remains');
    await expect(packet).toContainText('Proposed capability');
    expect((await packet.innerText()).indexOf('Recovery resumes suspended work exactly once after executor restart')).toBeLessThan((await packet.innerText()).indexOf('R2'));
    await expect(page.locator('.intervention-fleet-ribbon')).toHaveAttribute('aria-label', '2 need attention, 7 progressing, 1 waiting');
    await expect(page.getByRole('button', { name: 'Review proposed intervention' })).toBeVisible();
    await expect(packet.getByRole('button', { name: /confirm|cancel/i })).toHaveCount(0);
  });

  test('intervention desk changes structural emphasis and selects the ranked case packet', async ({ page }) => {
    await openPresentation(page, '#intervention');
    const desk = page.locator('.intervention-desk');

    for (const [key, expectedFocus] of [['1', 'fleet'], ['2', 'position'], ['3', 'cause'], ['4', 'action'], ['5', 'outcome']] as const) {
      await page.keyboard.press(key);
      await expect(desk).toHaveAttribute('data-state', expectedFocus);
      await expect(desk.locator(`[data-intervention-focus="${expectedFocus}"]`).first()).toHaveClass(/is-emphasized/);
    }

    await page.locator('[data-case-id="case-auth-gate"]').click();
    const packet = page.locator('.decision-packet');
    await expect(packet).toContainText('Release manager approval required');
    await expect(packet).toContainText('1 recovery audit publication remains held');
    await expect(packet).toContainText('Publish recovery audit');
    await expect(packet).not.toContainText('Another unchanged retry');
    await expect(packet).not.toContainText(/retry/i);
    await expect(packet).not.toContainText('Proposed capability');
    await expect(packet.getByRole('button', { name: 'Await release manager approval' })).toBeVisible();
    await page.keyboard.press('4');
    await expect(page.locator('.intervention-state-note')).toContainText('Release manager approval is required before the recovery audit can publish');
  });

  test('decision confirmation is modal, labeled proposed, and restores focus', async ({ page }) => {
    await openPresentation(page, '#intervention');
    const trigger = page.getByRole('button', { name: 'Review proposed intervention' });
    await trigger.click();
    const dialog = page.getByRole('dialog', { name: 'Review corrective intervention' });
    const cancel = dialog.getByRole('button', { name: 'Cancel' });
    const authorize = dialog.getByRole('button', { name: 'Authorize proposed correction' });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('Proposed capability');
    await expect(dialog).toContainText('3 successors');
    await expect(dialog).toContainText('$0.62');
    await expect(dialog).toContainText('Consequence');
    await expect(dialog).toContainText('remain blocked until correction verifies');
    await expect(dialog).toContainText('Authority');
    await expect(dialog).toContainText('Reversibility');
    await expect(dialog).toContainText('Validation');
    await expect(cancel).toBeFocused();
    await expect(page.locator('body')).toHaveClass(/modal-open/);
    await authorize.focus();
    await page.keyboard.press('Tab');
    await expect(cancel).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(authorize).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
    await expect(trigger).toBeFocused();
  });

  test('decision confirmation records an auditable local outcome without a backend call', async ({ page }) => {
    const nonFileRequests: string[] = [];
    page.on('request', (request) => {
      if (!request.url().startsWith('file:')) nonFileRequests.push(request.url());
    });
    await openPresentation(page, '#intervention');
    await page.getByRole('button', { name: 'Review proposed intervention' }).click();
    await page.getByRole('button', { name: 'Authorize proposed correction' }).click();
    await expect(page.locator('[data-concept="intervention"][data-state="outcome"]')).toBeVisible();
    await expect(page.locator('[data-decision-result]')).toContainText('Accepted locally');
    await expect(page.locator('[data-decision-result]')).toContainText('no backend command sent');
    await expect(page.locator('[data-decision-result]')).toBeFocused();
    expect(nonFileRequests).toEqual([]);
  });

  test('comparison uses rubric language without fabricated observed scores', async ({ page }) => {
    await openPresentation(page, '#comparison');
    await expect(page.locator('.comparison-matrix')).toContainText('Causal comprehension');
    await expect(page.locator('.comparison-matrix')).toContainText('Decision readiness');
    await expect(page.locator('.comparison-matrix')).toContainText('Expected strength');
    await expect(page.getByText(/user-tested score/i)).toHaveCount(0);
    await expect(page.locator('.comparison-matrix tbody tr')).toHaveCount(5);
    await expect(page.locator('.comparison-matrix thead tr').last().locator('th')).toHaveCount(10);
    await expect(page.getByText('Expected strength', { exact: true }).count()).resolves.toBeGreaterThan(0);
    await expect(page.getByText('Trade-off', { exact: true }).count()).resolves.toBeGreaterThan(0);
    await expect(page.getByText('Risk', { exact: true }).count()).resolves.toBeGreaterThan(0);
    await expect(page.getByText('Cartography + Evidence Workbench')).toBeVisible();
    await expect(page.getByText('Intervention Desk + Causal Spine')).toBeVisible();
    await expect(page.getByText('Mission Weave as fleet/run synopsis')).toBeVisible();
    expect(await page.locator('.comparison-matrix td .comparison-cell-reason').count()).toBe(50);
    expect(await page.locator('.comparison-matrix td .comparison-cell-reason').allTextContents()).not.toContain('');
    expect((await page.locator('.comparison-matrix td').allTextContents()).join(' ')).not.toMatch(/\b[1-5]\b|rating/i);
    await page.setViewportSize({ width: 390, height: 844 });
    const mobileComparison = page.locator('[data-comparison-mobile]');
    await expect(mobileComparison).toBeVisible();
    const mobileConcepts = [
      'Operational Cartography',
      'Causal Spine',
      'Intervention Desk',
      'Evidence Workbench',
      'Mission Weave',
    ];
    await expect(mobileComparison.locator('section')).toHaveCount(mobileConcepts.length);
    for (const conceptName of mobileConcepts) {
      const concept = mobileComparison.locator('section').filter({ has: page.getByRole('heading', { name: conceptName }) });
      const items = concept.getByRole('listitem');
      await expect(items).toHaveCount(10);
      for (const item of await items.all()) {
        await expect(item).toBeVisible();
        await expect(item.locator('strong')).not.toHaveText('');
        await expect(item.locator('.comparison-cell-label')).not.toHaveText('');
        await expect(item.locator('.comparison-cell-reason')).not.toHaveText('');
      }
    }
    const representativeCells = [
      ['Expected strength', 'The ranked exception queue puts blocked scope and urgency ahead of fleet context.'],
      ['Trade-off', 'Spatial adjacency suggests dependency but does not order the two verifier verdicts.'],
      ['Risk', 'The graph omits an authority packet, so a proposed correction can be mistaken for an approved command.'],
    ] as const;
    for (const [signal, reason] of representativeCells) {
      const cell = mobileComparison.getByRole('listitem').filter({ hasText: reason });
      await expect(cell).toBeVisible();
      await expect(cell.locator('.comparison-cell-label')).toHaveText(signal);
      await expect(cell.locator('.comparison-cell-reason')).toHaveText(reason);
    }
    const attentionReasons = await mobileComparison.locator('section').evaluateAll((sections) =>
      sections.map((section) => section.querySelector<HTMLElement>('.comparison-mobile-item .comparison-cell-reason')?.innerText),
    );
    const actionSafetyReasons = await mobileComparison.locator('section').evaluateAll((sections) =>
      sections.map((section) => {
        const item = [...section.querySelectorAll<HTMLElement>('.comparison-mobile-item')].find((candidate) =>
          candidate.querySelector('strong')?.textContent === 'Action safety and feedback',
        );
        return item?.querySelector<HTMLElement>('.comparison-cell-reason')?.innerText;
      }),
    );
    expect(new Set(attentionReasons).size).toBe(5);
    expect(new Set(actionSafetyReasons).size).toBe(5);
    await expect(mobileComparison.locator('.comparison-cell-reason').first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });

  test('artifact makes no external requests and avoids horizontal overflow', async ({ page }) => {
    const externalRequests: string[] = [];
    page.on('request', (request) => {
      if (!request.url().startsWith('file:')) externalRequests.push(request.url());
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await openPresentation(page, '#cartography');
    await page.keyboard.press('3');
    expect(externalRequests).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await expect(page.locator('.metric-card')).toHaveCount(0);
  });

  test('every concept exposes all five operating-loop states in place', async ({ page }) => {
    const concepts = ['cartography', 'causal', 'intervention', 'evidence', 'weave'];
    const states = ['fleet', 'position', 'cause', 'action', 'outcome'];
    for (const concept of concepts) {
      await openPresentation(page, `#${concept}`);
      for (const [index, state] of states.entries()) {
        await page.keyboard.press(String(index + 1));
        await expect(page.locator(`[data-concept="${concept}"][data-state="${state}"]`)).toBeVisible();
        await expect(page.locator(`[data-workspace-state="${state}"]`)).toHaveAttribute('aria-pressed', 'true');
      }
    }
  });

  test('causal spine stacks every visible event inside its mobile workspace', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openPresentation(page, '#causal');
    await page.keyboard.press('5');
    const containment = await page.locator('.causal-spine').evaluate((workspace) => {
      const workspaceBounds = workspace.getBoundingClientRect();
      const eventBounds = [...workspace.querySelectorAll<HTMLElement>('[data-event-id]')].map((event) => {
        const bounds = event.getBoundingClientRect();
        return bounds.left >= workspaceBounds.left && bounds.right <= workspaceBounds.right;
      });
      return {
        eventsWithinWorkspace: eventBounds.every(Boolean),
        documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      };
    });
    expect(containment).toEqual({ eventsWithinWorkspace: true, documentFits: true });
  });

  test('fits the presentation and all workspace states at mobile width', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openPresentation(page, '#cartography');

    const overflow = await page.evaluate(() => {
      const rail = document.querySelector<HTMLElement>('.state-rail');
      return {
        document: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        rail: rail !== null && rail.scrollWidth <= rail.clientWidth,
        bodyOverflowX: getComputedStyle(document.body).overflowX,
        railOverflowX: rail === null ? null : getComputedStyle(rail).overflowX,
      };
    });
    expect(overflow).toEqual({
      document: true,
      rail: true,
      bodyOverflowX: 'visible',
      railOverflowX: 'visible',
    });
    await expect(page.locator('[data-workspace-state]')).toHaveCount(5);
    const tableOverflow = await page.locator('.node-stat-table').evaluate((table) => table.scrollWidth <= table.clientWidth);
    expect(tableOverflow).toBe(true);
  });

  test('does not hijack guarded keyboard events', async ({ page }) => {
    await openPresentation(page, '#cartography');
    await page.evaluate(() => {
      const input = document.createElement('input');
      input.setAttribute('aria-label', 'Editable control');
      document.querySelector('[data-slide="cartography"]')?.append(input);
      input.focus();
    });
    await page.keyboard.press('ArrowRight');
    await expect(page).toHaveURL(/#cartography$/);

    await page.evaluate(() => {
      const modified = new KeyboardEvent('keydown', { key: 'ArrowRight', ctrlKey: true, bubbles: true });
      dispatchEvent(modified);
      const prevented = new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true });
      prevented.preventDefault();
      dispatchEvent(prevented);
      state.modal = 'details';
      dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
      state.modal = null;
    });
    await expect(page).toHaveURL(/#cartography$/);
  });

  test('accepts selections only for known concept slides', async ({ page }) => {
    await openPresentation(page);
    const result = await page.evaluate(() => ({
      accepted: window.taskWorldPresentation.selectObject('causal', 'verdict-a3'),
      rejected: window.taskWorldPresentation.selectObject('comparison', 'not-a-concept'),
      selectedByConcept: window.taskWorldPresentation.getState().selectedByConcept,
    }));

    expect(result.accepted).toBe(true);
    expect(result.rejected).toBe(false);
    expect(result.selectedByConcept.causal).toBe('verdict-a3');
    expect(result.selectedByConcept.comparison).toBeUndefined();
  });

  test('renders the full recovered operating loop and capability boundaries in every concept', async ({ page }) => {
    const concepts = ['cartography', 'causal', 'intervention', 'evidence', 'weave'] as const;
    const states = ['fleet', 'position', 'cause', 'action', 'outcome'] as const;
    const stateFacts = {
      fleet: 'r314',
      position: '3',
      cause: 'Recovery resumes suspended work exactly once after executor restart',
      action: 'Proposed capability',
      outcome: 'Grade A',
    } as const;

    for (const concept of concepts) {
      await openPresentation(page, `#${concept}`);
      for (const [index, workspaceState] of states.entries()) {
        await page.keyboard.press(String(index + 1));
        const workspace = page.locator(`[data-concept="${concept}"][data-state="${workspaceState}"]`);
        await expect(workspace).toBeVisible();
        await expect(workspace).toContainText(stateFacts[workspaceState]);
      }
      const outcome = page.locator(`[data-concept="${concept}"][data-state="outcome"]`);
      await expect(outcome).toContainText('merged');
      await expect(outcome).toContainText('avoided retry');
      await expect(outcome).toContainText('Promote restart replay fixture into the routine packet');
      await expect(outcome).toContainText('predecessor');
      await expect(page.locator(`[data-concept="${concept}"] .capability--current`).first()).toBeVisible();
      await expect(page.locator(`[data-concept="${concept}"] .capability--derivable`).first()).toBeVisible();
      await expect(page.locator(`[data-concept="${concept}"] .capability--proposed`).first()).toBeVisible();
    }
  });

  test('keeps the deck inert while the decision dialog is open and restores rail focus after state changes', async ({ page }) => {
    await openPresentation(page, '#intervention');
    const trigger = page.getByRole('button', { name: 'Review proposed intervention' });
    await trigger.click();
    await expect(page.locator('[data-presentation]')).toHaveAttribute('inert', '');
    await page.locator('[data-action="next-slide"]').focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/#intervention$/);
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-presentation]')).not.toHaveAttribute('inert');

    const actionRail = page.locator('[data-workspace-state="action"]');
    await actionRail.focus();
    await page.keyboard.press('Space');
    await expect(actionRail).toBeFocused();
    await expect(actionRail).toHaveAttribute('aria-pressed', 'true');
  });

  test('keeps decision-critical context and every workspace within desktop, tablet, and mobile widths', async ({ page }) => {
    const concepts = ['cartography', 'causal', 'intervention', 'evidence', 'weave'];
    const widths = [[1440, 900], [1024, 768], [390, 844]] as const;
    for (const [width, height] of widths) {
      await page.setViewportSize({ width, height });
      for (const concept of concepts) {
        await openPresentation(page, `#${concept}`);
        for (const key of ['1', '2', '3', '4', '5']) {
          await page.keyboard.press(key);
          const workspace = page.locator(`[data-concept="${concept}"]`);
          await expect(workspace).toBeVisible();
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
          await expect(workspace).toContainText(/Recovery resumes|grade|Proposed capability|merged/i);
        }
      }
    }
  });

  test('qualifies historical failure data and renders only resolved r314 facts in Outcome', async ({ page }) => {
    for (const concept of ['cartography', 'causal', 'intervention', 'evidence', 'weave']) {
      await openPresentation(page, `#${concept}`);
      await page.keyboard.press('5');
      const outcome = page.locator(`[data-concept="${concept}"][data-state="outcome"]`);
      await expect(outcome).toContainText('Before intervention');
      await expect(outcome).toContainText('released');
      await expect(outcome).not.toContainText('blocked by');
      await expect(outcome).not.toContainText('held successor');
      await expect(outcome).not.toContainText('Missing in both attempts');
    }
  });

  test('keeps the release approval case deferred instead of showing the r314 recovered outcome', async ({ page }) => {
    await openPresentation(page, '#intervention');
    await page.locator('[data-case-id="case-auth-gate"]').click();
    await page.keyboard.press('5');
    const outcome = page.locator('[data-concept="intervention"][data-state="outcome"]');
    await expect(outcome).toContainText('Awaiting release manager approval');
    await expect(outcome).not.toContainText('Grade A');
    await expect(outcome).not.toContainText('Promote restart replay fixture into the routine packet');
  });

  test('uses full-width outcome projections and a two-column mobile operating loop', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    for (const concept of ['intervention', 'evidence', 'weave']) {
      await openPresentation(page, `#${concept}`);
      await page.keyboard.press('5');
      const bounds = await page.locator(`[data-concept="${concept}"] [data-outcome-postscript]`).evaluate((projection) => {
        const workspace = projection.closest<HTMLElement>('[data-concept]')!;
        return { projection: projection.getBoundingClientRect().width, workspace: workspace.getBoundingClientRect().width };
      });
      expect(bounds.projection / bounds.workspace).toBeGreaterThan(0.7);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await openPresentation(page);
    await expect(page.locator('.loop-map span')).toHaveCount(8);
    expect(await page.locator('.loop-map').evaluate((loop) => getComputedStyle(loop).gridTemplateColumns.split(' ').length)).toBe(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
});
