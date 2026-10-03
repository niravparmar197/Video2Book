import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, seedTrackedBooks, mockJson, API_BASE } from './mocks';

test('My Books row title falls back through video title, url, then id', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await seedTrackedBooks(page, ['book-with-title', 'book-with-url-only', 'book-with-neither']);

  await mockJson(page, 'GET', `${API_BASE}/books/book-with-title`, 200, {
    id: 'book-with-title',
    status: 'done',
    pdf_path: 'books/book-with-title.pdf',
    error_message: null,
    estimated_cost_usd: 1.23,
    url: 'https://www.youtube.com/watch?v=has-title',
    created_at: '2026-01-01T00:00:00Z',
    videos: [{ video_id: 'v1', title: 'Intro to Testing', duration_seconds: 600 }],
  });
  await mockJson(page, 'GET', `${API_BASE}/books/book-with-url-only`, 200, {
    id: 'book-with-url-only',
    status: 'queued',
    pdf_path: null,
    error_message: null,
    estimated_cost_usd: 0,
    url: 'https://www.youtube.com/watch?v=no-title-yet',
    created_at: '2026-01-02T00:00:00Z',
    videos: [],
  });
  await mockJson(page, 'GET', `${API_BASE}/books/book-with-neither`, 200, {
    id: 'book-with-neither',
    status: 'failed',
    pdf_path: null,
    error_message: 'boom',
    estimated_cost_usd: 0,
    url: '',
    created_at: '2026-01-03T00:00:00Z',
    videos: [],
  });

  await page.getByTestId('nav-tab-books').click();

  const titledRow = page.getByTestId('my-books-row-book-with-title');
  await expect(titledRow).toContainText('Intro to Testing');
  await expect(titledRow).toContainText('book-with-title');

  const urlOnlyRow = page.getByTestId('my-books-row-book-with-url-only');
  await expect(urlOnlyRow).toContainText('https://www.youtube.com/watch?v=no-title-yet');
  await expect(urlOnlyRow).toContainText('book-with-url-only');

  const neitherRow = page.getByTestId('my-books-row-book-with-neither');
  await expect(neitherRow).toContainText('book-with-neither');

  // Existing status testids/assertions keep working unmodified.
  await expect(titledRow).toContainText('Done');
  await expect(urlOnlyRow).toContainText('Queued');
  await expect(neitherRow).toContainText('Failed');
});
