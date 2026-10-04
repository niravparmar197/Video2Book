import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, mockJson, API_BASE } from './mocks';

test('shows a warnings banner when the pipeline logged a non-fatal degradation', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-warnings-1';
  const queuedBook = { id: bookId, status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, queuedBook);

  const progressData = {
    current_node: 'write',
    completed_nodes: ['fetch', 'chunk', 'topics'],
    chapters: [],
    warnings: [
      {
        ts: '2026-09-25T12:00:00+00:00',
        logger: 'app.nodes.topics',
        message:
          'topics extraction for vid1 chunk 0 produced no usable JSON array after a retry; continuing with an empty topics list',
      },
    ],
  };
  const sseBody = `event: progress\ndata: ${JSON.stringify(progressData)}\n\n`;
  await page.route(`${API_BASE}/books/${bookId}/events`, (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseBody })
  );

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  const banner = page.getByTestId('progress-warnings');
  await expect(banner).toBeVisible();
  await expect(banner).toContainText('1 warning during processing');
  await expect(page.getByTestId('progress-warning-0')).toContainText(
    'produced no usable JSON array'
  );

  await page.screenshot({ path: 'tests/screenshots/v11-task1-01-progress-warnings.png' });
});

test('shows no warnings banner when the pipeline has nothing to report', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-warnings-2';
  const queuedBook = { id: bookId, status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, queuedBook);

  const progressData = {
    current_node: 'write',
    completed_nodes: ['fetch', 'chunk', 'topics'],
    chapters: [],
    warnings: [],
  };
  const sseBody = `event: progress\ndata: ${JSON.stringify(progressData)}\n\n`;
  await page.route(`${API_BASE}/books/${bookId}/events`, (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseBody })
  );

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('progress-current-node')).toHaveText('write');
  await expect(page.getByTestId('progress-warnings')).not.toBeVisible();
});
