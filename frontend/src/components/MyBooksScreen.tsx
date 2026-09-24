import React, { useEffect, useState } from 'react';
import { getBook } from '../lib/api';
import { getTrackedBookIds } from '../lib/myBooks';
import { Book } from '../types';

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

export const MyBooksScreen: React.FC<MyBooksScreenProps> = ({ onSelectBook }) => {
  const [books, setBooks] = useState<Book[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const ids = getTrackedBookIds();
    if (ids.length === 0) {
      setIsLoading(false);
      return;
    }
    Promise.all(
      ids.map((id) =>
        getBook(id).catch<Book>(() => ({ id, status: 'failed', pdf_path: null, error_message: 'not found' }))
      )
    ).then((results) => {
      setBooks(results);
      setIsLoading(false);
    });
  }, []);

  if (isLoading) {
    return <p className="font-body-sm text-body-sm text-on-surface-variant pt-4">Loading...</p>;
  }

  if (books.length === 0) {
    return (
      <div className="pt-8 text-center">
        <p className="font-body-md text-body-md text-on-surface-variant">
          No books yet. Start one from the "New Book" tab.
        </p>
      </div>
    );
  }

  return (
    <div className="w-full pb-24">
      <h1 className="font-headline-lg-mobile text-headline-lg-mobile text-primary font-semibold mb-space-md">
        My Books
      </h1>
      <div className="flex flex-col gap-space-sm">
        {books.map((book) => (
          <button
            key={book.id}
            onClick={() => onSelectBook(book.id)}
            className="text-left bg-surface-container-lowest rounded-xl p-space-md shadow-sm border border-[#e3e2df]/60 hover:border-[#c1c8c3] transition-colors"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[12px] text-on-surface-variant truncate">{book.id}</span>
              <span
                className={`px-2 py-0.5 rounded-full font-label-sm text-label-sm font-medium ${
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
    </div>
  );
};
