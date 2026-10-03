import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, mockJson, API_BASE } from './mocks';

test('book detail metadata card renders title, source link, cost, and created date', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-meta-1';
  const book = {
    id: bookId,
    status: 'rendering',
    pdf_path: null,
    error_message: null,
    estimated_cost_usd: 4.5,
    url: 'https://www.youtube.com/watch?v=abc123',
    created_at: '2026-03-15T00:00:00Z',
    videos: [{ video_id: 'abc123', title: 'Deep Learning Fundamentals', duration_seconds: 3600 }],
  };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, book);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, book);

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc123');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('book-detail-title')).toHaveText('Deep Learning Fundamentals');
  await expect(page.getByTestId('book-detail-id')).toHaveText(bookId);

  const link = page.getByTestId('book-detail-url');
  await expect(link).toHaveText('https://www.youtube.com/watch?v=abc123');
  await expect(link).toHaveAttribute('href', 'https://www.youtube.com/watch?v=abc123');
  await expect(link).toHaveAttribute('target', '_blank');
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer');

  await expect(page.getByTestId('book-detail-cost')).toHaveText('$4.50');
  await expect(page.getByTestId('book-detail-created-at')).toHaveText('March 15, 2026');
  await page.screenshot({ path: 'tests/screenshots/v2-task7-01-metadata-card.png' });
});
