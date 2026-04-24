import React, { useEffect } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';

// This route just triggers the modal and redirects back to /projects
const NewProject = () => {
  const navigate = useNavigate();
  const ctx = useOutletContext() || {};

  useEffect(() => {
    if (ctx.openNewProject) {
      ctx.openNewProject();
    }
    navigate('/projects', { replace: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return null;
};

export default NewProject;
