import React, { useState, Suspense } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import NewProjectModal from './NewProjectModal';
import { RunsProvider } from '../contexts/RunsContext';
import { useRuns } from '../contexts/useRuns';
import { SettingsProvider } from '../contexts/SettingsContext';
import { Menu, X } from 'lucide-react';

const PageSkeleton = () => (
  <div className="p-6 space-y-4 animate-pulse">
    <div className="h-7 w-48 bg-white/[0.04] rounded-xl" />
    <div className="grid grid-cols-3 gap-4">
      {[1,2,3].map(i => <div key={i} className="h-24 bg-white/[0.03] rounded-2xl" />)}
    </div>
    <div className="h-64 bg-white/[0.02] rounded-2xl" />
    <div className="space-y-2">
      {[1,2,3,4].map(i => <div key={i} className="h-12 bg-white/[0.02] rounded-xl" style={{width:`${70+i*5}%`}} />)}
    </div>
  </div>
);

function LayoutInner() {
  const [modalOpen, setModalOpen] = useState(false);
  // The mobile sidebar is open for the path it was opened on, so navigating closes it.
  const [sidebarOpenAt, setSidebarOpenAt] = useState(null);
  const { activeRunCount } = useRuns();
  const location = useLocation();

  // Close sidebar on route change (mobile)
  const sidebarOpen = sidebarOpenAt === location.pathname;
  const setSidebarOpen = (open) => setSidebarOpenAt(open ? location.pathname : null);

  return (
    <div className="flex h-screen overflow-hidden bg-[#050507]">
      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar — always visible on lg+, slide-in on mobile */}
      <div className={`fixed lg:static z-40 inset-y-0 left-0 transition-transform duration-200 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} lg:translate-x-0`}>
        <Sidebar onClose={() => setSidebarOpen(false)} />
      </div>

      <div className="flex flex-col flex-1 overflow-hidden min-w-0">
        <div className="flex items-center">
          {/* Hamburger — mobile only */}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="lg:hidden p-3 text-muted hover:text-bright transition-colors shrink-0"
            aria-label="Toggle sidebar"
          >
            {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
          <TopBar
            onNewProject={() => setModalOpen(true)}
            activeRunCount={activeRunCount}
          />
        </div>
        <main className="flex-1 overflow-x-hidden overflow-y-auto p-6 custom-scrollbar pb-12" role="main">
          <Suspense fallback={<PageSkeleton />}>
            <Outlet context={{ openNewProject: () => setModalOpen(true) }} />
          </Suspense>
        </main>
        <footer className="shrink-0 py-2 border-t border-white/[0.06] bg-[#050507]/80 text-center">
          <p className="text-xs text-slate-700">
            © 2026 AetherOS
          </p>
        </footer>
      </div>

      {/* Mounted only while open, so every opening starts with an empty form. */}
      {modalOpen && <NewProjectModal open onClose={() => setModalOpen(false)} />}
    </div>
  );
}

const Layout = () => (
  <SettingsProvider>
    <RunsProvider>
      <LayoutInner />
    </RunsProvider>
  </SettingsProvider>
);

export default Layout;
