import React, { useState } from 'react';
import { registerUser, setApiKey, ApiError } from '../lib/api';
import { StateMessage } from './StateMessage';

interface LoginScreenProps {
  onLoggedIn: () => void;
}

export const LoginScreen: React.FC<LoginScreenProps> = ({ onLoggedIn }) => {
  const [mode, setMode] = useState<'register' | 'paste'>('register');
  const [email, setEmail] = useState('');
  const [pastedKey, setPastedKey] = useState('');
  const [issuedKey, setIssuedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const { api_key } = await registerUser(email);
      setIssuedKey(api_key);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the backend');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleContinueWithIssuedKey = () => {
    if (!issuedKey) return;
    setApiKey(issuedKey);
    onLoggedIn();
  };

  const handlePaste = (e: React.FormEvent) => {
    e.preventDefault();
    if (!pastedKey.trim()) return;
    setApiKey(pastedKey.trim());
    onLoggedIn();
  };

  if (issuedKey) {
    return (
      <div className="w-full max-w-sm mx-auto pt-16 px-1">
        <h1 className="font-headline-lg-mobile text-headline-lg-mobile text-primary font-semibold mb-2">
          Save your API key
        </h1>
        <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-md">
          This is shown only once. Store it somewhere safe -- you'll need it to log back in.
        </p>
        <div
          data-testid="login-issued-key"
          className="bg-surface-container-lowest border border-[#e3e2df] rounded-lg p-3 mb-space-md break-all font-mono text-[13px] text-primary select-all"
        >
          {issuedKey}
        </div>
        <button
          data-testid="login-continue-button"
          onClick={handleContinueWithIssuedKey}
          className="w-full py-3 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-title-md text-title-md font-semibold transition-all active:scale-[0.98]"
        >
          I've saved it -- continue
        </button>
      </div>
    );
  }

  return (
    <div className="w-full max-w-sm mx-auto pt-16 px-1">
      <h1 className="font-headline-lg-mobile text-headline-lg-mobile text-primary font-semibold mb-1">
        Video2Book
      </h1>
      <p className="font-body-sm text-body-sm text-on-surface-variant mb-space-md">
        Turn YouTube videos into a PDF book.
      </p>

      <div className="flex gap-1 mb-space-md bg-surface-container rounded-lg p-1">
        <button
          data-testid="login-tab-register"
          onClick={() => setMode('register')}
          className={`flex-1 py-1.5 rounded-md font-label-sm text-label-sm font-medium transition-colors ${
            mode === 'register' ? 'bg-white text-primary shadow-sm' : 'text-on-surface-variant'
          }`}
        >
          New account
        </button>
        <button
          data-testid="login-tab-paste"
          onClick={() => setMode('paste')}
          className={`flex-1 py-1.5 rounded-md font-label-sm text-label-sm font-medium transition-colors ${
            mode === 'paste' ? 'bg-white text-primary shadow-sm' : 'text-on-surface-variant'
          }`}
        >
          I have a key
        </button>
      </div>

      {mode === 'register' ? (
        <form onSubmit={handleRegister} className="flex flex-col gap-space-sm">
          <input
            data-testid="login-email-input"
            type="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full px-3 py-2.5 bg-white border border-[#c1c8c3] rounded-lg text-body-md text-primary focus:outline-none focus:border-[#006c49]"
          />
          <button
            data-testid="login-register-submit"
            type="submit"
            disabled={isSubmitting}
            className="w-full py-3 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-title-md text-title-md font-semibold transition-all active:scale-[0.98] disabled:opacity-50"
          >
            {isSubmitting ? 'Creating account...' : 'Create account'}
          </button>
        </form>
      ) : (
        <form onSubmit={handlePaste} className="flex flex-col gap-space-sm">
          <input
            data-testid="login-paste-key-input"
            type="text"
            required
            placeholder="Paste your API key"
            value={pastedKey}
            onChange={(e) => setPastedKey(e.target.value)}
            className="w-full px-3 py-2.5 bg-white border border-[#c1c8c3] rounded-lg text-body-md font-mono text-primary focus:outline-none focus:border-[#006c49]"
          />
          <button
            data-testid="login-paste-submit"
            type="submit"
            className="w-full py-3 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-title-md text-title-md font-semibold transition-all active:scale-[0.98]"
          >
            Log in
          </button>
        </form>
      )}

      {error && <StateMessage variant="error" message={error} testId="login-error" />}
    </div>
  );
};
