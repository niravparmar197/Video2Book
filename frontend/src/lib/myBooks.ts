// The backend has no "list my books" endpoint, so the set of books a user
// has created is tracked client-side. This is a convenience index only --
// GET /books/{id} on the backend remains the source of truth for status.
const STORAGE_KEY = 'v2b_my_book_ids';

export function getTrackedBookIds(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

export function addTrackedBookId(id: string): void {
  const ids = getTrackedBookIds();
  if (!ids.includes(id)) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([id, ...ids]));
  }
}

export type FilterKey = 'all' | 'in_progress' | 'done' | 'failed';

const FILTER_STORAGE_KEY = 'v2b_my_books_filter';
const KNOWN_FILTER_KEYS: FilterKey[] = ['all', 'in_progress', 'done', 'failed'];

export function getSavedFilter(): FilterKey {
  try {
    const raw = localStorage.getItem(FILTER_STORAGE_KEY);
    return (KNOWN_FILTER_KEYS as string[]).includes(raw ?? '') ? (raw as FilterKey) : 'all';
  } catch {
    return 'all';
  }
}

export function setSavedFilter(key: FilterKey): void {
  try {
    localStorage.setItem(FILTER_STORAGE_KEY, key);
  } catch {
    // localStorage unavailable (private browsing, blocked site data) --
    // the filter simply won't persist this session, same degradation as
    // getTrackedBookIds()/addTrackedBookId() above.
  }
}
