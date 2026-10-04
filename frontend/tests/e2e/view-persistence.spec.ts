import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, mockJson, API_BASE } from './mocks';

test('a page refresh while viewing a book detail screen returns to that same book, not New Book', async ({
  page,
}) => {
  await installApiMocks(page);
  await loginAs(page);

  const book = { id: 'book-refresh-1', status: 'rendering', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, book);
  await mockJson(page, 'GET', `${API_BASE}/books/${book.id}`, 200, book);
  await page.route(`${API_BASE}/books/${book.id}/events`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `event: progress\ndata: ${JSON.stringify({
        current_node: 'write',
        completed_nodes: ['fetch', 'chunk'],
        chapters: [],
        warnings: [],
        percent: 40,
        elapsed_seconds: 90,
      })}\n\n`,
    })
  );

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();
  await expect(page.getByTestId('book-detail-id')).toHaveText(book.id);

  await page.reload();

  // Still on the same book's detail screen, not bounced back to New Book.
  await expect(page.getByTestId('book-detail-id')).toHaveText(book.id);
  await expect(page.getByRole('heading', { name: 'New book' })).not.toBeVisible();
});

test('a page refresh on the My Books tab stays on My Books, not New Book', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  await page.getByTestId('nav-tab-books').click();
  await expect(page.getByTestId('my-books-empty')).toBeVisible();

  await page.reload();

  await expect(page.getByRole('heading', { name: 'New book' })).not.toBeVisible();
});
