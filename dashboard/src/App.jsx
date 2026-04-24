import React, { useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import NewProject from './pages/NewProject';
import ProjectView from './pages/ProjectView';
import ProjectsList from './pages/ProjectsList';
import PhaseDetail from './pages/PhaseDetail';
import ClientPortal from './pages/ClientPortal';
import Settings from './pages/Settings';
import { api, setNavigate } from './api';

const ProtectedRoute = ({ children }) => {
  const token = api.getToken();
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
};

function App() {
  const navigate = useNavigate();

  // Wire React Router's navigate into api.js so the 401 interceptor
  // can redirect to /login without a hard page reload.
  useEffect(() => {
    setNavigate(navigate);
  }, [navigate]);

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
