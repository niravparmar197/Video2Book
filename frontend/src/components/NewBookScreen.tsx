import React, { useState } from 'react';
import { createBook, ApiError, type BookGenre } from '../lib/api';
import { StateMessage } from './StateMessage';

interface NewBookScreenProps {
  onBookCreated: (bookId: string) => void;
}

export const NewBookScreen: React.FC<NewBookScreenProps> = ({ onBookCreated }) => {
  const [url, setUrl] = useState('');
  const [genre, setGenre] = useState<BookGenre>('auto');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const book = await createBook(url.trim(), genre);
      onBookCreated(book.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the backend');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="w-full pb-24">
      <h1 className="font-headline-lg-mobile text-headline-lg-mobile text-primary font-semibold mb-1">
        New book
      </h1>
      <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-md">
        Paste a YouTube video or playlist link. We'll plan the outline first, then you can review
        it before we render the PDF.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-space-sm">
        <input
          data-testid="new-book-url-input"
          type="url"
          required
          placeholder="https://www.youtube.com/watch?v=... or /playlist?list=..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="w-full px-3 py-2.5 bg-white border border-[#c1c8c3] rounded-lg text-body-md text-primary focus:outline-none focus:border-[#006c49]"
        />
        <label className="flex flex-col gap-1 font-body-sm text-body-sm text-on-surface-variant">
          Book type
          <select
            data-testid="new-book-genre-select"
            value={genre}
            onChange={(e) => setGenre(e.target.value as BookGenre)}
            className="w-full px-3 py-2.5 bg-white border border-[#c1c8c3] rounded-lg text-body-md text-primary focus:outline-none focus:border-[#006c49]"
          >
            <option value="auto">Auto-detect from the video</option>
            <option value="lecture">Study notes (lesson, tutorial, course)</option>
            <option value="podcast">Podcast notes (interview, conversation)</option>
            <option value="comedy">Comedy recap (stand-up, comedy show)</option>
          </select>
        </label>
        <button
          data-testid="new-book-submit"
          type="submit"
          disabled={isSubmitting}
          className="w-full py-3 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-title-md text-title-md font-semibold flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-[20px]">auto_stories</span>
          {isSubmitting ? 'Starting...' : 'Start book'}
        </button>
      </form>

      {error && <StateMessage variant="error" message={error} testId="new-book-error" />}
    </div>
  );
};
