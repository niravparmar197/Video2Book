import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, mockJson, API_BASE } from './mocks';

test('done book shows a working download button', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-done-1';
  const doneBook = { id: bookId, status: 'done', pdf_path: 'books/book-done-1.pdf', error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, doneBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, doneBook);
  await page.route(`${API_BASE}/books/${bookId}/pdf`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/pdf', body: Buffer.from('%PDF-1.4 fake') })
  );

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('book-detail-download')).toBeVisible();
  await page.screenshot({ path: 'tests/screenshots/task7-01-done.png' });

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByTestId('book-detail-download').click(),
  ]);
  expect(download.suggestedFilename()).toBe(`${bookId}.pdf`);
});

test('failed book shows the error message and a working retry button', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-failed-1';
  const failedBook = { id: bookId, status: 'failed', pdf_path: null, error_message: 'LLM provider unavailable' };
  const retriedBook = { id: bookId, status: 'queued', pdf_path: null, error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, failedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, failedBook);

  let retryCalled = false;
  await page.route(`${API_BASE}/books/${bookId}/retry`, (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    retryCalled = true;
    return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(retriedBook) });
  });

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('book-detail-error-message')).toHaveText('LLM provider unavailable');
  await page.screenshot({ path: 'tests/screenshots/task7-02-failed.png' });

  await page.getByTestId('book-detail-retry').click();

  await expect.poll(() => retryCalled).toBe(true);
  await expect(page.getByTestId('book-detail-error-message')).not.toBeVisible();
});

test('a done book can also be downloaded as EPUB and Markdown', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-done-formats';
  const doneBook = { id: bookId, status: 'done', pdf_path: 'x/book.pdf', error_message: null };
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, doneBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, doneBook);
  await page.route(`${API_BASE}/books/${bookId}/download/epub`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/epub+zip', body: Buffer.from('PK epub') })
  );
  await page.route(`${API_BASE}/books/${bookId}/download/md`, (route) =>
    route.fulfill({ status: 200, contentType: 'text/markdown', body: '# Book' })
  );

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=abc');
  await page.getByTestId('new-book-submit').click();
  await expect(page.getByTestId('book-detail-download-epub')).toBeVisible();
  await page.screenshot({ path: 'tests/screenshots/book-formats-01-done.png' });

  const [epub] = await Promise.all([page.waitForEvent('download'), page.getByTestId('book-detail-download-epub').click()]);
  expect(epub.suggestedFilename()).toBe(`${bookId}.epub`);
  const [md] = await Promise.all([page.waitForEvent('download'), page.getByTestId('book-detail-download-md').click()]);
  expect(md.suggestedFilename()).toBe(`${bookId}.md`);
});
