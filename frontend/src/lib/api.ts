import type { Book, Chapter, ChapterEdit, ProgressEvent } from '../types';

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const API_KEY_STORAGE_KEY = 'v2b_api_key';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getApiKey(): string | null {
  return localStorage.getItem(API_KEY_STORAGE_KEY);
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE_KEY, key);
}

export function clearApiKey(): void {
  localStorage.removeItem(API_KEY_STORAGE_KEY);
}

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; auth?: boolean } = {}
): Promise<T> {
  const { method = 'GET', body, auth = true } = options;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (auth) {
    const key = getApiKey();
    if (key) headers['X-API-Key'] = key;
  }

  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ?? detail;
    } catch {
      // response wasn't JSON; keep statusText
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function registerUser(
  email: string,
  acceptTerms: boolean,
  inviteCode?: string
): Promise<{ user_id: string; api_key: string }> {
  return request('/users', {
    method: 'POST',
    body: { email, accept_terms: acceptTerms, invite_code: inviteCode || null },
    auth: false,
  });
}

/** A new key for this account; the old one stops working at once. */
export function rotateApiKey(): Promise<{ api_key: string; expires_at: string | null }> {
  return request('/users/me/api-key', { method: 'POST' });
}

/** Deletes the account and every book in it, with all their files. */
export function deleteAccount(): Promise<void> {
  return request('/users/me', { method: 'DELETE' });
}

/** The user's books, newest first, from the server (any device). */
export function listBooks(limit = 100): Promise<Book[]> {
  return request(`/books?limit=${limit}`);
}

/** Deletes a book and everything stored for it. */
export function deleteBook(bookId: string): Promise<void> {
  return request(`/books/${bookId}`, { method: 'DELETE' });
}

/** The kind of book: `auto` lets the backend decide from the video. */
export type BookGenre = 'auto' | 'lecture' | 'podcast' | 'comedy';

export function createBook(url: string, genre: BookGenre = 'auto'): Promise<Book> {
  return request('/books/youtube', { method: 'POST', body: { url, genre } });
}

export function getBook(bookId: string): Promise<Book> {
  return request(`/books/${bookId}`);
}

export function getOutline(bookId: string): Promise<Chapter[]> {
  return request(`/books/${bookId}/outline`);
}

export function putOutline(bookId: string, edits: ChapterEdit[]): Promise<Book> {
  return request(`/books/${bookId}/outline`, { method: 'PUT', body: edits });
}

export function retryBook(bookId: string): Promise<Book> {
  return request(`/books/${bookId}/retry`, { method: 'POST' });
}

export function cancelBook(bookId: string): Promise<Book> {
  return request(`/books/${bookId}/cancel`, { method: 'POST' });
}

export async function downloadPdf(bookId: string): Promise<void> {
  const key = getApiKey();
  const res = await fetch(`${API_BASE_URL}/books/${bookId}/pdf`, {
    headers: key ? { 'X-API-Key': key } : {},
  });
  if (!res.ok) {
    throw new ApiError(res.status, 'PDF is not available yet');
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = `${bookId}.pdf`;
  a.click();
  URL.revokeObjectURL(objectUrl);
}

/** The book as an e-book (EPUB) or Markdown, written next to the PDF. */
export type BookFileFormat = 'epub' | 'md';

export async function downloadBookFile(bookId: string, format: BookFileFormat): Promise<void> {
  const key = getApiKey();
  const res = await fetch(`${API_BASE_URL}/books/${bookId}/download/${format}`, {
    headers: key ? { 'X-API-Key': key } : {},
  });
  if (!res.ok) {
    throw new ApiError(res.status, `${format === 'epub' ? 'EPUB' : 'Markdown'} is not available for this book`);
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = `${bookId}.${format}`;
  a.click();
  URL.revokeObjectURL(objectUrl);
}

/**
 * Consumes the book's SSE progress stream (GET /books/{id}/events).
 * Calling code owns the AbortController and stops the stream by aborting it.
 */
export async function streamEvents(
  bookId: string,
  onProgress: (event: ProgressEvent) => void,
  onTerminal: (status: 'done' | 'failed') => void,
  signal: AbortSignal
): Promise<void> {
  const key = getApiKey();
  const res = await fetch(`${API_BASE_URL}/books/${bookId}/events`, {
    headers: key ? { 'X-API-Key': key } : {},
    signal,
  });
  if (!res.ok || !res.body) {
    throw new ApiError(res.status, 'could not open progress stream');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });

    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() ?? '';

    for (const chunk of chunks) {
      const lines = chunk.split('\n');
      const eventLine = lines.find((l) => l.startsWith('event: '));
      const dataLine = lines.find((l) => l.startsWith('data: '));
      if (!eventLine || !dataLine) continue;

      const event = eventLine.slice('event: '.length).trim();
      const data = JSON.parse(dataLine.slice('data: '.length));

      if (event === 'progress') onProgress(data as ProgressEvent);
      else if (event === 'done' || event === 'failed') {
        onTerminal(event);
        return;
      }
    }
  }
}
