import React, { useState, useEffect } from 'react';
import { Outlet, useOutletContext } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import NewProjectModal from './NewProjectModal';
import { api } from '../api';

const Layout = () => {
  const [modalOpen, setModalOpen] = useState(false);
  const [activeRunCount, setActiveRunCount] = useState(0);

  // Poll for active runs to show pulsing indicator in TopBar
  useEffect(() => {
    const poll = async () => {
      try {
        const res = await api.listRuns();
        const runs = res.data || [];
        setActiveRunCount(runs.filter((r) => r.status === 'running').length);
      } catch {}
    };
    poll();
    const iv = setInterval(poll, 15000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div className="flex h-screen overflow-hidden bg-surface">
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <TopBar
          onNewProject={() => setModalOpen(true)}
          activeRunCount={activeRunCount}
        />
        <main className="flex-1 overflow-x-hidden overflow-y-auto p-6 custom-scrollbar pb-12">
          {/* Pass modal opener to child routes via Outlet context */}
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
};

export default Layout;
