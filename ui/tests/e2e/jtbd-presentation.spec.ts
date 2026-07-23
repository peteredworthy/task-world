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

    await expect(page.getByText('Recovery resumes suspended work exactly once after executor restart')).toBeVisible();
    await expect(page.getByText('R2', { exact: true })).toBeVisible();
    await expect(page.locator('[data-node-stat-row]')).toHaveCount(5);
    await expect(page.locator('[data-node-stat-row]').first()).toContainText('Implement replay boundary');
    await expect(page.locator('[data-node-stat-row]').first()).toContainText('C');
    await expect(page.locator('.fleet-ribbon')).toHaveAttribute('aria-label', /2 need attention, 7 progressing, 1 waiting/);

    await page.locator('.graph-node[data-node-id="N14"]').click();
    await expect(page.locator('[data-selected-object]')).toContainText('Implement replay boundary');
    await expect(page.locator('.capability--proposed')).toContainText('Proposed capability');
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
