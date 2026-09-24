import { test, expect, Page, Locator } from '@playwright/test';
import { installApiMocks, mockJson, API_BASE } from './mocks';

const VIEWPORT_WIDTH = 375;
test.use({ viewport: { width: VIEWPORT_WIDTH, height: 667 } });

async function assertNoHorizontalScroll(page: Page): Promise<void> {
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(VIEWPORT_WIDTH);
}

async function assertFullyInViewport(locator: Locator): Promise<void> {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(VIEWPORT_WIDTH);
}

test('core flow stays within a 375px-wide viewport with no horizontal scroll', async ({ page }) => {
  await installApiMocks(page);

  // Login
  await page.goto('/');
  await assertNoHorizontalScroll(page);
  for (const testId of ['login-tab-register', 'login-tab-paste', 'login-email-input', 'login-register-submit']) {
    await assertFullyInViewport(page.getByTestId(testId));
  }

  await mockJson(page, 'POST', `${API_BASE}/users`, 201, { user_id: 'user-1', api_key: 'test-key-mobile' });
  await page.getByTestId('login-email-input').fill('dev@example.com');
  await page.getByTestId('login-register-submit').click();
  await assertNoHorizontalScroll(page);
  await assertFullyInViewport(page.getByTestId('login-continue-button'));
  await page.getByTestId('login-continue-button').click();

  // New book
  await assertNoHorizontalScroll(page);
  for (const testId of ['new-book-url-input', 'new-book-submit']) {
    await assertFullyInViewport(page.getByTestId(testId));
  }
  await page.screenshot({ path: 'tests/screenshots/task10-01-new-book-mobile.png' });

  // My Books (empty state)
  await page.getByTestId('nav-tab-books').click();
  await assertNoHorizontalScroll(page);
  await assertFullyInViewport(page.getByTestId('my-books-empty'));
  await page.screenshot({ path: 'tests/screenshots/task10-02-my-books-mobile.png' });

  // Outline editor -- deliberately long chapter title to stress-test wrapping
  await page.getByTestId('nav-tab-new').click();
  const bookId = 'book-mobile-1';
  const outlineReadyBook = { id: bookId, status: 'outline_ready', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, outlineReadyBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, outlineReadyBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}/outline`, 200, [
    {
      id: 'ch-1',
      title: 'A Fairly Long Chapter Title That Could Wrap Awkwardly On A Narrow Phone Screen',
      order: 1,
      skip: false,
      locked: false,
      source_video_ids: ['v1'],
    },
  ]);

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('outline-chapter-ch-1')).toBeVisible();
  await assertNoHorizontalScroll(page);
  for (const testId of ['outline-lock-ch-1', 'outline-skip-ch-1', 'outline-save']) {
    await assertFullyInViewport(page.getByTestId(testId));
  }
  await page.screenshot({ path: 'tests/screenshots/task10-03-outline-mobile.png' });
});
