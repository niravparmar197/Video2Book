import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, mockJson, API_BASE } from './mocks';

test('my books screen shows the shared loading state before resolving to the shared empty state', async ({
  page,
}) => {
  await installApiMocks(page);
  await loginAs(page);

  // Deliberate delay so the loading state is observable instead of racing
  // an instantly-resolved mock (see Task 8's note on this same issue).
  await page.route(/^http:\/\/localhost:8000\/books(\?.*)?$/, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 300));
    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });

  await page.getByTestId('nav-tab-books').click();

  await expect(page.getByTestId('state-message')).toHaveAttribute('data-variant', 'loading');
  await expect(page.getByTestId('my-books-empty')).toHaveAttribute('data-variant', 'empty');
});

test('my books screen shows an error when the book list cannot be loaded', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await page.route(/^http:\/\/localhost:8000\/books(\?.*)?$/, (route) =>
    route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'database down' }) })
  );

  await page.getByTestId('nav-tab-books').click();

  await expect(page.getByTestId('my-books-error')).toHaveText('database down');
});

test('my books screen empty state uses the shared component', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  await page.getByTestId('nav-tab-books').click();

  const empty = page.getByTestId('my-books-empty');
  await expect(empty).toBeVisible();
  await expect(empty).toHaveAttribute('data-variant', 'empty');
});

test('error banners keep their exact text (no icon glyph text leaking in)', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 429, { detail: 'rate limited' });

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  const errorEl = page.getByTestId('new-book-error');
  await expect(errorEl).toHaveText('rate limited');
  await expect(errorEl).toHaveAttribute('data-variant', 'error');
});
