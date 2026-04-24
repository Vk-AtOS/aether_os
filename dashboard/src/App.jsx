import React, { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import NewProject from './pages/NewProject';
import ProjectView from './pages/ProjectView';
import ProjectsList from './pages/ProjectsList';
import PhaseDetail from './pages/PhaseDetail';
import ClientPortal from './pages/ClientPortal';
import Settings from './pages/Settings';
import { api } from './api';

const ProtectedRoute = ({ children }) => {
  const token = api.getToken();
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
};

function App() {
  // Sync token from sessionStorage on load is handled by api.js initialization
  // but we can enforce a check here if needed.
  
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/portal/:id" element={<ClientPortal />} />
      
      <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<Dashboard />} />
        <Route path="new" element={<NewProject />} />
        <Route path="projects" element={<ProjectsList />} />
        <Route path="project/:id" element={<ProjectView />} />
        <Route path="project/:id/phase/:name" element={<PhaseDetail />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
