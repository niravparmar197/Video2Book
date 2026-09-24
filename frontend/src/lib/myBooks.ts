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
