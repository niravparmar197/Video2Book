import { test, expect } from '@playwright/test';
import { installApiMocks, API_BASE } from './mocks';

test('app loads the login screen without any real backend call', async ({ page }) => {
  await installApiMocks(page);

  let backendCallCount = 0;
  page.on('request', (req) => {
    if (req.url().startsWith(API_BASE)) backendCallCount += 1;
  });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Video2Book' })).toBeVisible();

  await page.screenshot({ path: 'tests/screenshots/task1-01-smoke-login-screen.png' });

  expect(backendCallCount).toBe(0);
});
