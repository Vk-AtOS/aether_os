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
import Compliance from './pages/Compliance';
import Marketplace from './pages/Marketplace';
import NewProjectWizard from './pages/NewProjectWizard';
import ConnectorHub from './pages/ConnectorHub';
import PluginManager from './pages/PluginManager';
import MemoryInspector from './pages/MemoryInspector';
import CostDashboard from './pages/CostDashboard';
import AdminUsers from './pages/AdminUsers';
import Billing from './pages/Billing';
import Profile from './pages/Profile';
import WebhookSettings from './pages/WebhookSettings';
import FrontendBuilder from './pages/FrontendBuilder';
import BackendBuilder from './pages/BackendBuilder';
import PromptInput from './pages/PromptInput';
import AuditLogs from './pages/AuditLogs';
import OAuthCallback from './pages/OAuthCallback';
import Learning from './pages/Learning';
import Legal from './pages/Legal';
import IntelligenceHub from './pages/IntelligenceHub';
import SearchPage from './pages/SearchPage';
import Deployments from './pages/Deployments';
import SystemHealth from './pages/SystemHealth';
import Guardian from './pages/Guardian';
import Signup from './pages/Signup';
import Pricing from './pages/Pricing';
import Agents from './pages/Agents';
import GlobalPatternsTuning from './pages/GlobalPatternsTuning';
import ProjectDesigner from './pages/ProjectDesigner';
import Workspaces from './pages/Workspaces';
import { api, setNavigate } from './api';
import { useRole } from './hooks/useRole';
import ErrorBoundary from './components/ErrorBoundary';

const ProtectedRoute = ({ children }) => {
  const token = api.getToken();
  if (!token) return <Navigate to="/login" replace />;
  return children;
};

const AdminRoute = ({ children }) => {
  const token = api.getToken();
  const { isAdmin } = useRole();
  if (!token) return <Navigate to="/login" replace />;
  if (!isAdmin) return <Navigate to="/" replace />;
  return children;
};

const NotFound = () => (
  <div className="min-h-screen flex items-center justify-center bg-surface">
    <div className="text-center space-y-4">
      <div className="text-6xl font-bold text-accent/30">404</div>
      <h1 className="text-2xl font-bold text-bright">Page Not Found</h1>
      <p className="text-muted">The page you're looking for doesn't exist.</p>
      <a href="/" className="inline-block mt-4 bg-accent hover:bg-accent/90 text-white font-bold px-6 py-2 rounded-lg transition-colors">
        Back to Dashboard
      </a>
    </div>
  </div>
);

function App() {
  const navigate = useNavigate();

  useEffect(() => {
    setNavigate(navigate);
  }, [navigate]);

  return (
    <Routes>
      <Route path="/login"   element={<ErrorBoundary><Login /></ErrorBoundary>} />
      <Route path="/signup"  element={<ErrorBoundary><Signup /></ErrorBoundary>} />
      <Route path="/pricing" element={<ErrorBoundary><Pricing /></ErrorBoundary>} />
      <Route path="/legal"   element={<ErrorBoundary><Legal /></ErrorBoundary>} />
      <Route path="/auth/callback" element={<OAuthCallback />} />
      <Route path="/portal/:id" element={<ErrorBoundary><ClientPortal /></ErrorBoundary>} />

      <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
        <Route path="new" element={<ErrorBoundary><NewProject /></ErrorBoundary>} />
        <Route path="projects" element={<ErrorBoundary><ProjectsList /></ErrorBoundary>} />
        <Route path="project/:id" element={<ErrorBoundary><ProjectView /></ErrorBoundary>} />
        <Route path="project/:id/phase/:name" element={<ErrorBoundary><PhaseDetail /></ErrorBoundary>} />
        <Route path="settings" element={<ErrorBoundary><Settings /></ErrorBoundary>} />
        <Route path="settings/sso" element={<ErrorBoundary><Settings /></ErrorBoundary>} />
        <Route path="compliance" element={<ErrorBoundary><Compliance /></ErrorBoundary>} />
        <Route path="marketplace" element={<ErrorBoundary><Marketplace /></ErrorBoundary>} />
        <Route path="new-project" element={<Navigate to="/designer" replace />} />
        <Route path="connectors" element={<ErrorBoundary><ConnectorHub /></ErrorBoundary>} />
        <Route path="dashboard/tools/connectors" element={<Navigate to="/connectors" replace />} />
        <Route path="skills" element={<ErrorBoundary><PluginManager /></ErrorBoundary>} />
        <Route path="dashboard/tools/skills" element={<Navigate to="/skills" replace />} />
        <Route path="memory" element={<ErrorBoundary><MemoryInspector /></ErrorBoundary>} />
        <Route path="dashboard/tools/memory" element={<Navigate to="/memory" replace />} />
        <Route path="costs" element={<ErrorBoundary><CostDashboard /></ErrorBoundary>} />
        <Route path="dashboard/tools/costs" element={<Navigate to="/costs" replace />} />
        <Route path="admin/users" element={<AdminRoute><ErrorBoundary><AdminUsers /></ErrorBoundary></AdminRoute>} />
        <Route path="admin/billing" element={<AdminRoute><ErrorBoundary><Billing /></ErrorBoundary></AdminRoute>} />
        <Route path="admin/intelligence" element={<AdminRoute><ErrorBoundary><GlobalPatternsTuning /></ErrorBoundary></AdminRoute>} />
        <Route path="profile" element={<ErrorBoundary><Profile /></ErrorBoundary>} />
        <Route path="settings/webhooks" element={<ErrorBoundary><WebhookSettings /></ErrorBoundary>} />
        <Route path="webhooks" element={<Navigate to="/settings/webhooks" replace />} />
        <Route path="dashboard/tools/webhooks" element={<Navigate to="/settings/webhooks" replace />} />
        <Route path="frontend-builder" element={<ErrorBoundary><FrontendBuilder /></ErrorBoundary>} />
        <Route path="dashboard/tools/frontend-builder" element={<Navigate to="/frontend-builder" replace />} />
        <Route path="project/:id/frontend-builder" element={<ErrorBoundary><FrontendBuilder /></ErrorBoundary>} />
        <Route path="backend-builder" element={<ErrorBoundary><BackendBuilder /></ErrorBoundary>} />
        <Route path="dashboard/tools/backend-builder" element={<Navigate to="/backend-builder" replace />} />
        <Route path="project/:id/backend-builder" element={<ErrorBoundary><BackendBuilder /></ErrorBoundary>} />
        <Route path="prompt" element={<ErrorBoundary><PromptInput /></ErrorBoundary>} />
        <Route path="dashboard/tools/prompt" element={<Navigate to="/prompt" replace />} />
        <Route path="project/:id/prompt" element={<ErrorBoundary><PromptInput /></ErrorBoundary>} />
        <Route path="audit" element={<AdminRoute><ErrorBoundary><AuditLogs /></ErrorBoundary></AdminRoute>} />
        <Route path="learning" element={<ErrorBoundary><Learning /></ErrorBoundary>} />
        <Route path="dashboard/tools/learning" element={<Navigate to="/learning" replace />} />
        <Route path="intelligence" element={<ErrorBoundary><IntelligenceHub /></ErrorBoundary>} />
        <Route path="search" element={<ErrorBoundary><SearchPage /></ErrorBoundary>} />
        <Route path="deployments" element={<ErrorBoundary><Deployments /></ErrorBoundary>} />
        <Route path="health" element={<ErrorBoundary><SystemHealth /></ErrorBoundary>} />
        <Route path="guardian" element={<ErrorBoundary><Guardian /></ErrorBoundary>} />
        <Route path="agents" element={<ErrorBoundary><Agents /></ErrorBoundary>} />
        <Route path="designer" element={<ErrorBoundary><ProjectDesigner /></ErrorBoundary>} />
        <Route path="designer/:id" element={<ErrorBoundary><ProjectDesigner /></ErrorBoundary>} />
        <Route path="workspaces" element={<ErrorBoundary><Workspaces /></ErrorBoundary>} />
        <Route path="*" element={<NotFound />} />
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

export default App;
