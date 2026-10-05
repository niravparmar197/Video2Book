import { test, expect, Page, Locator } from '@playwright/test';
import { installApiMocks, mockJson, seedTrackedBooks, API_BASE } from './mocks';

const VIEWPORT_WIDTH = 375;
test.use({ viewport: { width: VIEWPORT_WIDTH, height: 667 } });

async function assertNoHorizontalScroll(page: Page): Promise<void> {
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(VIEWPORT_WIDTH);
}

async function assertFullyInViewport(locator: Locator): Promise<void> {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(VIEWPORT_WIDTH);
}

test('core flow stays within a 375px-wide viewport with no horizontal scroll', async ({ page }) => {
  await installApiMocks(page);

  // Login
  await page.goto('/');
  await assertNoHorizontalScroll(page);
  for (const testId of ['login-tab-register', 'login-tab-paste', 'login-email-input', 'login-register-submit']) {
    await assertFullyInViewport(page.getByTestId(testId));
  }

  await mockJson(page, 'POST', `${API_BASE}/users`, 201, { user_id: 'user-1', api_key: 'test-key-mobile' });
  await page.getByTestId('login-email-input').fill('dev@example.com');
  await page.getByTestId('login-accept-terms').check();
  await page.getByTestId('login-register-submit').click();
  await assertNoHorizontalScroll(page);
  await assertFullyInViewport(page.getByTestId('login-continue-button'));
  await page.getByTestId('login-continue-button').click();

  // New book
  await assertNoHorizontalScroll(page);
  for (const testId of ['new-book-url-input', 'new-book-submit']) {
    await assertFullyInViewport(page.getByTestId(testId));
  }
  await page.screenshot({ path: 'tests/screenshots/task10-01-new-book-mobile.png' });

  // My Books (empty state)
  await page.getByTestId('nav-tab-books').click();
  await assertNoHorizontalScroll(page);
  await assertFullyInViewport(page.getByTestId('my-books-empty'));
  await page.screenshot({ path: 'tests/screenshots/task10-02-my-books-mobile.png' });

  // Outline editor -- deliberately long chapter title to stress-test wrapping
  await page.getByTestId('nav-tab-new').click();
  const bookId = 'book-mobile-1';
  const outlineReadyBook = { id: bookId, status: 'outline_ready', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, outlineReadyBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, outlineReadyBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}/outline`, 200, [
    {
      id: 'ch-1',
      title: 'A Fairly Long Chapter Title That Could Wrap Awkwardly On A Narrow Phone Screen',
      order: 1,
      skip: false,
      locked: false,
      source_video_ids: ['v1'],
    },
  ]);

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('outline-chapter-ch-1')).toBeVisible();
  await assertNoHorizontalScroll(page);
  for (const testId of ['outline-lock-ch-1', 'outline-skip-ch-1', 'outline-save']) {
    await assertFullyInViewport(page.getByTestId(testId));
  }
  await page.screenshot({ path: 'tests/screenshots/task10-03-outline-mobile.png' });

  // Book detail metadata card + cancel button (Sprint v2)
  await page.getByTestId('nav-tab-new').click();
  const inFlightBookId = 'book-mobile-2';
  const inFlightBook = {
    id: inFlightBookId,
    status: 'rendering',
    pdf_path: null,
    error_message: null,
    estimated_cost_usd: 2.75,
    url: 'https://www.youtube.com/watch?v=a-fairly-long-video-id-string',
    created_at: '2026-03-15T00:00:00Z',
    videos: [{ video_id: 'a-fairly-long-video-id-string', title: 'A Fairly Long Video Title That Could Wrap On Mobile', duration_seconds: 1200 }],
  };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, inFlightBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${inFlightBookId}`, 200, inFlightBook);

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=a-fairly-long-video-id-string');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('book-detail-title')).toBeVisible();
  await assertNoHorizontalScroll(page);
  for (const testId of ['book-detail-title', 'book-detail-id', 'book-detail-url', 'book-detail-cost', 'book-detail-created-at', 'book-detail-cancel']) {
    await assertFullyInViewport(page.getByTestId(testId));
  }
  await page.screenshot({ path: 'tests/screenshots/v2-task8-01-book-detail-metadata-mobile.png' });

  // Cancel confirmation row (Sprint v6)
  await page.getByTestId('book-detail-cancel').click();
  await expect(page.getByTestId('book-detail-cancel-confirm')).toBeVisible();
  await assertNoHorizontalScroll(page);
  for (const testId of ['book-detail-cancel-confirm', 'book-detail-cancel-confirm-yes', 'book-detail-cancel-confirm-no']) {
    await assertFullyInViewport(page.getByTestId(testId));
  }
  await page.screenshot({ path: 'tests/screenshots/v6-task5-01-cancel-confirm-mobile.png' });
  await page.getByTestId('book-detail-cancel-confirm-no').click();

  // Per-chapter progress list (Sprint v3) -- long title + multi-attempt badge
  await page.getByTestId('nav-tab-new').click();
  const chaptersBookId = 'book-mobile-3';
  const chaptersBook = { id: chaptersBookId, status: 'queued', pdf_path: null, error_message: null };
  const chapterProgress = {
    current_node: 'write',
    completed_nodes: ['fetch', 'transcribe', 'outline'],
    chapters: [
      {
        id: 'ch-mobile-1',
        title: 'A Fairly Long Chapter Title That Could Wrap Awkwardly Next To Its Status Badges',
        status: 'done',
        score: 6,
        attempts: 3,
        passed: true,
      },
      { id: 'ch-mobile-2', title: 'A Second, Shorter Chapter', status: 'pending', score: null, attempts: null, passed: null },
      { id: 'ch-mobile-3', title: 'A Third Chapter That Needed Extra Attention', status: 'done', score: 4, attempts: 3, passed: false },
    ],
  };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, chaptersBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${chaptersBookId}`, 200, chaptersBook);
  await page.route(`${API_BASE}/books/${chaptersBookId}/events`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `event: progress\ndata: ${JSON.stringify(chapterProgress)}\n\n`,
    })
  );

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=mobile-chapters');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('progress-chapters')).toBeVisible();
  await assertNoHorizontalScroll(page);
  for (const testId of [
    'progress-chapters-count',
    'progress-chapters-bar',
    'progress-chapters-needs-review',
    'progress-chapters',
    'progress-chapter-ch-mobile-1',
    'progress-chapter-outcome-ch-mobile-1',
    'progress-chapter-attempts-ch-mobile-1',
    'progress-chapter-ch-mobile-2',
  ]) {
    await assertFullyInViewport(page.getByTestId(testId));
  }
  await page.screenshot({ path: 'tests/screenshots/v3-task6-01-chapter-progress-mobile.png' });

  // SSE reconnect indicator (Sprint v7)
  await page.getByTestId('nav-tab-new').click();
  const reconnectBookId = 'book-mobile-4';
  const reconnectBook = { id: reconnectBookId, status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, reconnectBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${reconnectBookId}`, 200, reconnectBook);
  let reconnectEventsCallCount = 0;
  await page.route(`${API_BASE}/books/${reconnectBookId}/events`, (route) => {
    reconnectEventsCallCount += 1;
    if (reconnectEventsCallCount === 1) {
      return route.fulfill({ status: 502, contentType: 'text/plain', body: 'bad gateway' });
    }
    return route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `event: progress\ndata: ${JSON.stringify({ current_node: 'transcribe', completed_nodes: ['fetch'] })}\n\n`,
    });
  });

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=mobile-reconnect');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('progress-reconnecting')).toBeVisible();
  await assertNoHorizontalScroll(page);
  await assertFullyInViewport(page.getByTestId('progress-reconnecting'));
  await page.screenshot({ path: 'tests/screenshots/v7-task6-01-reconnecting-mobile.png' });
  await expect(page.getByTestId('progress-current-node')).toHaveText('transcribe', { timeout: 8000 });

  // My Books filter tabs (Sprint v4)
  await seedTrackedBooks(page, ['book-mobile-filter-1', 'book-mobile-filter-2']);
  await mockJson(page, 'GET', `${API_BASE}/books/book-mobile-filter-1`, 200, {
    id: 'book-mobile-filter-1',
    status: 'rendering',
    pdf_path: null,
    error_message: null,
    estimated_cost_usd: 0,
    url: '',
    created_at: '2026-01-01T00:00:00Z',
    videos: [],
  });
  await mockJson(page, 'GET', `${API_BASE}/books/book-mobile-filter-2`, 200, {
    id: 'book-mobile-filter-2',
    status: 'done',
    pdf_path: 'books/book-mobile-filter-2.pdf',
    error_message: null,
    estimated_cost_usd: 0,
    url: '',
    created_at: '2026-01-02T00:00:00Z',
    videos: [],
  });

  await page.getByTestId('nav-tab-books').click();
  await assertNoHorizontalScroll(page);
  for (const testId of [
    'my-books-filter-all',
    'my-books-filter-in-progress',
    'my-books-filter-done',
    'my-books-filter-failed',
  ]) {
    await assertFullyInViewport(page.getByTestId(testId));
  }

  // My Books search input (Sprint v9)
  await assertFullyInViewport(page.getByTestId('my-books-search-input'));
  await page.getByTestId('my-books-search-input').fill('book-mobile-filter-2');
  await assertNoHorizontalScroll(page);
  await expect(page.getByTestId('my-books-row-book-mobile-filter-2')).toBeVisible();
  await expect(page.getByTestId('my-books-row-book-mobile-filter-1')).toHaveCount(0);
  await page.screenshot({ path: 'tests/screenshots/v9-task6-01-search-mobile.png' });
  await page.getByTestId('my-books-search-input').fill('');

  await page.getByTestId('my-books-filter-failed').click();
  await assertNoHorizontalScroll(page);
  await assertFullyInViewport(page.getByTestId('my-books-filter-empty'));
  await page.screenshot({ path: 'tests/screenshots/v4-task6-01-my-books-filter-mobile.png' });
});
