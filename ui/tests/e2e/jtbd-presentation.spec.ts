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

    await page.reload();
    await expect(page.getByRole('heading', { name: 'Operational Cartography' })).toBeVisible();
  });

  test('changes workspace state independently of deck navigation', async ({ page }) => {
    await openPresentation(page, '#cartography');
    await page.keyboard.press('3');
    await expect(page.locator('[data-workspace-state="cause"]')).toHaveAttribute('aria-pressed', 'true');
    await expect(page).toHaveURL(/#cartography$/);
  });
});
