import React, { useEffect, useMemo, useState } from 'react';
import { ApiError, listBooks } from '../lib/api';
import { ACTIVE_STATUSES, bookTitle } from '../lib/book';
import { FilterKey, getSavedFilter, setSavedFilter } from '../lib/myBooks';
import { Book } from '../types';
import { StateMessage } from './StateMessage';

interface MyBooksScreenProps {
  onSelectBook: (bookId: string) => void;
}

const STATUS_LABEL: Record<Book['status'], string> = {
  queued: 'Queued',
  planning: 'Planning outline',
  outline_ready: 'Outline ready for review',
  rendering: 'Rendering PDF',
  done: 'Done',
  failed: 'Failed',
};

const FILTERS: { key: FilterKey; label: string; testId: string; emptyLabel: string }[] = [
  { key: 'all', label: 'All', testId: 'my-books-filter-all', emptyLabel: '' },
  { key: 'in_progress', label: 'In Progress', testId: 'my-books-filter-in-progress', emptyLabel: 'in-progress' },
  { key: 'done', label: 'Done', testId: 'my-books-filter-done', emptyLabel: 'done' },
  { key: 'failed', label: 'Failed', testId: 'my-books-filter-failed', emptyLabel: 'failed' },
];

function matchesFilter(book: Book, filter: FilterKey): boolean {
  if (filter === 'all') return true;
  if (filter === 'in_progress') return ACTIVE_STATUSES.includes(book.status);
  return book.status === filter;
}

function matchesSearch(book: Book, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return (
    bookTitle(book).toLowerCase().includes(needle) ||
    book.url.toLowerCase().includes(needle) ||
    book.id.toLowerCase().includes(needle)
  );
}

function sortByCreatedAtDesc(books: Book[]): Book[] {
  return [...books].sort((a, b) => {
    const aTime = Date.parse(a.created_at);
    const bTime = Date.parse(b.created_at);
    const aValid = !Number.isNaN(aTime);
    const bValid = !Number.isNaN(bTime);
    if (!aValid && !bValid) return 0;
    if (!aValid) return 1;
    if (!bValid) return -1;
    return bTime - aTime;
  });
}

export const MyBooksScreen: React.FC<MyBooksScreenProps> = ({ onSelectBook }) => {
  const [books, setBooks] = useState<Book[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterKey>(() => getSavedFilter());
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    // From the server (GET /books), so the list is the same on every device.
    listBooks()
      .then(setBooks)
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : 'Could not reach the backend'))
      .finally(() => setIsLoading(false));
  }, []);

  const sortedBooks = useMemo(() => sortByCreatedAtDesc(books), [books]);
  const filteredBooks = useMemo(
    () => sortedBooks.filter((book) => matchesFilter(book, filter) && matchesSearch(book, searchQuery)),
    [sortedBooks, filter, searchQuery]
  );

  if (isLoading) {
    return <StateMessage variant="loading" message="Loading your books..." />;
  }

  if (loadError) {
    return <StateMessage variant="error" message={loadError} testId="my-books-error" />;
  }

  if (books.length === 0) {
    return (
      <StateMessage
        variant="empty"
        message='No books yet. Start one from the "New Book" tab.'
        testId="my-books-empty"
      />
    );
  }

  const activeFilter = FILTERS.find((f) => f.key === filter) ?? FILTERS[0];

  return (
    <div className="w-full pb-24">
      <h1 className="font-headline-lg-mobile text-headline-lg-mobile text-primary font-semibold mb-space-md">
        My Books
      </h1>

      <div
        data-testid="my-books-filters"
        className="flex items-center flex-wrap gap-space-sm mb-space-md"
      >
        {FILTERS.map(({ key, label, testId }) => {
          const count = sortedBooks.filter((book) => matchesFilter(book, key)).length;
          const isActive = filter === key;
          return (
            <button
              key={key}
              data-testid={testId}
              aria-pressed={isActive}
              onClick={() => {
                setFilter(key);
                setSavedFilter(key);
              }}
              className={`shrink-0 px-3 py-1.5 rounded-full font-label-sm text-label-sm font-medium transition-colors ${
                isActive
                  ? 'bg-primary-container text-on-primary'
                  : 'bg-surface-container text-on-surface-variant hover:bg-surface-container-lowest'
              }`}
            >
              {label} ({count})
            </button>
          );
        })}
      </div>

      <input
        data-testid="my-books-search-input"
        type="search"
        placeholder="Search by title, url, or id..."
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        className="w-full mb-space-md px-3 py-2.5 bg-white border border-[#c1c8c3] rounded-lg text-body-md text-primary focus:outline-none focus:border-[#006c49]"
      />

      {filteredBooks.length === 0 && searchQuery.trim() !== '' ? (
        <StateMessage
          variant="empty"
          message={`No books match "${searchQuery.trim()}".`}
          testId="my-books-search-empty"
        />
      ) : filteredBooks.length === 0 ? (
        <StateMessage
          variant="empty"
          message={`No ${activeFilter.emptyLabel} books.`}
          testId="my-books-filter-empty"
        />
      ) : (
        <div className="flex flex-col gap-space-sm">
          {filteredBooks.map((book) => (
            <button
              key={book.id}
              data-testid={`my-books-row-${book.id}`}
              onClick={() => onSelectBook(book.id)}
              className="text-left bg-surface-container-lowest rounded-xl p-space-md shadow-sm border border-[#e3e2df]/60 hover:border-[#c1c8c3] transition-colors"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-body-md text-body-md text-primary truncate">{bookTitle(book)}</p>
                  <p className="font-mono text-[11px] text-on-surface-variant truncate">{book.id}</p>
                </div>
                <span
                  data-testid={`my-books-status-${book.id}`}
                  className={`shrink-0 px-2 py-0.5 rounded-full font-label-sm text-label-sm font-medium ${
                    book.status === 'done'
                      ? 'bg-secondary-container text-on-secondary-fixed'
                      : book.status === 'failed'
                      ? 'bg-error-container text-on-error-container'
                      : 'bg-surface-container text-on-surface-variant'
                  }`}
                >
                  {STATUS_LABEL[book.status]}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
