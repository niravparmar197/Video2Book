import React, { useEffect, useRef, useState } from 'react';
import {
  getBook,
  retryBook,
  cancelBook,
  deleteBook,
  downloadPdf,
  downloadBookFile,
  ApiError,
  type BookFileFormat,
} from '../lib/api';
import { ACTIVE_STATUSES, bookTitle } from '../lib/book';
import { Book } from '../types';
import { OutlineEditor } from './OutlineEditor';
import { ProgressView } from './ProgressView';
import { StateMessage } from './StateMessage';

interface BookDetailScreenProps {
  bookId: string;
  /** Called after the book was deleted, so the app can leave this screen. */
  onDeleted?: () => void;
}

/** The worker is making the book: it must be cancelled before deleting. */
const BEING_MADE: Book['status'][] = ['planning', 'rendering'];

const POLL_INTERVAL_MS = 4000;

function formatCost(usd: number): string {
  return `$${usd.toFixed(2)}`;
}

function formatCreatedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
}

export const BookDetailScreen: React.FC<BookDetailScreenProps> = ({ bookId, onDeleted }) => {
  const [book, setBook] = useState<Book | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isConfirmingCancel, setIsConfirmingCancel] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refetch = () => {
    getBook(bookId)
      .then(setBook)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not load book'));
  };

  useEffect(() => {
    refetch();
    pollRef.current = setInterval(refetch, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId]);

  useEffect(() => {
    if (book && (book.status === 'done' || book.status === 'failed') && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, [book]);

  const handleRetry = async () => {
    setIsRetrying(true);
    setError(null);
    try {
      const updated = await retryBook(bookId);
      setBook(updated);
      pollRef.current = setInterval(refetch, POLL_INTERVAL_MS);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not retry book');
    } finally {
      setIsRetrying(false);
    }
  };

  const handleCancelConfirm = async () => {
    setIsCancelling(true);
    setError(null);
    try {
      const updated = await cancelBook(bookId);
      setBook(updated);
      setIsConfirmingCancel(false);
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not cancel book');
    } finally {
      setIsCancelling(false);
    }
  };

  const handleDeleteConfirm = async () => {
    setIsDeleting(true);
    setError(null);
    try {
      await deleteBook(bookId);
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      onDeleted?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not delete book');
      setIsDeleting(false);
    }
  };

  const handleDownload = async () => {
    setIsDownloading(true);
    setError(null);
    try {
      await downloadPdf(bookId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not download PDF');
    } finally {
      setIsDownloading(false);
    }
  };

  const handleDownloadFile = async (format: BookFileFormat) => {
    setError(null);
    try {
      await downloadBookFile(bookId, format);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `Could not download ${format}`);
    }
  };

  if (error && !book) {
    return <StateMessage variant="error" message={error} />;
  }

  if (!book) {
    return <StateMessage variant="loading" message="Loading..." />;
  }

  return (
    <div className="w-full pb-24">
      <div className="bg-surface-container-lowest rounded-xl p-space-md border border-[#e3e2df]/60 shadow-sm mb-space-md">
        <h2
          data-testid="book-detail-title"
          className="font-headline-sm text-headline-sm text-primary font-semibold truncate"
        >
          {bookTitle(book)}
        </h2>
        <p data-testid="book-detail-id" className="font-mono text-[12px] text-on-surface-variant truncate mt-1">
          {book.id}
        </p>
        <div className="flex flex-wrap items-center gap-space-sm mt-space-sm font-body-sm text-body-sm text-on-surface-variant">
          {book.url && (
            <a
              data-testid="book-detail-url"
              href={book.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-secondary underline underline-offset-2 truncate max-w-full"
            >
              {book.url}
            </a>
          )}
          {typeof book.estimated_cost_usd === 'number' && (
            <span data-testid="book-detail-cost">{formatCost(book.estimated_cost_usd)}</span>
          )}
          {book.created_at && (
            <span data-testid="book-detail-created-at">{formatCreatedAt(book.created_at)}</span>
          )}
        </div>
        {ACTIVE_STATUSES.includes(book.status) &&
          (isConfirmingCancel ? (
            <div
              data-testid="book-detail-cancel-confirm"
              className="mt-space-sm flex items-center flex-wrap gap-space-sm"
            >
              <span className="font-body-sm text-body-sm text-on-surface-variant">
                Cancel this book?
              </span>
              <div className="flex items-center gap-1.5 shrink-0">
                <button
                  data-testid="book-detail-cancel-confirm-yes"
                  onClick={handleCancelConfirm}
                  disabled={isCancelling}
                  className="px-2.5 py-1.5 rounded-md bg-error-container hover:bg-error-container/70 text-on-error-container font-label-sm text-label-sm font-medium transition-colors disabled:opacity-50"
                >
                  {isCancelling ? 'Cancelling...' : 'Yes, cancel'}
                </button>
                <button
                  data-testid="book-detail-cancel-confirm-no"
                  onClick={() => setIsConfirmingCancel(false)}
                  disabled={isCancelling}
                  className="px-2.5 py-1.5 rounded-md bg-surface-container hover:bg-surface-container-lowest text-on-surface-variant font-label-sm text-label-sm font-medium transition-colors disabled:opacity-50"
                >
                  Never mind
                </button>
              </div>
            </div>
          ) : (
            <button
              data-testid="book-detail-cancel"
              onClick={() => setIsConfirmingCancel(true)}
              className="mt-space-sm flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-error-container/40 hover:bg-error-container/70 text-on-error-container font-label-sm text-label-sm font-medium transition-colors"
            >
              <span className="material-symbols-outlined text-[16px]">cancel</span>
              Cancel
            </button>
          ))}
      </div>

      {(book.status === 'queued' || book.status === 'planning' || book.status === 'rendering') && (
        <ProgressView bookId={bookId} onTerminal={refetch} />
      )}

      {book.status === 'outline_ready' && (
        <OutlineEditor bookId={bookId} onSaved={refetch} />
      )}

      {book.status === 'done' && (
        <div className="bg-surface-container-lowest rounded-xl p-space-md border border-[#e3e2df]/60 shadow-sm text-center">
          <span className="material-symbols-outlined text-[32px] text-secondary mb-2 block">
            check_circle
          </span>
          <h2 className="font-headline-sm text-headline-sm text-primary font-semibold mb-space-sm">
            Your book is ready
          </h2>
          <button
            data-testid="book-detail-download"
            onClick={handleDownload}
            disabled={isDownloading}
            className="py-2.5 px-5 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-title-md text-title-md font-semibold inline-flex items-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[20px]">download</span>
            {isDownloading ? 'Downloading...' : 'Download PDF'}
          </button>
          <div className="flex justify-center gap-space-sm mt-space-sm">
            <button
              data-testid="book-detail-download-epub"
              onClick={() => handleDownloadFile('epub')}
              className="py-1.5 px-3 rounded-lg border border-[#c1c8c3] text-primary font-label-sm text-label-sm hover:bg-surface-container"
            >
              E-book (EPUB)
            </button>
            <button
              data-testid="book-detail-download-md"
              onClick={() => handleDownloadFile('md')}
              className="py-1.5 px-3 rounded-lg border border-[#c1c8c3] text-primary font-label-sm text-label-sm hover:bg-surface-container"
            >
              Markdown
            </button>
          </div>
        </div>
      )}

      {book.status === 'failed' && (
        <div className="bg-error-container/40 rounded-xl p-space-md border border-error/30 text-center">
          <span className="material-symbols-outlined text-[32px] text-error mb-2 block">error</span>
          <h2 className="font-headline-sm text-headline-sm text-primary font-semibold mb-1">
            Something went wrong
          </h2>
          {book.error_message && (
            <p
              data-testid="book-detail-error-message"
              className="font-body-sm text-body-sm text-on-surface-variant mb-space-sm"
            >
              {book.error_message}
            </p>
          )}
          <button
            data-testid="book-detail-retry"
            onClick={handleRetry}
            disabled={isRetrying}
            className="py-2.5 px-5 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-title-md text-title-md font-semibold inline-flex items-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[20px]">refresh</span>
            {isRetrying ? 'Retrying...' : 'Retry'}
          </button>
        </div>
      )}

      {!BEING_MADE.includes(book.status) && (
        <div className="mt-space-md text-center">
          {isConfirmingDelete ? (
            <div
              data-testid="book-detail-delete-confirm"
              className="inline-flex flex-col items-center gap-2 bg-error-container/40 rounded-lg p-3 border border-error/30"
            >
              <span className="font-body-sm text-body-sm text-primary">
                Delete this book and all its files? This cannot be undone.
              </span>
              <div className="flex gap-2">
                <button
                  data-testid="book-detail-delete-confirm-yes"
                  onClick={handleDeleteConfirm}
                  disabled={isDeleting}
                  className="py-1.5 px-3 rounded-lg bg-error text-on-error font-label-sm text-label-sm font-semibold disabled:opacity-50"
                >
                  {isDeleting ? 'Deleting...' : 'Yes, delete'}
                </button>
                <button
                  data-testid="book-detail-delete-confirm-no"
                  onClick={() => setIsConfirmingDelete(false)}
                  disabled={isDeleting}
                  className="py-1.5 px-3 rounded-lg border border-[#c1c8c3] text-primary font-label-sm text-label-sm"
                >
                  Keep it
                </button>
              </div>
            </div>
          ) : (
            <button
              data-testid="book-detail-delete"
              onClick={() => setIsConfirmingDelete(true)}
              className="inline-flex items-center gap-1 py-1.5 px-3 rounded-lg text-error font-label-sm text-label-sm hover:bg-error-container/40"
            >
              <span className="material-symbols-outlined text-[16px]">delete</span>
              Delete book
            </button>
          )}
        </div>
      )}

      {error && <StateMessage variant="error" message={error} />}
    </div>
  );
};
