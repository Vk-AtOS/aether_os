import { createContext, useContext } from 'react';

export const ToastContext = createContext(null);

export const useToast = () => {
  const ctx = useContext(ToastContext);
  if (!ctx) return (msg) => console.log('[toast]', msg); // graceful fallback
  return ctx;
};
