import React, { useState } from 'react';
import { ApiError, deleteAccount, rotateApiKey, setApiKey } from '../lib/api';
import { StateMessage } from './StateMessage';
import { TermsOfUse } from './TermsOfUse';

interface AccountScreenProps {
  /** Called once the account is gone: the app logs out. */
  onAccountDeleted: () => void;
}

/** Get a new API key, read the terms, or delete the account. */
export const AccountScreen: React.FC<AccountScreenProps> = ({ onAccountDeleted }) => {
  const [newKey, setNewKey] = useState<string | null>(null);
  const [isRotating, setIsRotating] = useState(false);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRotate = async () => {
    setIsRotating(true);
    setError(null);
    try {
      const { api_key } = await rotateApiKey();
      setApiKey(api_key); // this browser keeps working with the new key
      setNewKey(api_key);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not get a new key');
    } finally {
      setIsRotating(false);
    }
  };

  const handleDelete = async () => {
    setIsDeleting(true);
    setError(null);
    try {
      await deleteAccount();
      onAccountDeleted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not delete the account');
      setIsDeleting(false);
    }
  };

  return (
    <div className="w-full pb-24 flex flex-col gap-space-md">
      <h1 className="font-headline-lg-mobile text-headline-lg-mobile text-primary font-semibold">Account</h1>

      <section className="bg-surface-container-lowest rounded-xl p-space-md border border-[#e3e2df]/60">
        <h2 className="font-title-md text-title-md text-primary font-semibold mb-1">API key</h2>
        <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-sm">
          Get a new key if yours expired or may have leaked. The old key stops working at once.
        </p>
        {newKey && (
          <div
            data-testid="account-new-key"
            className="mb-space-sm break-all font-mono text-[13px] text-primary select-all bg-white border border-[#e3e2df] rounded-lg p-3"
          >
            {newKey}
          </div>
        )}
        <button
          data-testid="account-rotate-key"
          onClick={handleRotate}
          disabled={isRotating}
          className="py-2 px-4 rounded-lg border border-[#c1c8c3] text-primary font-label-sm text-label-sm font-medium disabled:opacity-50"
        >
          {isRotating ? 'Getting a new key...' : 'Get a new API key'}
        </button>
      </section>

      <section className="bg-surface-container-lowest rounded-xl p-space-md border border-[#e3e2df]/60">
        <h2 className="font-title-md text-title-md text-primary font-semibold">Terms of Use</h2>
        <TermsOfUse />
      </section>

      <section className="rounded-xl p-space-md border border-error/30 bg-error-container/20">
        <h2 className="font-title-md text-title-md text-primary font-semibold mb-1">Delete account</h2>
        <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-sm">
          Deletes your account and every book in it, with all files. Cancel books still being made first.
        </p>
        {isConfirmingDelete ? (
          <div data-testid="account-delete-confirm" className="flex gap-2">
            <button
              data-testid="account-delete-confirm-yes"
              onClick={handleDelete}
              disabled={isDeleting}
              className="py-2 px-4 rounded-lg bg-error text-on-error font-label-sm text-label-sm font-semibold disabled:opacity-50"
            >
              {isDeleting ? 'Deleting...' : 'Yes, delete everything'}
            </button>
            <button
              onClick={() => setIsConfirmingDelete(false)}
              disabled={isDeleting}
              className="py-2 px-4 rounded-lg border border-[#c1c8c3] text-primary font-label-sm text-label-sm"
            >
              Keep my account
            </button>
          </div>
        ) : (
          <button
            data-testid="account-delete"
            onClick={() => setIsConfirmingDelete(true)}
            className="py-2 px-4 rounded-lg text-error border border-error/40 font-label-sm text-label-sm font-medium"
          >
            Delete my account
          </button>
        )}
      </section>

      {error && <StateMessage variant="error" message={error} testId="account-error" />}
    </div>
  );
};
