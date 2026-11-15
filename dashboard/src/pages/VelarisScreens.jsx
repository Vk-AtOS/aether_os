import React from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { Briefcase } from 'lucide-react';
import { PageHead, Notice } from '../components/velaris/shared';
import ActionScreen from '../components/velaris/ActionScreen';
import { screenById } from '../components/velaris/screens';
import { useRole } from '../hooks/useRole';

// /work/:screen: the Velaris gap screens (screens.js). The gateway enforces the role; this hides what would be refused.
const VelarisScreens = () => {
  const { screen: id } = useParams();
  const { isAdmin, isViewer } = useRole();
  const screen = screenById(id);
  if (!screen) return <Navigate to="/work/my-leave" replace />;
  const blocked = isViewer || (screen.role === 'admin' && !isAdmin);
  return (
    <div className="space-y-4">
      <PageHead icon={Briefcase} title={screen.title} sub={screen.sub} />
      {blocked
        ? <Notice tone="warn">{isViewer ? 'Your role may look at Velaris but not act in it.' : 'This screen needs the owner or admin role in this organisation.'}</Notice>
        : <ActionScreen key={screen.id} screen={screen} />}
    </div>
  );
};

export default VelarisScreens;
