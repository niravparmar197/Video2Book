import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, seedTrackedBooks, mockJson, API_BASE } from './mocks';

test('shows the empty state when no books are tracked', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  await page.getByTestId('nav-tab-books').click();

  await expect(page.getByTestId('my-books-empty')).toBeVisible();
  await page.screenshot({ path: 'tests/screenshots/task5-01-empty.png' });
});

test('lists tracked books with their live status', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await seedTrackedBooks(page, ['book-1', 'book-2']);
  await mockJson(page, 'GET', `${API_BASE}/books/book-1`, 200, {
    id: 'book-1',
    status: 'done',
    pdf_path: 'books/book-1.pdf',
    error_message: null,
  });
  await mockJson(page, 'GET', `${API_BASE}/books/book-2`, 200, {
    id: 'book-2',
    status: 'failed',
    pdf_path: null,
    error_message: 'boom',
  });

  await page.getByTestId('nav-tab-books').click();

  await expect(page.getByTestId('my-books-row-book-1')).toContainText('Done');
  await expect(page.getByTestId('my-books-row-book-2')).toContainText('Failed');
  await page.screenshot({ path: 'tests/screenshots/task5-02-populated.png' });
});
