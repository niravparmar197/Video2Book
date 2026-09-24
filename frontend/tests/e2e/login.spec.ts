import { test, expect } from '@playwright/test';
import { installApiMocks, mockJson, API_BASE } from './mocks';

test.describe('login screen', () => {
  test('register a new account, save the issued key, and reach the app', async ({ page }) => {
    await installApiMocks(page);
    await mockJson(page, 'POST', `${API_BASE}/users`, 201, {
      user_id: 'user-1',
      api_key: 'test-api-key-abc123',
    });

    await page.goto('/');
    await page.screenshot({ path: 'tests/screenshots/task3-01-login-empty.png' });

    await page.getByTestId('login-email-input').fill('dev@example.com');
    await page.getByTestId('login-register-submit').click();

    await expect(page.getByTestId('login-issued-key')).toHaveText('test-api-key-abc123');
    await page.getByTestId('login-continue-button').click();

    await expect(page.getByRole('heading', { name: 'New book' })).toBeVisible();
    const storedKey = await page.evaluate(() => localStorage.getItem('v2b_api_key'));
    expect(storedKey).toBe('test-api-key-abc123');

    await page.screenshot({ path: 'tests/screenshots/task3-02-logged-in.png' });
  });

  test('log in by pasting an existing API key', async ({ page }) => {
    await installApiMocks(page);

    await page.goto('/');
    await page.getByTestId('login-tab-paste').click();
    await page.getByTestId('login-paste-key-input').fill('pasted-key-xyz');
    await page.getByTestId('login-paste-submit').click();

    await expect(page.getByRole('heading', { name: 'New book' })).toBeVisible();
    const storedKey = await page.evaluate(() => localStorage.getItem('v2b_api_key'));
    expect(storedKey).toBe('pasted-key-xyz');
  });

  test('shows the backend error message when registration fails', async ({ page }) => {
    await installApiMocks(page);
    await mockJson(page, 'POST', `${API_BASE}/users`, 409, { detail: 'email already registered' });

    await page.goto('/');
    await page.getByTestId('login-email-input').fill('dev@example.com');
    await page.getByTestId('login-register-submit').click();

    await expect(page.getByTestId('login-error')).toHaveText('email already registered');
  });
});
