import type { Page } from '@playwright/test';
import type { Book } from '../../src/types';

/**
 * The base URL the app's fetch calls target (src/lib/api.ts's default when
 * VITE_API_BASE_URL isn't set). Tests never rely on a real backend being up.
 */
export const API_BASE = 'http://localhost:8000';

/**
 * Registers a safety-net route for every request under API_BASE: unless a
 * more specific page.route() is registered afterwards (Playwright runs the
 * most-recently-registered matching handler first), any call reaching the
 * mocked backend fails loudly instead of silently hitting the real network.
 */
export async function installApiMocks(page: Page): Promise<void> {
  await page.route(`${API_BASE}/**`, (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: `unmocked endpoint in test: ${route.request().method()} ${route.request().url()}` }),
    })
  );

  // index.html pulls Google Fonts over the real network. Under several
  // parallel workers that request queues up and page.screenshot()'s
  // internal "wait for fonts to load" step can exceed the test timeout --
  // block it so tests fall back to system fonts instantly instead of
  // depending on an external CDN's latency.
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) => route.abort());

  // GET /books (the user's book list) is empty unless seedTrackedBooks() says otherwise.
  await page.route(BOOK_LIST_URL, (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });
}

/** GET /books with or without a query string, never /books/<id>. */
const BOOK_LIST_URL = /^http:\/\/localhost:8000\/books(\?.*)?$/;

// Per page: the Book each test returns from GET /books/<id> via mockJson(),
// so the GET /books list can be answered with the same objects.
const mockedBooks = new WeakMap<Page, Map<string, unknown>>();

function booksFor(page: Page): Map<string, unknown> {
  let books = mockedBooks.get(page);
  if (!books) {
    books = new Map();
    mockedBooks.set(page, books);
  }
  return books;
}

/**
 * Registers a JSON response for one method + URL glob, layered on top of
 * installApiMocks()'s safety net. Register the most specific globs last --
 * Playwright resolves the most-recently-added matching route first.
 */
/**
 * Skips the login screen for tests that only care about a screen behind
 * it: sets the api key localStorage's LoginScreen would have set, then
 * reloads so App.tsx picks it up on mount.
 */
export async function loginAs(page: Page, apiKey = 'test-api-key'): Promise<void> {
  await page.goto('/');
  await page.evaluate((key) => localStorage.setItem('v2b_api_key', key), apiKey);
  await page.reload();
}

/**
 * The user's books for MyBooksScreen's GET /books: each id's Book is the one
 * the test mocks for GET /books/<id> with mockJson() (looked up when the list
 * is requested, so it may be mocked after this call). Ids with no 200 mock
 * are left out, as the server would.
 */
export async function seedTrackedBooks(page: Page, ids: string[]): Promise<void> {
  const books = booksFor(page);
  await page.route(BOOK_LIST_URL, (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    const list = ids.map((id) => books.get(id)).filter((book) => book !== undefined);
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(list) });
  });
}

/**
 * A fully-typed Book fixture with every field a real GET /books/{id}
 * response includes (sprint v2), so tests exercising metadata/filter/search
 * behavior don't each hand-roll their own partial object. Override only
 * what the test cares about.
 */
export function makeBook(overrides: Partial<Book> & Pick<Book, 'id'>): Book {
  return {
    status: 'queued',
    pdf_path: null,
    error_message: null,
    estimated_cost_usd: 0,
    url: '',
    created_at: '2026-01-01T00:00:00Z',
    videos: [],
    ...overrides,
  };
}

export async function mockJson(
  page: Page,
  method: string,
  urlGlob: string,
  status: number,
  body: unknown
): Promise<void> {
  const bookId = urlGlob.match(/^http:\/\/localhost:8000\/books\/([^/?*]+)$/)?.[1];
  if (method === 'GET' && status === 200 && bookId) booksFor(page).set(bookId, body);
  await page.route(urlGlob, (route) => {
    if (route.request().method() !== method) return route.fallback();
    return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  });
}
