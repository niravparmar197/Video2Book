import React from 'react';

export type TabType = 'new' | 'books';

interface BottomNavProps {
  activeTab: TabType;
  onSelectTab: (tab: TabType) => void;
}

export const BottomNav: React.FC<BottomNavProps> = ({ activeTab, onSelectTab }) => {
  const tabs: { id: TabType; label: string; icon: string }[] = [
    { id: 'new', label: 'New Book', icon: 'add_circle' },
    { id: 'books', label: 'My Books', icon: 'menu_book' },
  ];

  return (
    <nav className="fixed bottom-0 w-full z-50 pb-safe bg-[#faf9f5]/92 backdrop-blur-xl border-t border-[#e3e2df]/70 shadow-[0_-2px_12px_rgba(30,58,47,0.05)]">
      <div className="flex justify-around items-center h-16 px-2 max-w-lg mx-auto">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              data-testid={`nav-tab-${tab.id}`}
              onClick={() => onSelectTab(tab.id)}
              className={`flex flex-col items-center justify-center min-w-[72px] h-12 transition-colors gap-0.5 relative ${
                isActive ? 'text-[#1e3a2f] font-semibold' : 'text-[#424844] hover:text-[#07241a]'
              }`}
            >
              <span
                className="material-symbols-outlined text-[22px] transition-transform duration-200"
                style={{
                  fontVariationSettings: isActive ? "'FILL' 1, 'wght' 600" : "'FILL' 0, 'wght' 400",
                }}
              >
                {tab.icon}
              </span>
              <span className="font-label-sm text-label-sm">{tab.label}</span>
              {isActive && <span className="absolute -top-1 w-6 h-0.5 bg-[#006c49] rounded-full" />}
            </button>
          );
        })}
      </div>
    </nav>
  );
};
