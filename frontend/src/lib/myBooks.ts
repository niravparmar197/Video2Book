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
    // the filter simply won't persist this session.
  }
}

// App.tsx keeps "which screen am I on" (New Book / My Books / a specific
// book's detail view) in plain React state with no URL routing, so a full
// page refresh wiped it and dropped the user back on New Book -- losing
// their place on an in-flight book entirely, not just resetting its
// elapsed-time display (that part was already correct: the backend
// computes elapsed_seconds from the graph's checkpoint history, which
// survives a reconnect fine). Persisting the current view here means a
// refresh resumes exactly where the user was instead of looking like the
// whole run restarted.
export interface SavedView {
  activeTab: 'new' | 'books';
  selectedBookId: string | null;
}

const VIEW_STORAGE_KEY = 'v2b_current_view';

export function getSavedView(): SavedView | null {
  try {
    const raw = localStorage.getItem(VIEW_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<SavedView>;
    if (parsed.activeTab !== 'new' && parsed.activeTab !== 'books') return null;
    return {
      activeTab: parsed.activeTab,
      selectedBookId: typeof parsed.selectedBookId === 'string' ? parsed.selectedBookId : null,
    };
  } catch {
    return null;
  }
}

export function setSavedView(view: SavedView): void {
  try {
    localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify(view));
  } catch {
    // localStorage unavailable -- the view simply won't persist this
    // session, same degradation as the other helpers in this file.
  }
}
