import { expect, test, type Page } from '@playwright/test';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const testDir = dirname(fileURLToPath(import.meta.url));
const reviewPath = resolve(
  testDir,
  '../../../research/ui-foundation/reviews/phase-3-reality-capability-01.html',
);
const reviewUrl = pathToFileURL(reviewPath).href;

async function openReview(page: Page) {
  await page.goto(reviewUrl);
  await expect(page.getByRole('heading', { name: 'Reality & capability review' })).toBeVisible();
}

test.describe('Phase 3 grounded review checkpoint', () => {
  test('opens generated offline evidence without external requests and keeps the narrow layout readable', async ({ page }) => {
    const externalRequests: string[] = [];
    page.on('request', (request) => {
      if (!request.url().startsWith('file:')) externalRequests.push(request.url());
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await openReview(page);

    await expect(page.locator('[data-review-item]')).toHaveCount(5);
    await expect(page.locator('[data-review-item]').first()).toContainText('Q-5');
    await expect(page.locator('[data-review-item]').first()).toContainText('Why this matters');
    await expect(page.locator('[data-review-item]').first()).toContainText('Proposed interpretation');
    await expect(page.locator('[data-review-item]').first()).toContainText('What supports it');
    await expect(page.locator('[data-review-item]').first()).toContainText('What remains uncertain');
    await expect(page.locator('[data-review-item]').first()).toContainText('Consequence of accepting');
    await expect(page.locator('[data-review-item]').first()).toContainText('Options');
    const disclosure = page.locator('details').first();
    await expect(disclosure).toBeVisible();
    await disclosure.locator('summary').click();
    await expect(disclosure).toContainText('catalog/questions.yaml');
    expect(externalRequests).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });

  test('records every feedback state with history, filters, keyboard focus, copied IDs, and exports', async ({ page }) => {
    await openReview(page);
    const firstItem = page.locator('[data-review-item="Q-5"]');
    const copyId = firstItem.getByRole('button', { name: 'Copy Q-5' });
    await copyId.focus();
    await expect(copyId).toBeFocused();
    await expect(copyId).toHaveCSS('outline-style', 'solid');

    for (const response of ['accept', 'reject', 'revise', 'uncertain'] as const) {
      await firstItem.getByRole('button', { name: response }).click();
      await expect(firstItem).toHaveAttribute('data-response', response);
    }
    await firstItem.getByLabel('Note for Q-5').fill('Authority needs a human decision.');
    await firstItem.getByRole('button', { name: 'accept' }).click();
    await expect
      .poll(() => page.evaluate(() => Object.keys(localStorage).filter((key) => key.includes('review-feedback.v1.phase-3-01')).length))
      .toBe(1);
    await page.reload();
    await expect(firstItem).toHaveAttribute('data-response', 'accept');
    await expect(firstItem.getByLabel('Note for Q-5')).toHaveValue('Authority needs a human decision.');

    await page.getByRole('button', { name: 'accepted' }).click();
    await expect(page.locator('[data-review-item]:visible')).toHaveCount(1);
    for (const filter of ['unresolved', 'rejected', 'revise', 'uncertain'] as const) {
      await page.getByRole('button', { name: filter }).click();
      await expect(page.locator('[data-review-item]:visible')).toHaveCount(filter === 'unresolved' ? 4 : 0);
    }
    await page.getByRole('button', { name: 'all responses' }).click();
    await expect(page.locator('[data-review-item]:visible')).toHaveCount(5);

    const jsonDownload = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export JSON' }).click();
    expect((await jsonDownload).suggestedFilename()).toMatch(/phase-3-01-feedback\.json$/);
    const textDownload = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export concise text' }).click();
    expect((await textDownload).suggestedFilename()).toMatch(/phase-3-01-feedback\.txt$/);
  });

  test('fails closed with a readable initialization error when generated review data is invalid', async ({ page }) => {
    await openReview(page);
    await page.evaluate(() => {
      document.querySelector('[data-review-data]')!.textContent = '{broken';
      window.foundationReview.initialize();
    });
    await expect(page.getByRole('alert')).toContainText('Review initialization failed');
    await expect(page.getByRole('alert')).toContainText('Generated review data is invalid');
  });
});
