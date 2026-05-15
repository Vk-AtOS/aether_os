import React, { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import NewProjectModal from './NewProjectModal';
import { RunsProvider, useRuns } from '../contexts/RunsContext';
import { Menu, X } from 'lucide-react';

function LayoutInner() {
  const [modalOpen, setModalOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { activeRunCount } = useRuns();
  const location = useLocation();

  // Close sidebar on route change (mobile)
  useEffect(() => { setSidebarOpen(false); }, [location.pathname]);

  return (
    <div className="flex h-screen overflow-hidden bg-surface">
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
            onClick={() => setSidebarOpen(v => !v)}
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
          <Outlet context={{ openNewProject: () => setModalOpen(true) }} />
        </main>
        <footer className="shrink-0 py-2 border-t border-border bg-panel text-center">
          <p className="text-xs text-muted/50">
            © 2026 VKatOS Private Limited — AetherOS Factory v1.0
          </p>
        </footer>
      </div>

      <NewProjectModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
      />
    </div>
  );
}

const Layout = () => (
  <RunsProvider>
    <LayoutInner />
  </RunsProvider>
);

export default Layout;
