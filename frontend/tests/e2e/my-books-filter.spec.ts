import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, makeBook, seedTrackedBooks, mockJson, API_BASE } from './mocks';

test('sorts tracked books newest-first by created_at regardless of fetch order', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  // Seeded in an order that does NOT match created_at order, to prove the
  // component sorts rather than just preserving fetch/tracked order.
  await seedTrackedBooks(page, ['book-oldest', 'book-newest', 'book-middle']);

  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-oldest`,
    200,
    makeBook({ id: 'book-oldest', status: 'done', created_at: '2026-01-01T00:00:00Z' })
  );
  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-newest`,
    200,
    makeBook({ id: 'book-newest', status: 'done', created_at: '2026-03-01T00:00:00Z' })
  );
  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-middle`,
    200,
    makeBook({ id: 'book-middle', status: 'done', created_at: '2026-02-01T00:00:00Z' })
  );

  await page.getByTestId('nav-tab-books').click();

  const rowIds = await page.locator('[data-testid^="my-books-row-"]').evaluateAll((rows) =>
    rows.map((r) => r.getAttribute('data-testid'))
  );
  expect(rowIds).toEqual(['my-books-row-book-newest', 'my-books-row-book-middle', 'my-books-row-book-oldest']);
});

test('an invalid/empty created_at sorts last instead of crashing or sorting first', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await seedTrackedBooks(page, ['book-valid', 'book-invalid-date']);

  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-valid`,
    200,
    makeBook({ id: 'book-valid', status: 'done', created_at: '2026-01-01T00:00:00Z' })
  );
  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-invalid-date`,
    200,
    makeBook({ id: 'book-invalid-date', status: 'done', created_at: '' })
  );

  await page.getByTestId('nav-tab-books').click();

  const rowIds = await page.locator('[data-testid^="my-books-row-"]').evaluateAll((rows) =>
    rows.map((r) => r.getAttribute('data-testid'))
  );
  expect(rowIds).toEqual(['my-books-row-book-valid', 'my-books-row-book-invalid-date']);
});

test('status filter tabs narrow the list and show correct counts', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await seedTrackedBooks(page, ['book-queued', 'book-rendering', 'book-done', 'book-failed']);

  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-queued`,
    200,
    makeBook({ id: 'book-queued', status: 'queued', created_at: '2026-01-01T00:00:00Z' })
  );
  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-rendering`,
    200,
    makeBook({ id: 'book-rendering', status: 'rendering', created_at: '2026-01-02T00:00:00Z' })
  );
  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-done`,
    200,
    makeBook({ id: 'book-done', status: 'done', created_at: '2026-01-03T00:00:00Z' })
  );
  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-failed`,
    200,
    makeBook({ id: 'book-failed', status: 'failed', created_at: '2026-01-04T00:00:00Z' })
  );

  await page.getByTestId('nav-tab-books').click();

  await expect(page.getByTestId('my-books-filter-all')).toContainText('All (4)');
  await expect(page.getByTestId('my-books-filter-in-progress')).toContainText('In Progress (2)');
  await expect(page.getByTestId('my-books-filter-done')).toContainText('Done (1)');
  await expect(page.getByTestId('my-books-filter-failed')).toContainText('Failed (1)');
  await expect(page.getByTestId('my-books-filter-all')).toHaveAttribute('aria-pressed', 'true');

  await page.getByTestId('my-books-filter-in-progress').click();
  await expect(page.getByTestId('my-books-filter-in-progress')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('my-books-row-book-queued')).toBeVisible();
  await expect(page.getByTestId('my-books-row-book-rendering')).toBeVisible();
  await expect(page.getByTestId('my-books-row-book-done')).toHaveCount(0);
  await expect(page.getByTestId('my-books-row-book-failed')).toHaveCount(0);
  await page.screenshot({ path: 'tests/screenshots/v4-task4-01-filter-in-progress.png' });

  await page.getByTestId('my-books-filter-done').click();
  await expect(page.getByTestId('my-books-row-book-done')).toBeVisible();
  await expect(page.getByTestId('my-books-row-book-queued')).toHaveCount(0);

  await page.getByTestId('my-books-filter-failed').click();
  await expect(page.getByTestId('my-books-row-book-failed')).toBeVisible();
  await expect(page.getByTestId('my-books-row-book-done')).toHaveCount(0);

  await page.getByTestId('my-books-filter-all').click();
  for (const id of ['book-queued', 'book-rendering', 'book-done', 'book-failed']) {
    await expect(page.getByTestId(`my-books-row-${id}`)).toBeVisible();
  }
});

test('shows a filter-aware empty state when a tab has no matching books', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await seedTrackedBooks(page, ['book-only-done']);

  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-only-done`,
    200,
    makeBook({ id: 'book-only-done', status: 'done', created_at: '2026-01-01T00:00:00Z' })
  );

  await page.getByTestId('nav-tab-books').click();
  await page.getByTestId('my-books-filter-failed').click();

  await expect(page.getByTestId('my-books-filter-empty')).toBeVisible();
  await expect(page.getByTestId('my-books-filter-empty')).toContainText('failed');
  await expect(page.getByTestId('my-books-empty')).toHaveCount(0);
  await page.screenshot({ path: 'tests/screenshots/v4-task4-02-filter-empty.png' });
});
