import { test, expect } from '@playwright/test';
import { installApiMocks, loginAs, makeBook, mockJson, API_BASE } from './mocks';

test('cancel button appears for in-flight books and transitions to the failed state', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-cancel-1';
  const queuedBook = makeBook({ id: bookId, status: 'queued', url: 'https://www.youtube.com/watch?v=cancelme' });
  const cancelledBook = makeBook({ ...queuedBook, status: 'failed', error_message: 'Cancelled by user' });

  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, queuedBook);

  let cancelCalled = false;
  await page.route(`${API_BASE}/books/${bookId}/cancel`, (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    cancelCalled = true;
    return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(cancelledBook) });
  });

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=cancelme');
  await page.getByTestId('new-book-submit').click();

  const cancelButton = page.getByTestId('book-detail-cancel');
  await expect(cancelButton).toBeVisible();
  await cancelButton.click();

  // First click only reveals the confirmation -- no API call yet.
  await expect(page.getByTestId('book-detail-cancel-confirm')).toBeVisible();
  await expect(page.getByTestId('book-detail-cancel')).not.toBeVisible();
  expect(cancelCalled).toBe(false);
  await page.screenshot({ path: 'tests/screenshots/v6-task4-01-cancel-confirm.png' });

  await page.getByTestId('book-detail-cancel-confirm-yes').click();

  await expect.poll(() => cancelCalled).toBe(true);
  await expect(page.getByTestId('book-detail-error-message')).toHaveText('Cancelled by user');
  await expect(page.getByTestId('book-detail-cancel')).not.toBeVisible();
  await expect(page.getByTestId('book-detail-cancel-confirm')).not.toBeVisible();
});

test('"Never mind" dismisses the confirmation without cancelling the book', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const bookId = 'book-cancel-nevermind';
  const queuedBook = makeBook({ id: bookId, status: 'queued', url: 'https://www.youtube.com/watch?v=cancelme' });

  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, queuedBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${bookId}`, 200, queuedBook);

  let cancelCalled = false;
  await page.route(`${API_BASE}/books/${bookId}/cancel`, (route) => {
    cancelCalled = true;
    return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(queuedBook) });
  });

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=cancelme');
  await page.getByTestId('new-book-submit').click();

  await page.getByTestId('book-detail-cancel').click();
  await expect(page.getByTestId('book-detail-cancel-confirm')).toBeVisible();

  await page.getByTestId('book-detail-cancel-confirm-no').click();

  await expect(page.getByTestId('book-detail-cancel-confirm')).not.toBeVisible();
  await expect(page.getByTestId('book-detail-cancel')).toBeVisible();
  expect(cancelCalled).toBe(false);

  // The plain Cancel button still works after a "Never mind".
  await page.getByTestId('book-detail-cancel').click();
  await expect(page.getByTestId('book-detail-cancel-confirm')).toBeVisible();
});

test('cancel button is hidden for done and failed books', async ({ page }) => {
  await installApiMocks(page);
  await loginAs(page);

  const doneBookId = 'book-done-cancel';
  const doneBook = makeBook({ id: doneBookId, status: 'done' });
  await mockJson(page, 'POST', `${API_BASE}/books/youtube`, 201, doneBook);
  await mockJson(page, 'GET', `${API_BASE}/books/${doneBookId}`, 200, doneBook);

  await page.getByTestId('new-book-url-input').fill('https://www.youtube.com/watch?v=done');
  await page.getByTestId('new-book-submit').click();

  await expect(page.getByTestId('book-detail-download')).toBeVisible();
  await expect(page.getByTestId('book-detail-cancel')).not.toBeVisible();
});
