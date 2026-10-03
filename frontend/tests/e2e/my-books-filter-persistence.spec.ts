import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, makeBook, seedTrackedBooks, mockJson, API_BASE } from './mocks';

test('the selected filter survives navigating away and a full page reload', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await seedTrackedBooks(page, ['book-persist-1', 'book-persist-2']);
  await mockJson(page, 'GET', `${API_BASE}/books/book-persist-1`, 200, makeBook({ id: 'book-persist-1', status: 'failed' }));
  await mockJson(page, 'GET', `${API_BASE}/books/book-persist-2`, 200, makeBook({ id: 'book-persist-2', status: 'done' }));

  await page.getByTestId('nav-tab-books').click();
  await page.getByTestId('my-books-filter-failed').click();
  await expect(page.getByTestId('my-books-row-book-persist-1')).toBeVisible();
  await expect(page.getByTestId('my-books-row-book-persist-2')).toHaveCount(0);

  await page.reload();
  await page.getByTestId('nav-tab-books').click();

  await expect(page.getByTestId('my-books-filter-failed')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('my-books-filter-all')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByTestId('my-books-row-book-persist-1')).toBeVisible();
  await expect(page.getByTestId('my-books-row-book-persist-2')).toHaveCount(0);
});

test('a fresh session with nothing stored defaults to All', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await seedTrackedBooks(page, ['book-persist-3']);
  await mockJson(page, 'GET', `${API_BASE}/books/book-persist-3`, 200, makeBook({ id: 'book-persist-3', status: 'done' }));

  await page.getByTestId('nav-tab-books').click();

  await expect(page.getByTestId('my-books-filter-all')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('my-books-row-book-persist-3')).toBeVisible();
});

test('a corrupted/unrecognized stored filter value falls back to All without crashing', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await page.evaluate(() => localStorage.setItem('v2b_my_books_filter', 'not-a-real-filter'));
  await seedTrackedBooks(page, ['book-persist-4']);
  await mockJson(page, 'GET', `${API_BASE}/books/book-persist-4`, 200, makeBook({ id: 'book-persist-4', status: 'queued' }));

  await page.getByTestId('nav-tab-books').click();

  await expect(page.getByTestId('my-books-filter-all')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('my-books-row-book-persist-4')).toBeVisible();
});
