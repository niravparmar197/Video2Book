import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, mockJson, API_BASE } from './mocks';

test('shows live progress from the SSE stream', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-progress-1';
  const queuedBook = { id: bookId, status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, queuedBook);

  // No terminal event -- the stream just stays "open" with two cumulative
  // progress events, so the test observes progress rendering in isolation
  // instead of racing a near-instant hand-off to the terminal state
  // (mocked responses resolve far faster than a real pipeline run would).
  const sseBody =
    `event: progress\ndata: ${JSON.stringify({ current_node: 'fetch', completed_nodes: [] })}\n\n` +
    `event: progress\ndata: ${JSON.stringify({ current_node: 'transcribe', completed_nodes: ['fetch'] })}\n\n`;
  await page.route(`${API_BASE}/books/${bookId}/events`, (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseBody })
  );

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('progress-current-node')).toHaveText('transcribe');
  await expect(page.getByTestId('progress-completed-nodes')).toContainText('fetch');
  await expect(page.getByTestId('book-detail-download')).not.toBeVisible();
  await page.screenshot({ path: 'tests/screenshots/task8-01-progress.png' });
});

test('hands off to the done state when the stream reports terminal', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-progress-2';
  const queuedBook = { id: bookId, status: 'queued', pdf_path: null, error_message: null };
  const doneBook = { id: bookId, status: 'done', pdf_path: 'books/book-progress-2.pdf', error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);

  let getBookCallCount = 0;
  await page.route(`${API_BASE}/books/${bookId}`, (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    getBookCallCount += 1;
    const body = getBookCallCount === 1 ? queuedBook : doneBook;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  const sseBody = `event: done\ndata: ${JSON.stringify({ status: 'done' })}\n\n`;
  await page.route(`${API_BASE}/books/${bookId}/events`, (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseBody })
  );

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('book-detail-download')).toBeVisible();
  await page.screenshot({ path: 'tests/screenshots/task8-02-done-after-progress.png' });
});
