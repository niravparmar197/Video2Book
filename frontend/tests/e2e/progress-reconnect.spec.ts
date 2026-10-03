import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, mockJson, API_BASE } from './mocks';

test('shows a reconnecting indicator after a stream failure, then clears once it recovers', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-reconnect-1';
  const queuedBook = { id: bookId, status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, queuedBook);

  let eventsCallCount = 0;
  const recoveredProgress = { current_node: 'transcribe', completed_nodes: ['fetch'] };
  await page.route(`${API_BASE}/books/${bookId}/events`, (route) => {
    eventsCallCount += 1;
    if (eventsCallCount === 1) {
      return route.fulfill({ status: 502, contentType: 'text/plain', body: 'bad gateway' });
    }
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `event: progress\ndata: ${JSON.stringify(recoveredProgress)}\n\n`,
    });
  });

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  // First attempt fails immediately -- no progress has ever been received,
  // so the reconnecting state shows via the loading StateMessage's text.
  await expect(page.getByTestId('progress-reconnecting')).toBeVisible();
  await expect(page.getByTestId('progress-reconnecting')).toContainText('Reconnecting...');
  await page.screenshot({ path: 'tests/screenshots/v7-task5-01-reconnecting-pre-progress.png' });

  // The retry (after RECONNECT_DELAY_MS) succeeds and the indicator clears.
  await expect(page.getByTestId('progress-current-node')).toHaveText('transcribe', { timeout: 8000 });
  await expect(page.getByTestId('progress-reconnecting')).not.toBeVisible();
  await expect.poll(() => eventsCallCount).toBeGreaterThanOrEqual(2);
});

test('a genuine network-level failure (not just a non-2xx response) also triggers a reconnect', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-reconnect-2';
  const queuedBook = { id: bookId, status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, queuedBook);

  let eventsCallCount = 0;
  const recoveredProgress = { current_node: 'transcribe', completed_nodes: ['fetch'] };
  await page.route(`${API_BASE}/books/${bookId}/events`, (route) => {
    eventsCallCount += 1;
    if (eventsCallCount === 1) {
      // A network-level failure (connection reset), distinct from test 1's
      // non-2xx ApiError -- both must be treated as a genuine failure, not
      // confused with the AbortError a real unmount produces.
      return route.abort('connectionreset');
    }
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `event: progress\ndata: ${JSON.stringify(recoveredProgress)}\n\n`,
    });
  });

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('progress-reconnecting')).toBeVisible();
  await expect(page.getByTestId('progress-current-node')).toHaveText('transcribe', { timeout: 8000 });
  await expect(page.getByTestId('progress-reconnecting')).not.toBeVisible();
});

test('a clean stream end with no terminal event never triggers a reconnect (existing fixtures stay inert)', async ({
  page,
}) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-reconnect-3';
  const queuedBook = { id: bookId, status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, queuedBook);

  let eventsCallCount = 0;
  const sseBody =
    `event: progress\ndata: ${JSON.stringify({ current_node: 'fetch', completed_nodes: [] })}\n\n` +
    `event: progress\ndata: ${JSON.stringify({ current_node: 'transcribe', completed_nodes: ['fetch'] })}\n\n`;
  await page.route(`${API_BASE}/books/${bookId}/events`, (route) => {
    eventsCallCount += 1;
    return route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseBody });
  });

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('progress-current-node')).toHaveText('transcribe');

  // Wait comfortably longer than RECONNECT_DELAY_MS to prove no reconnect
  // fires for a clean, terminal-free stream end -- this is a negative
  // assertion (nothing should happen), so a real wait is unavoidable here.
  await page.waitForTimeout(3000);

  await expect(page.getByTestId('progress-reconnecting')).not.toBeVisible();
  expect(eventsCallCount).toBe(1);
});
