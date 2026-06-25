import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Repositories from './pages/Repositories';
import Patches from './pages/Patches';
import Scan from './pages/Scan';
import Patterns from './pages/Patterns';
import AIEngine from './pages/AIEngine';
import Notifications from './pages/Notifications';
import Compliance from './pages/Compliance';
import Settings from './pages/Settings';
import JobDetail from './pages/JobDetail';
import Layout from './components/Layout';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router basename="/app">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Layout />}>
            <Route index element={<Navigate to="/feed" replace />} />
            <Route path="feed" element={<Dashboard />} />
            <Route path="feed/jobs/:jobId" element={<JobDetail />} />
            <Route path="repositories" element={<Repositories />} />
            <Route path="patches" element={<Patches />} />
            <Route path="scan" element={<Scan />} />
            <Route path="patterns" element={<Patterns />} />
            <Route path="ai-engine" element={<AIEngine />} />
            <Route path="notifications" element={<Notifications />} />
            <Route path="compliance" element={<Compliance />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </Router>
    </QueryClientProvider>
  );
}

export default App;
