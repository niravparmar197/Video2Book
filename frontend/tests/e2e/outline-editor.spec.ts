import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, mockJson, API_BASE } from './mocks';

test('toggle skip/lock on chapters and save the outline', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-outline-1';
  const outlineReadyBook = { id: bookId, status: 'outline_ready', pdf_path: null, error_message: null };
  const renderingBook = { id: bookId, status: 'rendering', pdf_path: null, error_message: null };

  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, outlineReadyBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, outlineReadyBook);

  const chapters = [
    { id: 'ch-1', title: 'Intro', order: 1, skip: false, locked: false, source_video_ids: ['v1'] },
    { id: 'ch-2', title: 'Deep Dive', order: 2, skip: false, locked: false, source_video_ids: ['v1', 'v2'] },
  ];
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}/outline`, 200, chapters);

  let putPayload: unknown = null;
  await page.route(`${API_BASE}/books/${bookId}/outline`, (route) => {
    if (route.request().method() !== 'PUT') return route.fallback();
    putPayload = route.request().postDataJSON();
    return route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify(renderingBook),
    });
  });

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('outline-chapter-ch-1')).toBeVisible();
  await page.screenshot({ path: 'tests/screenshots/task6-01-outline-loaded.png' });

  await page.getByTestId('outline-skip-ch-1').click();
  await page.getByTestId('outline-lock-ch-2').click();
  await page.screenshot({ path: 'tests/screenshots/task6-02-toggled.png' });

  await page.getByTestId('outline-save').click();

  await expect
    .poll(() => putPayload)
    .toEqual([
      { id: 'ch-1', skip: true, locked: false },
      { id: 'ch-2', skip: false, locked: true },
    ]);
});
