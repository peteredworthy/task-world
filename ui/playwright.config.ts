import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for visual regression tests.
 *
 * Snapshots are stored under tests/e2e/__snapshots__/ and committed
 * to serve as baselines for future visual comparison runs.
 */
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['html', { open: 'never' }], ['list']],

  use: {
    baseURL: 'http://localhost:5399',
    trace: 'on-first-retry',
    // Reduce motion to stabilise screenshots (stops CSS animations)
    reducedMotion: 'reduce',
    // Fixed viewport for reproducible snapshots
    viewport: { width: 1280, height: 800 },
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    command: 'npm run dev -- --port 5399',
    url: 'http://localhost:5399',
    reuseExistingServer: false,
    timeout: 90_000,
  },

  // Store snapshots alongside the test file for easy review
  snapshotPathTemplate: '{testDir}/__snapshots__/{testFilePath}/{arg}{ext}',

  expect: {
    // Allow a small number of differing pixels to tolerate font-hinting
    // and sub-pixel rendering differences across environments.
    toHaveScreenshot: {
      maxDiffPixels: 150,
    },
  },
});
