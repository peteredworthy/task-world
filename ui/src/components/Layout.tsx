import { useRef, useEffect } from 'react';
import { Outlet, useNavigate } from 'react-router-dom';
import { Sidebar, MobileBottomNav } from './Sidebar';
import { ConnectionBanner } from './ConnectionBanner';
import { useCreateRunModal } from '../hooks/useCreateRunModal';
import { useSettingsModal } from '../hooks/useSettingsModal';

export function Layout() {
  const searchRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { open: openCreateRun } = useCreateRunModal();
  const { open: openSettings } = useSettingsModal();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        searchRef.current?.focus();
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  function handleSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      const value = (e.target as HTMLInputElement).value.trim();
      if (value) {
        navigate('/?search=' + encodeURIComponent(value));
      } else {
        navigate('/');
      }
    }
  }

  return (
    <div className="flex min-h-screen bg-bg-primary">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-auto scrollbar-dark pb-16 md:pb-0">
        <header className="sticky top-0 z-40 bg-bg-card border-b border-border">
          <div className="px-6">
            <div className="flex items-center justify-between h-14">
              {/* Center: Search bar */}
              <div className="hidden md:flex flex-1 max-w-md">
                <div className="relative w-full">
                  <input
                    ref={searchRef}
                    type="text"
                    placeholder="Search runs..."
                    className="w-full bg-bg-elevated border border-border rounded-lg px-4 py-2 text-sm text-text-primary placeholder-text-muted focus:outline-none focus:border-accent-purple"
                    onKeyDown={handleSearchKeyDown}
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted text-xs bg-bg-hover px-1.5 py-0.5 rounded">
                    &#x2318;K
                  </span>
                </div>
              </div>

              {/* Spacer */}
              <div className="flex-1" />

              {/* Right: Actions */}
              <div className="flex items-center gap-4">
                <button
                  onClick={() => openCreateRun()}
                  className="hidden sm:flex items-center gap-2 bg-accent-purple hover:bg-accent-purple/90 text-white px-4 py-2 rounded-lg text-sm font-semibold"
                >
                  + New Run
                </button>
                <button
                  onClick={openSettings}
                  className="text-text-secondary hover:text-text-primary"
                  aria-label="Settings"
                >
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                  </svg>
                </button>
                <div className="w-8 h-8 rounded-full bg-accent-purple flex items-center justify-center text-white text-sm font-semibold" aria-label="User avatar">
                  D
                </div>
              </div>
            </div>
          </div>
        </header>
        <ConnectionBanner />
        <main className="px-6 py-6">
          <Outlet />
        </main>
      </div>
      <MobileBottomNav />
    </div>
  );
}
