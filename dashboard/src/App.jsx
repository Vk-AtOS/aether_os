import React, { useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import Layout from './components/Layout';
// Static (auth-critical — must not lazy-load)
import Login from './pages/Login';
import OAuthCallback from './pages/OAuthCallback';
import { api, setNavigate } from './api';
import { useRole } from './hooks/useRole';
import ErrorBoundary from './components/ErrorBoundary';

// Lazy (all other pages)
const Dashboard         = React.lazy(() => import('./pages/Dashboard'));
const NewProject        = React.lazy(() => import('./pages/NewProject'));
const ProjectView       = React.lazy(() => import('./pages/ProjectView'));
const ProjectsList      = React.lazy(() => import('./pages/ProjectsList'));
const PhaseDetail       = React.lazy(() => import('./pages/PhaseDetail'));
const ClientPortal      = React.lazy(() => import('./pages/ClientPortal'));
const Settings          = React.lazy(() => import('./pages/Settings'));
const Compliance        = React.lazy(() => import('./pages/Compliance'));
const Marketplace       = React.lazy(() => import('./pages/Marketplace'));
const NewProjectWizard  = React.lazy(() => import('./pages/NewProjectWizard'));
const ConnectorHub      = React.lazy(() => import('./pages/ConnectorHub'));
const PluginManager     = React.lazy(() => import('./pages/PluginManager'));
const MemoryInspector   = React.lazy(() => import('./pages/MemoryInspector'));
const CostDashboard     = React.lazy(() => import('./pages/CostDashboard'));
const AdminUsers        = React.lazy(() => import('./pages/AdminUsers'));
const Billing           = React.lazy(() => import('./pages/Billing'));
const Profile           = React.lazy(() => import('./pages/Profile'));
const WebhookSettings   = React.lazy(() => import('./pages/WebhookSettings'));
const FrontendBuilder   = React.lazy(() => import('./pages/FrontendBuilder'));
const BackendBuilder    = React.lazy(() => import('./pages/BackendBuilder'));
const PromptInput       = React.lazy(() => import('./pages/PromptInput'));
const AuditLogs         = React.lazy(() => import('./pages/AuditLogs'));
const Learning          = React.lazy(() => import('./pages/Learning'));
const Legal             = React.lazy(() => import('./pages/Legal'));
const IntelligenceHub   = React.lazy(() => import('./pages/IntelligenceHub'));
const SearchPage        = React.lazy(() => import('./pages/SearchPage'));
const Deployments       = React.lazy(() => import('./pages/Deployments'));
const SystemHealth      = React.lazy(() => import('./pages/SystemHealth'));
const Guardian          = React.lazy(() => import('./pages/Guardian'));
const Signup            = React.lazy(() => import('./pages/Signup'));
const Pricing           = React.lazy(() => import('./pages/Pricing'));
const Agents            = React.lazy(() => import('./pages/Agents'));
const GlobalPatternsTuning = React.lazy(() => import('./pages/GlobalPatternsTuning'));
const ProjectDesigner   = React.lazy(() => import('./pages/ProjectDesigner'));
const Workspaces        = React.lazy(() => import('./pages/Workspaces'));


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
      <Route path="/signup"  element={<ErrorBoundary><Suspense fallback={<PageSkeleton />}><Signup /></Suspense></ErrorBoundary>} />
      <Route path="/pricing" element={<ErrorBoundary><Suspense fallback={<PageSkeleton />}><Pricing /></Suspense></ErrorBoundary>} />
      <Route path="/legal"   element={<ErrorBoundary><Suspense fallback={<PageSkeleton />}><Legal /></Suspense></ErrorBoundary>} />
      <Route path="/auth/callback" element={<OAuthCallback />} />
      <Route path="/portal/:id" element={<ErrorBoundary><Suspense fallback={<PageSkeleton />}><ClientPortal /></Suspense></ErrorBoundary>} />

      <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
        <Route path="new" element={<ErrorBoundary><NewProjectWizard /></ErrorBoundary>} />
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
