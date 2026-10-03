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

/** Seeds the client-side "my books" index MyBooksScreen reads from. */
export async function seedTrackedBooks(page: Page, ids: string[]): Promise<void> {
  await page.evaluate((ids) => localStorage.setItem('v2b_my_book_ids', JSON.stringify(ids)), ids);
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
  await page.route(urlGlob, (route) => {
    if (route.request().method() !== method) return route.fallback();
    return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  });
}
