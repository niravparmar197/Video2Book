import React from 'react';

/**
 * The terms a user accepts at sign-up (POST /users needs accept_terms).
 * Plain language on purpose; have a lawyer review it before a public launch.
 */
export const TermsOfUse: React.FC = () => (
  <div
    data-testid="terms-of-use"
    className="mt-space-sm max-h-64 overflow-y-auto bg-surface-container-lowest border border-[#e3e2df] rounded-lg p-3 font-body-sm text-body-sm text-on-surface-variant space-y-2"
  >
    <p className="font-semibold text-primary">Terms of Use</p>
    <p>
      <span className="font-semibold">Your videos, your responsibility.</span> You may only submit
      videos you have the right to turn into notes for your own use -- for example your own videos,
      videos whose license allows it, or use that the law in your country permits. You are
      responsible for that, not Video2Book.
    </p>
    <p>
      <span className="font-semibold">What we do with them.</span> We fetch the video's captions,
      audio and screenshots to make your book. The text is processed by third-party AI services
      (NVIDIA and Google) on their free tiers, which may use it to improve their models -- do not
      submit private or confidential videos.
    </p>
    <p>
      <span className="font-semibold">Accuracy.</span> Books are written by AI from the video and
      can contain mistakes. Check anything important against the video.
    </p>
    <p>
      <span className="font-semibold">Keeping and deleting.</span> Your book files are kept for a
      limited time and then deleted. You can delete a book, or your whole account and everything in
      it, at any time.
    </p>
    <p>
      <span className="font-semibold">Fair use of the service.</span> Don't create several accounts
      or automate requests to get around the limits. We may suspend accounts that do.
    </p>
  </div>
);
