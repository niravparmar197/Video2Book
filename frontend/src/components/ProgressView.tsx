import React, { useEffect, useState } from 'react';
import { streamEvents } from '../lib/api';
import { ProgressEvent } from '../types';

interface ProgressViewProps {
  bookId: string;
  onTerminal: () => void;
}

export const ProgressView: React.FC<ProgressViewProps> = ({ bookId, onTerminal }) => {
  const [progress, setProgress] = useState<ProgressEvent | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    streamEvents(bookId, setProgress, () => onTerminal(), controller.signal).catch(() => {
      // stream ended (aborted on unmount, or backend closed it) -- status
      // polling in the parent screen is the fallback source of truth.
    });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId]);

  return (
    <div className="w-full">
      <h2 className="font-headline-sm text-headline-sm text-primary font-semibold mb-space-sm">
        Working on it...
      </h2>

      {progress ? (
        <div className="bg-surface-container-lowest rounded-xl p-space-md border border-[#e3e2df]/60 shadow-sm">
          <div className="flex items-center gap-2 mb-space-sm">
            <span className="material-symbols-outlined text-[18px] text-[#1e3a2f] animate-spin">
              progress_activity
            </span>
            <span data-testid="progress-current-node" className="font-title-md text-[14px] text-primary font-medium">
              {progress.current_node}
            </span>
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
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <p className="font-body-sm text-body-sm text-on-surface-variant">Connecting...</p>
      )}
    </div>
  );
};
