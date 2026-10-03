import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, makeBook, seedTrackedBooks, mockJson, API_BASE } from './mocks';

test('typing a title substring narrows to just the matching book', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await seedTrackedBooks(page, ['book-a', 'book-b']);

  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-a`,
    200,
    makeBook({
      id: 'book-a',
      status: 'done',
      url: 'https://www.youtube.com/watch?v=aaa',
      videos: [{ video_id: 'aaa', title: 'Deep Learning Fundamentals', duration_seconds: 600 }],
    })
  );
  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-b`,
    200,
    makeBook({
      id: 'book-b',
      status: 'done',
      url: 'https://www.youtube.com/watch?v=bbb',
      videos: [{ video_id: 'bbb', title: 'Intro to Cooking', duration_seconds: 600 }],
    })
  );

  await page.getByTestId('nav-tab-books').click();
  await page.getByTestId('my-books-search-input').fill('deep learning');

  await expect(page.getByTestId('my-books-row-book-a')).toBeVisible();
  await expect(page.getByTestId('my-books-row-book-b')).toHaveCount(0);
  await page.screenshot({ path: 'tests/screenshots/v9-task5-01-search-narrowed.png' });
});

test('a search matching a url or id (not the title) still finds the book', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await seedTrackedBooks(page, ['book-url-match', 'book-other']);

  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-url-match`,
    200,
    makeBook({ id: 'book-url-match', status: 'done', url: 'https://www.youtube.com/watch?v=distinctive-slug' })
  );
  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-other`,
    200,
    makeBook({ id: 'book-other', status: 'done', url: 'https://www.youtube.com/watch?v=zzz' })
  );

  await page.getByTestId('nav-tab-books').click();
  await page.getByTestId('my-books-search-input').fill('distinctive-slug');
  await expect(page.getByTestId('my-books-row-book-url-match')).toBeVisible();
  await expect(page.getByTestId('my-books-row-book-other')).toHaveCount(0);

  await page.getByTestId('my-books-search-input').fill('book-other');
  await expect(page.getByTestId('my-books-row-book-other')).toBeVisible();
  await expect(page.getByTestId('my-books-row-book-url-match')).toHaveCount(0);
});

test('search combines with the status filter (AND, not OR)', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await seedTrackedBooks(page, ['book-done-match', 'book-failed-match']);

  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-done-match`,
    200,
    makeBook({
      id: 'book-done-match',
      status: 'done',
      url: 'https://www.youtube.com/watch?v=match1',
      videos: [{ video_id: 'match1', title: 'Rust Tutorial', duration_seconds: 600 }],
    })
  );
  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-failed-match`,
    200,
    makeBook({
      id: 'book-failed-match',
      status: 'failed',
      url: 'https://www.youtube.com/watch?v=match2',
      videos: [{ video_id: 'match2', title: 'Rust Advanced', duration_seconds: 600 }],
    })
  );

  await page.getByTestId('nav-tab-books').click();
  await page.getByTestId('my-books-filter-done').click();
  await page.getByTestId('my-books-search-input').fill('rust');

  await expect(page.getByTestId('my-books-row-book-done-match')).toBeVisible();
  await expect(page.getByTestId('my-books-row-book-failed-match')).toHaveCount(0);

  // Filter tab counts stay status-only, unaffected by the search text.
  await expect(page.getByTestId('my-books-filter-all')).toContainText('All (2)');
  await expect(page.getByTestId('my-books-filter-done')).toContainText('Done (1)');
});

test('a search with zero matches shows a search-specific empty state', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);
  await seedTrackedBooks(page, ['book-only']);

  await mockJson(
    page,
    'GET',
    `${API_BASE}/books/book-only`,
    200,
    makeBook({
      id: 'book-only',
      status: 'done',
      url: 'https://www.youtube.com/watch?v=only',
      videos: [{ video_id: 'only', title: 'Something Else', duration_seconds: 600 }],
    })
  );

  await page.getByTestId('nav-tab-books').click();
  await page.getByTestId('my-books-search-input').fill('nonexistent term');

  await expect(page.getByTestId('my-books-search-empty')).toBeVisible();
  await expect(page.getByTestId('my-books-search-empty')).toContainText('No books match "nonexistent term".');
  await expect(page.getByTestId('my-books-filter-empty')).toHaveCount(0);
  await page.screenshot({ path: 'tests/screenshots/v9-task5-02-search-empty.png' });

  // Clearing the search restores the row.
  await page.getByTestId('my-books-search-input').fill('');
  await expect(page.getByTestId('my-books-row-book-only')).toBeVisible();
});
