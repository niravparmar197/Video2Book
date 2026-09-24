import React from 'react';

interface StateMessageProps {
  variant: 'loading' | 'empty' | 'error';
  message: string;
  testId?: string;
}

/**
 * Every screen's loading spinner, empty state, and error banner go through
 * here so the three read the same way everywhere instead of each screen
 * inventing its own plain-<p> variant. The error variant intentionally
 * stays plain text (no icon) -- Material Symbols renders via a ligature,
 * so an icon glyph sibling would leak into the element's text content and
 * break exact-text assertions (e.g. login.spec.ts's `toHaveText`).
 */
export const StateMessage: React.FC<StateMessageProps> = ({ variant, message, testId }) => {
  if (variant === 'error') {
    return (
      <p
        data-testid={testId ?? 'state-message'}
        data-variant="error"
        className="mt-space-sm font-body-sm text-body-sm text-error"
      >
        {message}
      </p>
    );
  }

  return (
    <div
      data-testid={testId ?? 'state-message'}
      data-variant={variant}
      className="w-full flex flex-col items-center gap-2 py-10 text-center text-on-surface-variant"
    >
      <span
        className={`material-symbols-outlined text-[24px] ${variant === 'loading' ? 'animate-spin' : ''}`}
      >
        {variant === 'loading' ? 'progress_activity' : 'inbox'}
      </span>
      <p className="font-body-sm text-body-sm">{message}</p>
    </div>
  );
};
