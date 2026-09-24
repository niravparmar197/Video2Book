import type { Page } from '@playwright/test';

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
