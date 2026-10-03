import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, mockJson, API_BASE } from './mocks';

async function startBookWithProgress(
  page: import('@playwright/test').Page,
  bookId: string,
  progressData: unknown
) {
  const queuedBook = { id: bookId, status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, queuedBook);
  const sseBody = `event: progress\ndata: ${JSON.stringify(progressData)}\n\n`;
  await page.route(`${API_BASE}/books/${bookId}/events`, (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseBody })
  );
  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();
}

test('shows a partial count and proportional bar width while chapters are in progress', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  await startBookWithProgress(page, 'book-summary-1', {
    current_node: 'write',
    completed_nodes: ['fetch', 'transcribe', 'outline'],
    chapters: [
      { id: 'ch-1', title: 'One', status: 'done', score: 9, attempts: 1, passed: true },
      { id: 'ch-2', title: 'Two', status: 'pending', score: null, attempts: null, passed: null },
      { id: 'ch-3', title: 'Three', status: 'pending', score: null, attempts: null, passed: null },
      { id: 'ch-4', title: 'Four', status: 'pending', score: null, attempts: null, passed: null },
    ],
  });

  await expect(page.getByTestId('progress-chapters-count')).toHaveText('1 of 4 chapters done');
  await expect(page.getByTestId('progress-chapters-bar')).toHaveAttribute('aria-valuenow', '25');
  await expect(page.getByTestId('progress-chapters-bar-fill')).toHaveAttribute('style', /width:\s*25%/);
  await expect(page.getByTestId('progress-chapters-needs-review')).not.toBeVisible();
  await page.screenshot({ path: 'tests/screenshots/v5-task1-01-partial-summary.png' });
});

test('shows 100% with no needs-review callout when everything passed', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  await startBookWithProgress(page, 'book-summary-2', {
    current_node: 'write',
    completed_nodes: ['fetch', 'transcribe', 'outline'],
    chapters: [
      { id: 'ch-1', title: 'One', status: 'done', score: 9, attempts: 1, passed: true },
      { id: 'ch-2', title: 'Two', status: 'done', score: 8, attempts: 2, passed: true },
    ],
  });

  await expect(page.getByTestId('progress-chapters-count')).toHaveText('2 of 2 chapters done');
  await expect(page.getByTestId('progress-chapters-bar')).toHaveAttribute('aria-valuenow', '100');
  await expect(page.getByTestId('progress-chapters-needs-review')).not.toBeVisible();
});

test('shows a needs-review callout when a finished chapter did not pass', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  await startBookWithProgress(page, 'book-summary-3', {
    current_node: 'write',
    completed_nodes: ['fetch', 'transcribe', 'outline'],
    chapters: [
      { id: 'ch-1', title: 'One', status: 'done', score: 9, attempts: 1, passed: true },
      { id: 'ch-2', title: 'Two', status: 'done', score: 4, attempts: 3, passed: false },
      { id: 'ch-3', title: 'Three', status: 'done', score: 3, attempts: 3, passed: false },
    ],
  });

  await expect(page.getByTestId('progress-chapters-count')).toHaveText('3 of 3 chapters done');
  await expect(page.getByTestId('progress-chapters-needs-review')).toHaveText('2 need review');
  await page.screenshot({ path: 'tests/screenshots/v5-task3-01-needs-review-summary.png' });
});

test('shows no summary before any chapters exist (pre-outline progress)', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  await startBookWithProgress(page, 'book-summary-4', {
    current_node: 'fetch',
    completed_nodes: [],
  });

  await expect(page.getByTestId('progress-current-node')).toHaveText('fetch');
  await expect(page.getByTestId('progress-chapters-count')).not.toBeVisible();
  await expect(page.getByTestId('progress-chapters-bar')).not.toBeVisible();
  await expect(page.getByTestId('progress-chapters-needs-review')).not.toBeVisible();
});
