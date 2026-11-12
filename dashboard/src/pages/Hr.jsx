import React, { Suspense } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { Users } from 'lucide-react';
import { PageHead, Notice } from '../components/velaris/shared';
import { Spinner } from '../components/prime/parts';
import { useRole } from '../hooks/useRole';
import { HR_TABS } from '../components/hr/tabs';

const SCREENS = {
  requisitions: React.lazy(() => import('../components/hr/Requisitions')),
  pipeline: React.lazy(() => import('../components/hr/Pipeline')),
  resume: React.lazy(() => import('../components/hr/Resume')),
  postings: React.lazy(() => import('../components/hr/Postings')),
  forms: React.lazy(() => import('../components/hr/Forms')),
  interviews: React.lazy(() => import('../components/hr/Interviews')),
  kits: React.lazy(() => import('../components/hr/Kits')),
  offers: React.lazy(() => import('../components/hr/Offers')),
  esign: React.lazy(() => import('../components/hr/ESign')),
  onboarding: React.lazy(() => import('../components/hr/Onboarding')),
  employees: React.lazy(() => import('../components/hr/Employees')),
  policies: React.lazy(() => import('../components/hr/Policies')),
};

const Hr = () => {
  const { tab = 'requisitions' } = useParams();
  const { isAdmin } = useRole();
  const Screen = SCREENS[tab];
  if (!Screen) return <Navigate to="/hr/requisitions" replace />;
  const label = HR_TABS.find(([id]) => id === tab)[1];
  return (
    <div className="space-y-4">
      <PageHead icon={Users} title={`HR: ${label}`} sub="Hiring and people operations through Velaris. Changes wait for approval before they take effect." />
      {!isAdmin && <Notice tone="warn">HR screens need the owner or admin role in this organisation. Velaris will refuse what your role does not allow.</Notice>}
      <Suspense fallback={<Spinner />}><Screen key={tab} /></Suspense>
    </div>
  );
};

export default Hr;
