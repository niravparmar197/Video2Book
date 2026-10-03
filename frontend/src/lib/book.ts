import type { Book, BookStatus } from '../types';

// Statuses a book can still be cancelled from (BookDetailScreen) or that
// count as "in progress" for the My Books status filter -- the same
// non-terminal set, used by both.
export const ACTIVE_STATUSES: BookStatus[] = ['queued', 'planning', 'outline_ready', 'rendering'];

export function bookTitle(book: Book): string {
  return book.videos?.[0]?.title || book.url || book.id;
}
