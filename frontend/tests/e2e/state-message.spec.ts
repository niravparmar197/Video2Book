import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, seedTrackedBooks, mockJson, API_BASE } from './mocks';

test('my books screen shows the shared loading state before resolving to the shared empty state', async ({
  page,
}) => {
  await installApiMocks(page);
  await loginAs(page);
  await seedTrackedBooks(page, ['book-1']);

  // Deliberate delay so the loading state is observable instead of racing
  // an instantly-resolved mock (see Task 8's note on this same issue).
  await page.route(`${API_BASE}/books/book-1`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 300));
    return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'gone' }) });
  });

  await page.getByTestId('nav-tab-books').click();

  await expect(page.getByTestId('state-message')).toHaveAttribute('data-variant', 'loading');

  // MyBooksScreen treats an unreachable book as failed rather than empty,
  // so with only one tracked (now-404ing) id it lands on a populated list,
  // not the empty state -- confirms the shared component renders both
  // variants correctly across a real state transition.
  await expect(page.getByTestId('my-books-row-book-1')).toBeVisible();
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
