import { useMemo } from 'react';
import { api } from '../api';

export const decode = (token) => {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    return JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
  } catch {
    return null;
  }
};

export const useRole = () => {
  const token = api.getToken();
  return useMemo(() => {
    const payload = token ? decode(token) : null;
    const role = payload?.role ?? 'viewer';
    const userId = payload?.user_id ?? payload?.sub ?? null;
    const isOwner = role === 'owner';
    const isAdmin = role === 'owner' || role === 'admin';
    const isMember = role === 'member';
    const isViewer = role === 'viewer';
    const canWrite = !isViewer;
    return { role, userId, isOwner, isAdmin, isMember, isViewer, canWrite };
  }, [token]);
};
