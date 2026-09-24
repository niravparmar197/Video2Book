import React, { useEffect, useRef, useState } from 'react';
import { getBook, retryBook, downloadPdf, ApiError } from '../lib/api';
import { Book } from '../types';
import { OutlineEditor } from './OutlineEditor';
import { ProgressView } from './ProgressView';

interface BookDetailScreenProps {
  bookId: string;
}

const POLL_INTERVAL_MS = 4000;

export const BookDetailScreen: React.FC<BookDetailScreenProps> = ({ bookId }) => {
  const [book, setBook] = useState<Book | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
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

  if (error && !book) {
    return <p className="font-body-sm text-body-sm text-error pt-4">{error}</p>;
  }

  if (!book) {
    return <p className="font-body-sm text-body-sm text-on-surface-variant pt-4">Loading...</p>;
  }

  return (
    <div className="w-full pb-24">
      <p data-testid="book-detail-id" className="font-mono text-[12px] text-on-surface-variant mb-space-md truncate">
        {book.id}
      </p>

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
            onClick={handleDownload}
            disabled={isDownloading}
            className="py-2.5 px-5 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-title-md text-title-md font-semibold inline-flex items-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[20px]">download</span>
            {isDownloading ? 'Downloading...' : 'Download PDF'}
          </button>
        </div>
      )}

      {book.status === 'failed' && (
        <div className="bg-error-container/40 rounded-xl p-space-md border border-error/30 text-center">
          <span className="material-symbols-outlined text-[32px] text-error mb-2 block">error</span>
          <h2 className="font-headline-sm text-headline-sm text-primary font-semibold mb-1">
            Something went wrong
          </h2>
          {book.error_message && (
            <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-sm">
              {book.error_message}
            </p>
          )}
          <button
            onClick={handleRetry}
            disabled={isRetrying}
            className="py-2.5 px-5 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-title-md text-title-md font-semibold inline-flex items-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[20px]">refresh</span>
            {isRetrying ? 'Retrying...' : 'Retry'}
          </button>
        </div>
      )}

      {error && <p className="mt-space-sm font-body-sm text-body-sm text-error">{error}</p>}
    </div>
  );
};
