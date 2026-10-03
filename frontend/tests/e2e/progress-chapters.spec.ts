import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, mockJson, API_BASE } from './mocks';

test('renders a mixed set of pending/passed/multi-attempt chapters from the SSE stream', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-chapters-1';
  const queuedBook = { id: bookId, status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, queuedBook);

  const progressData = {
    current_node: 'write',
    completed_nodes: ['fetch', 'transcribe', 'outline'],
    chapters: [
      { id: 'ch-1', title: 'Introduction', status: 'done', score: 9, attempts: 1, passed: true },
      { id: 'ch-2', title: 'Deep Dive', status: 'done', score: 6, attempts: 3, passed: true },
      { id: 'ch-3', title: 'Conclusion', status: 'pending', score: null, attempts: null, passed: null },
    ],
  };
  const sseBody = `event: progress\ndata: ${JSON.stringify(progressData)}\n\n`;
  await page.route(`${API_BASE}/books/${bookId}/events`, (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseBody })
  );

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('progress-current-node')).toHaveText('write');

  const ch1 = page.getByTestId('progress-chapter-ch-1');
  await expect(ch1).toContainText('Introduction');
  await expect(page.getByTestId('progress-chapter-outcome-ch-1')).toContainText('Passed');
  await expect(page.getByTestId('progress-chapter-outcome-ch-1')).toContainText('9');
  await expect(page.getByTestId('progress-chapter-attempts-ch-1')).not.toBeVisible();

  const ch2 = page.getByTestId('progress-chapter-ch-2');
  await expect(ch2).toContainText('Deep Dive');
  await expect(page.getByTestId('progress-chapter-outcome-ch-2')).toContainText('Passed');
  await expect(page.getByTestId('progress-chapter-attempts-ch-2')).toContainText('3 attempts');

  const ch3 = page.getByTestId('progress-chapter-ch-3');
  await expect(ch3).toContainText('Conclusion');
  await expect(page.getByTestId('progress-chapter-outcome-ch-3')).not.toBeVisible();
  await expect(page.getByTestId('progress-chapter-attempts-ch-3')).not.toBeVisible();

  await page.screenshot({ path: 'tests/screenshots/v3-task4-01-chapter-progress.png' });
});

test('renders a chapter that finished but did not pass', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-chapters-2';
  const queuedBook = { id: bookId, status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, queuedBook);

  const progressData = {
    current_node: 'write',
    completed_nodes: ['fetch', 'transcribe', 'outline'],
    chapters: [
      { id: 'ch-1', title: 'Rough Chapter', status: 'done', score: 4, attempts: 3, passed: false },
    ],
  };
  const sseBody = `event: progress\ndata: ${JSON.stringify(progressData)}\n\n`;
  await page.route(`${API_BASE}/books/${bookId}/events`, (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseBody })
  );

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('progress-chapter-outcome-ch-1')).toContainText('Needs review');
  await expect(page.getByTestId('progress-chapter-attempts-ch-1')).toContainText('3 attempts');
  await page.screenshot({ path: 'tests/screenshots/v3-task5-01-chapter-needs-review.png' });
});

test('shows no chapter list before any chapters exist (pre-outline progress)', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-chapters-3';
  const queuedBook = { id: bookId, status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, queuedBook);

  // Mirrors a real early-phase event: no chapters key at all yet, same as
  // pre-v3 payloads and the existing progress-view.spec.ts fixtures.
  const sseBody = `event: progress\ndata: ${JSON.stringify({ current_node: 'fetch', completed_nodes: [] })}\n\n`;
  await page.route(`${API_BASE}/books/${bookId}/events`, (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseBody })
  );

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('progress-current-node')).toHaveText('fetch');
  await expect(page.getByTestId('progress-chapters')).not.toBeVisible();
});
