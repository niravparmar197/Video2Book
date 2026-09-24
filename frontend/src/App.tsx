import React, { useState } from 'react';
import { Header } from './components/Header';
import { BottomNav, TabType } from './components/BottomNav';
import { LoginScreen } from './components/LoginScreen';
import { NewBookScreen } from './components/NewBookScreen';
import { MyBooksScreen } from './components/MyBooksScreen';
import { BookDetailScreen } from './components/BookDetailScreen';
import { getApiKey, clearApiKey } from './lib/api';

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState<boolean>(!!getApiKey());
  const [activeTab, setActiveTab] = useState<TabType>('new');
  const [selectedBookId, setSelectedBookId] = useState<string | null>(null);

  const handleLogout = () => {
    clearApiKey();
    setIsLoggedIn(false);
    setSelectedBookId(null);
  };

  const handleSelectTab = (tab: TabType) => {
    setSelectedBookId(null);
    setActiveTab(tab);
  };

  const breadcrumb = selectedBookId ? 'Book' : activeTab === 'new' ? 'New Book' : 'My Books';

  if (!isLoggedIn) {
    return (
      <div className="bg-[#faf9f5] font-body-md text-body-md text-[#1b1c1a] flex flex-col min-h-screen">
        <main className="flex-1 w-full bg-[#faf9f5] px-4 max-w-lg mx-auto">
          <LoginScreen onLoggedIn={() => setIsLoggedIn(true)} />
        </main>
      </div>
    );
  }

  return (
    <div className="bg-[#faf9f5] font-body-md text-body-md text-[#1b1c1a] flex flex-col min-h-screen">
      <Header breadcrumb={breadcrumb} isLoggedIn={isLoggedIn} onLogout={handleLogout} />

      <main className="flex-1 w-full bg-[#faf9f5] pt-16 px-4 max-w-lg mx-auto">
        {selectedBookId ? (
          <BookDetailScreen bookId={selectedBookId} />
        ) : activeTab === 'new' ? (
          <NewBookScreen onBookCreated={setSelectedBookId} />
        ) : (
          <MyBooksScreen onSelectBook={setSelectedBookId} />
        )}
      </main>

      <BottomNav activeTab={activeTab} onSelectTab={handleSelectTab} />
    </div>
  );
}
