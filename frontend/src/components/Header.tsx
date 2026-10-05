import React from 'react';

interface HeaderProps {
  breadcrumb: string;
  isLoggedIn: boolean;
  onLogout: () => void;
  onOpenAccount?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ breadcrumb, isLoggedIn, onLogout, onOpenAccount }) => {
  return (
    <header className="fixed top-0 w-full z-50 pt-safe bg-[#faf9f5]/90 backdrop-blur-xl border-b border-[#e3e2df]/60 shadow-[0_1px_8px_rgba(0,0,0,0.03)]">
      <div className="h-14 px-4 max-w-4xl mx-auto flex items-center justify-between">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="font-headline-sm text-headline-sm font-semibold tracking-tight text-[#1e3a2f]">
            Video2Book
          </span>
          <span className="text-[#c1c8c3] font-label-sm text-label-sm mx-1">/</span>
          <span className="font-body-sm text-body-sm text-[#424844] font-medium truncate max-w-[160px]">
            {breadcrumb}
          </span>
        </div>

        {isLoggedIn && (
          <div className="flex items-center gap-1">
            {onOpenAccount && (
              <button
                data-testid="header-account"
                onClick={onOpenAccount}
                aria-label="Account"
                className="px-3 h-9 flex items-center justify-center rounded-full text-[#424844] hover:text-[#07241a] hover:bg-[#efeeea] transition-all font-label-sm text-label-sm font-medium"
              >
                Account
              </button>
            )}
            <button
              onClick={onLogout}
              aria-label="Log out"
              className="px-3 h-9 flex items-center justify-center rounded-full text-[#424844] hover:text-[#07241a] hover:bg-[#efeeea] transition-all font-label-sm text-label-sm font-medium"
            >
              Log out
            </button>
          </div>
        )}
      </div>
    </header>
  );
};
