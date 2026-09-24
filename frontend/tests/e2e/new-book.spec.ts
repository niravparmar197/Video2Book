import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, mockJson, API_BASE } from './mocks';

test('submitting a link creates a book and navigates to its detail view', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const book = { id: 'book-abc123', status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, book);
  await mockJson(page, 'GET', `${API_BASE}/books/${book.id}`, 200, book);

  await expect(page.getByRole('heading', { name: 'New book' })).toBeVisible();
  await page.screenshot({ path: 'tests/screenshots/task4-01-new-book-empty.png' });

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('book-detail-id')).toHaveText(book.id);
  await page.screenshot({ path: 'tests/screenshots/task4-02-book-detail.png' });
});

test('shows the backend error message when creation fails', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 429, {
    detail: 'you already have 3 book(s) in progress',
  });

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('new-book-error')).toHaveText('you already have 3 book(s) in progress');
});
