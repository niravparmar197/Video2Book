import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, makeBook, mockJson, API_BASE } from './mocks';

test('a finished book can be deleted after confirming, and the app returns to My Books', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-delete-1';
  const book = makeBook({ id: bookId, status: 'done', url: 'https://www.youtube.com/watch?v=deleteme' });
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, book);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, book);
  let deleteCalled = false;
  await page.route(`${API_BASE}/books/${bookId}`, (route) => {
    if (route.request().method() !== 'DELETE') return route.fallback();
    deleteCalled = true;
    return route.fulfill({ status: 204, body: '' });
  });

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=deleteme');
  await page.getByTestId('new-book-submit').click();

  await page.getByTestId('book-detail-delete').click();
  await expect(page.getByTestId('book-detail-delete-confirm')).toBeVisible();
  expect(deleteCalled).toBe(false);

  await page.getByTestId('book-detail-delete-confirm-yes').click();

  await expect.poll(() => deleteCalled).toBe(true);
  await expect(page.getByTestId('my-books-empty')).toBeVisible();
});

test('a book being made has no delete button', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-running-1';
  const book = makeBook({ id: bookId, status: 'rendering', url: 'https://www.youtube.com/watch?v=busy' });
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, book);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, book);
  await page.route(`${API_BASE}/books/${bookId}/events`, (route) =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
  );

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=busy');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('book-detail-title')).toBeVisible();
  await expect(page.getByTestId('book-detail-delete')).toHaveCount(0);
});

test('the account screen gives a new key and deletes the account', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page, 'old-key');
  await mockJson(page, 'POST', `${API_BASE}/users/me/api-key`, 200, { api_key: 'new-key', expires_at: null });
  let deleted = false;
  await page.route(`${API_BASE}/users/me`, (route) => {
    if (route.request().method() !== 'DELETE') return route.fallback();
    deleted = true;
    return route.fulfill({ status: 204, body: '' });
  });

  await page.getByTestId('header-account').click();
  await page.getByTestId('account-rotate-key').click();

  await expect(page.getByTestId('account-new-key')).toHaveText('new-key');
  expect(await page.evaluate(() => localStorage.getItem('v2b_api_key'))).toBe('new-key');

  await page.getByTestId('account-delete').click();
  await page.getByTestId('account-delete-confirm-yes').click();

  await expect.poll(() => deleted).toBe(true);
  await expect(page.getByTestId('login-email-input')).toBeVisible();
});
