import React, { useEffect, useState } from 'react';
import { getOutline, putOutline, ApiError } from '../lib/api';
import { Chapter, ChapterEdit } from '../types';
import { StateMessage } from './StateMessage';

interface OutlineEditorProps {
  bookId: string;
  onSaved: () => void;
}

export const OutlineEditor: React.FC<OutlineEditorProps> = ({ bookId, onSaved }) => {
  const [chapters, setChapters] = useState<Chapter[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    getOutline(bookId)
      .then(setChapters)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Could not load outline'));
  }, [bookId]);

  const toggle = (chapterId: string, field: 'skip' | 'locked') => {
    setChapters((prev) =>
      prev
        ? prev.map((c) => (c.id === chapterId ? { ...c, [field]: !c[field] } : c))
        : prev
    );
  };

  const handleSave = async () => {
    if (!chapters) return;
    setIsSaving(true);
    setError(null);
    const edits: ChapterEdit[] = chapters.map((c) => ({ id: c.id, skip: c.skip, locked: c.locked }));
    try {
      await putOutline(bookId, edits);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save outline');
      setIsSaving(false);
    }
  };

  if (error && !chapters) {
    return <StateMessage variant="error" message={error} />;
  }

  if (!chapters) {
    return <StateMessage variant="loading" message="Loading outline..." />;
  }

  return (
    <div className="w-full pb-28">
      <h2 className="font-headline-sm text-headline-sm text-primary font-semibold mb-1">
        Review outline
      </h2>
      <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-md">
        Lock chapters you don't want changed, skip chapters you don't want in the book, then save
        to start rendering.
      </p>

      <div className="flex flex-col gap-space-sm">
        {[...chapters]
          .sort((a, b) => a.order - b.order)
          .map((chapter) => (
            <article
              key={chapter.id}
              data-testid={`outline-chapter-${chapter.id}`}
              className={`bg-surface-container-lowest rounded-xl p-space-md shadow-sm border border-[#e3e2df]/60 ${
                chapter.skip ? 'opacity-60' : ''
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <span className="font-label-sm text-label-sm text-secondary font-medium">
                    CHAPTER {String(chapter.order).padStart(2, '0')}
                  </span>
                  <h3
                    className={`font-headline-sm text-headline-sm text-primary leading-snug font-medium ${
                      chapter.skip ? 'line-through' : ''
                    }`}
                  >
                    {chapter.title}
                  </h3>
                  {chapter.source_video_ids.length > 0 && (
                    <p className="font-label-sm text-label-sm text-outline mt-1">
                      {chapter.source_video_ids.length} source video
                      {chapter.source_video_ids.length === 1 ? '' : 's'}
                    </p>
                  )}
                </div>
              </div>

              <div className="flex items-center flex-wrap gap-2 mt-space-sm">
                <button
                  data-testid={`outline-lock-${chapter.id}`}
                  onClick={() => toggle(chapter.id, 'locked')}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-md font-label-sm text-label-sm transition-colors ${
                    chapter.locked
                      ? 'bg-surface-container text-on-surface'
                      : 'bg-surface hover:bg-surface-container text-on-surface-variant'
                  }`}
                >
                  <span className="material-symbols-outlined text-[16px] text-primary">
                    {chapter.locked ? 'lock' : 'lock_open'}
                  </span>
                  {chapter.locked ? 'Locked' : 'Unlocked'}
                </button>

                <button
                  data-testid={`outline-skip-${chapter.id}`}
                  onClick={() => toggle(chapter.id, 'skip')}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-surface hover:bg-surface-container text-on-surface-variant font-label-sm text-label-sm transition-colors"
                >
                  <span className="material-symbols-outlined text-[16px]">
                    {chapter.skip ? 'undo' : 'visibility_off'}
                  </span>
                  {chapter.skip ? 'Restore' : 'Skip'}
                </button>
              </div>
            </article>
          ))}
      </div>

      {error && <StateMessage variant="error" message={error} />}

      <div className="fixed bottom-16 left-0 right-0 z-40 px-gutter-mobile py-space-sm bg-surface/90 backdrop-blur-md border-t border-[#e3e2df]/60">
        <div className="max-w-lg mx-auto">
          <button
            data-testid="outline-save"
            onClick={handleSave}
            disabled={isSaving}
            className="w-full py-3 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-title-md text-title-md font-semibold flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[20px]">auto_stories</span>
            {isSaving ? 'Saving...' : 'Save & generate PDF'}
          </button>
        </div>
      </div>
    </div>
  );
};
