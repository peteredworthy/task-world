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
    await expect(page.locator('.capability--proposed')).toContainText('Proposed capability');
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

  test('intervention review action is guarded until the modal capability is available', async ({ page }) => {
    await openPresentation(page, '#intervention');
    const review = page.getByRole('button', { name: 'Review proposed intervention' });
    await review.click();
    await expect(page.locator('[data-live-region]')).toContainText('Confirmation becomes available in the final interaction task');
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
});
