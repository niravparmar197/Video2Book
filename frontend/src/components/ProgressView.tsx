import React, { useEffect, useRef, useState } from 'react';
import { streamEvents } from '../lib/api';
import { ChapterProgress, PipelineWarning, ProgressEvent } from '../types';
import { StateMessage } from './StateMessage';

interface ProgressViewProps {
  bookId: string;
  onTerminal: () => void;
}

const RECONNECT_DELAY_MS = 2000;
const ELAPSED_TICK_MS = 1000;

function isAbortError(err: unknown): boolean {
  return err instanceof Error && err.name === 'AbortError';
}

function formatElapsed(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes === 0) return `${remainingSeconds}s`;
  return `${minutes}m ${remainingSeconds}s`;
}

const OverallProgress: React.FC<{ percent: number; elapsedSeconds: number }> = ({
  percent,
  elapsedSeconds,
}) => (
  <div className="flex items-center justify-between gap-2 mb-space-sm">
    <div
      data-testid="progress-overall-bar"
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      className="flex-1 h-2 rounded-full bg-surface-container overflow-hidden"
    >
      <div
        data-testid="progress-overall-bar-fill"
        className="h-full rounded-full bg-primary transition-all"
        style={{ width: `${percent}%` }}
      />
    </div>
    <span
      data-testid="progress-overall-percent"
      className="font-label-sm text-label-sm text-on-surface-variant font-medium shrink-0"
    >
      {percent}%
    </span>
    <span
      data-testid="progress-elapsed"
      className="font-label-sm text-label-sm text-on-surface-variant font-medium shrink-0"
    >
      {formatElapsed(elapsedSeconds)}
    </span>
  </div>
);

const ChapterSummary: React.FC<{ chapters: ChapterProgress[] }> = ({ chapters }) => {
  const total = chapters.length;
  const done = chapters.filter((c) => c.status === 'done').length;
  const needsReview = chapters.filter((c) => c.status === 'done' && c.passed === false).length;
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div className="bg-surface-container-lowest rounded-xl p-space-md border border-[#e3e2df]/60 shadow-sm mt-space-md">
      <div className="flex items-center justify-between gap-2 flex-wrap mb-space-sm">
        <span
          data-testid="progress-chapters-count"
          className="font-title-md text-[14px] text-primary font-medium"
        >
          {done} of {total} chapters done
        </span>
        {needsReview > 0 && (
          <span
            data-testid="progress-chapters-needs-review"
            className="shrink-0 px-2 py-0.5 rounded-full bg-error-container text-on-error-container font-label-sm text-label-sm font-medium"
          >
            {needsReview} need{needsReview === 1 ? 's' : ''} review
          </span>
        )}
      </div>
      <div
        data-testid="progress-chapters-bar"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        className="w-full h-2 rounded-full bg-surface-container overflow-hidden"
      >
        <div
          data-testid="progress-chapters-bar-fill"
          className="h-full rounded-full bg-secondary transition-all"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
};

const WarningsBanner: React.FC<{ warnings: PipelineWarning[] }> = ({ warnings }) => {
  if (warnings.length === 0) return null;
  return (
    <div
      data-testid="progress-warnings"
      className="bg-error-container rounded-xl p-space-md border border-[#e3e2df]/60 shadow-sm mt-space-md"
    >
      <div className="flex items-center gap-2 mb-space-sm">
        <span className="material-symbols-outlined text-[18px] text-on-error-container">
          warning
        </span>
        <span className="font-title-md text-[14px] text-on-error-container font-medium">
          {warnings.length} {warnings.length === 1 ? 'warning' : 'warnings'} during processing
        </span>
      </div>
      <ul className="font-label-sm text-label-sm text-on-error-container space-y-1">
        {warnings.map((warning, index) => (
          <li key={`${warning.ts}-${index}`} data-testid={`progress-warning-${index}`}>
            {warning.message}
          </li>
        ))}
      </ul>
    </div>
  );
};

const ChapterRow: React.FC<{ chapter: ChapterProgress }> = ({ chapter }) => {
  const isDone = chapter.status === 'done';
  return (
    <div
      data-testid={`progress-chapter-${chapter.id}`}
      className="bg-surface-container-lowest rounded-xl p-space-md border border-[#e3e2df]/60 shadow-sm flex items-center justify-between gap-2"
    >
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={`material-symbols-outlined text-[18px] shrink-0 ${
            isDone ? 'text-secondary' : 'text-on-surface-variant'
          }`}
        >
          {isDone ? 'check_circle' : 'radio_button_unchecked'}
        </span>
        <span className="font-body-sm text-body-sm text-primary truncate">{chapter.title}</span>
      </div>

      {isDone && chapter.score !== null && (
        <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
          <span
            data-testid={`progress-chapter-outcome-${chapter.id}`}
            className={`px-2 py-0.5 rounded-full font-label-sm text-label-sm font-medium ${
              chapter.passed
                ? 'bg-secondary-container text-on-secondary-fixed'
                : 'bg-error-container text-on-error-container'
            }`}
          >
            {chapter.passed ? 'Passed' : 'Needs review'} · {chapter.score}
          </span>
          {chapter.attempts !== null && chapter.attempts > 1 && (
            <span
              data-testid={`progress-chapter-attempts-${chapter.id}`}
              className="px-2 py-0.5 rounded-full bg-surface-container text-on-surface-variant font-label-sm text-label-sm font-medium"
            >
              {chapter.attempts} attempts
            </span>
          )}
        </div>
      )}
    </div>
  );
};

export const ProgressView: React.FC<ProgressViewProps> = ({ bookId, onTerminal }) => {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [isReconnecting, setIsReconnecting] = useState(false);
  // The SSE stream only pushes an event when the node/chapter state
  // actually changes (no-op ticks aren't sent, per _progress_events'
  // dedup) -- elapsed_seconds would otherwise look frozen between real
  // state changes even though wall time keeps passing. A local 1s ticker
  // extrapolates forward from the last event's elapsed_seconds using
  // real elapsed wall time since it was received, so the displayed
  // timer keeps moving without needing the backend to push every second.
  const [displayedElapsed, setDisplayedElapsed] = useState(0);
  const lastEventRef = useRef<{ elapsedSeconds: number; receivedAtMs: number } | null>(null);

  useEffect(() => {
    if (!progress) return;
    const elapsedSeconds = progress.elapsed_seconds ?? 0;
    lastEventRef.current = { elapsedSeconds, receivedAtMs: Date.now() };
    setDisplayedElapsed(elapsedSeconds);

    const tick = () => {
      const last = lastEventRef.current;
      if (!last) return;
      const secondsSinceEvent = Math.floor((Date.now() - last.receivedAtMs) / 1000);
      setDisplayedElapsed(last.elapsedSeconds + secondsSinceEvent);
    };
    const interval = setInterval(tick, ELAPSED_TICK_MS);
    return () => clearInterval(interval);
  }, [progress]);

  useEffect(() => {
    let isActive = true;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController;

    const connect = () => {
      controller = new AbortController();
      streamEvents(
        bookId,
        (event) => {
          setProgress(event);
          setIsReconnecting(false);
        },
        () => onTerminal(),
        controller.signal
      ).catch((err) => {
        // A clean resolve (stream ended on its own, e.g. after a terminal
        // event) never reaches this catch. An intentional abort (unmount,
        // or bookId changing below) must never trigger a reconnect either --
        // only a genuine failure (non-2xx ApiError, network error) should.
        if (!isActive || isAbortError(err)) return;
        setIsReconnecting(true);
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      });
    };

    connect();

    return () => {
      isActive = false;
      controller.abort();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId]);

  return (
    <div className="w-full">
      <h2 className="font-headline-sm text-headline-sm text-primary font-semibold mb-space-sm">
        Working on it...
      </h2>

      {progress ? (
        <>
          {isReconnecting && (
            <div
              data-testid="progress-reconnecting"
              className="flex items-center gap-2 mb-space-sm px-space-md py-2 rounded-lg bg-surface-container text-on-surface-variant font-label-sm text-label-sm font-medium"
            >
              <span className="material-symbols-outlined text-[16px] animate-spin">
                progress_activity
              </span>
              Reconnecting...
            </div>
          )}
          <div className="bg-surface-container-lowest rounded-xl p-space-md border border-[#e3e2df]/60 shadow-sm">
            <OverallProgress percent={progress.percent ?? 0} elapsedSeconds={displayedElapsed} />
            <div className="flex items-center gap-2 mb-space-sm">
              <span className="material-symbols-outlined text-[18px] text-[#1e3a2f] animate-spin">
                progress_activity
              </span>
              <span data-testid="progress-current-node" className="font-title-md text-[14px] text-primary font-medium">
                {progress.current_node}
              </span>
              {progress.book_kind && (
                <span
                  data-testid="progress-book-kind"
                  className="ml-auto px-2 py-0.5 rounded-full bg-surface-container text-on-surface-variant font-label-sm text-label-sm font-medium"
                >
                  {progress.book_kind}
                </span>
              )}
            </div>
            {progress.completed_nodes.length > 0 && (
              <ul
                data-testid="progress-completed-nodes"
                className="font-label-sm text-label-sm text-on-surface-variant space-y-1"
              >
                {progress.completed_nodes.map((node) => (
                  <li key={node} className="flex items-center gap-1.5">
                    <span className="material-symbols-outlined text-[14px] text-secondary">
                      check_circle
                    </span>
                    {node}
                    {progress.step_seconds?.[node] !== undefined && (
                      <span data-testid={`progress-step-seconds-${node}`} className="text-outline">
                        · {formatElapsed(Math.round(progress.step_seconds[node]))}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <WarningsBanner warnings={progress.warnings ?? []} />
        </>
      ) : (
        <StateMessage
          variant="loading"
          message={isReconnecting ? 'Reconnecting...' : 'Connecting...'}
          testId={isReconnecting ? 'progress-reconnecting' : undefined}
        />
      )}

      {progress && progress.chapters && progress.chapters.length > 0 && (
        <>
          <ChapterSummary chapters={progress.chapters} />
          <div data-testid="progress-chapters" className="flex flex-col gap-space-sm mt-space-md">
            {progress.chapters.map((chapter) => (
              <ChapterRow key={chapter.id} chapter={chapter} />
            ))}
          </div>
        </>
      )}
    </div>
  );
};
