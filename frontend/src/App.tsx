import React, { useState } from 'react';
import { Header } from './components/Header';
import { BottomNav, TabType } from './components/BottomNav';
import { LoginScreen } from './components/LoginScreen';
import { NewBookScreen } from './components/NewBookScreen';
import { MyBooksScreen } from './components/MyBooksScreen';
import { BookDetailScreen } from './components/BookDetailScreen';
import { AccountScreen } from './components/AccountScreen';
import { getApiKey, clearApiKey } from './lib/api';
import { getSavedView, setSavedView } from './lib/myBooks';

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState<boolean>(!!getApiKey());
  // Restored from localStorage (sprints/v12) so a page refresh resumes
  // exactly where the user was -- an in-flight book's own progress stream
  // already survives a reconnect fine (the backend tracks elapsed time
  // from the run's checkpoint history, not from when this tab connected),
  // but losing selectedBookId here dropped the user back on "New Book"
  // with no way back to it, which looked like the whole run had restarted.
  const savedView = getSavedView();
  const [activeTab, setActiveTab] = useState<TabType>(savedView?.activeTab ?? 'new');
  const [selectedBookId, setSelectedBookId] = useState<string | null>(
    savedView?.selectedBookId ?? null
  );
  const [showAccount, setShowAccount] = useState(false);

  const persistView = (tab: TabType, bookId: string | null) => {
    setSavedView({ activeTab: tab, selectedBookId: bookId });
  };

  const handleLogout = () => {
    clearApiKey();
    setIsLoggedIn(false);
    setSelectedBookId(null);
    setShowAccount(false);
    setSavedView({ activeTab: 'new', selectedBookId: null });
  };

  const handleSelectTab = (tab: TabType) => {
    setShowAccount(false);
    setSelectedBookId(null);
    setActiveTab(tab);
    persistView(tab, null);
  };

  const handleSelectBook = (bookId: string) => {
    setShowAccount(false);
    setSelectedBookId(bookId);
    persistView(activeTab, bookId);
  };

  const handleBookCreated = (bookId: string) => {
    setSelectedBookId(bookId);
    persistView(activeTab, bookId);
  };

  const handleBookDeleted = () => {
    setSelectedBookId(null);
    setActiveTab('books');
    persistView('books', null);
  };

  const breadcrumb = showAccount
    ? 'Account'
    : selectedBookId
      ? 'Book'
      : activeTab === 'new'
        ? 'New Book'
        : 'My Books';

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
      <Header
        breadcrumb={breadcrumb}
        isLoggedIn={isLoggedIn}
        onLogout={handleLogout}
        onOpenAccount={() => setShowAccount(true)}
      />

      <main className="flex-1 w-full bg-[#faf9f5] pt-16 px-4 max-w-lg mx-auto">
        {showAccount ? (
          <AccountScreen onAccountDeleted={handleLogout} />
        ) : selectedBookId ? (
          <BookDetailScreen bookId={selectedBookId} onDeleted={handleBookDeleted} />
        ) : activeTab === 'new' ? (
          <NewBookScreen onBookCreated={handleBookCreated} />
        ) : (
          <MyBooksScreen onSelectBook={handleSelectBook} />
        )}
      </main>

      <BottomNav activeTab={activeTab} onSelectTab={handleSelectTab} />
    </div>
  );
}
