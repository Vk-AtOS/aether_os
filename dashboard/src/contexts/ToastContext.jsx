import React, { createContext, useContext, useState, useCallback } from 'react';
import { CheckCircle, AlertTriangle, Info, X } from 'lucide-react';

const ToastContext = createContext(null);

const ICONS = { success: CheckCircle, error: AlertTriangle, info: Info };
const COLORS = {
  success: 'border-emerald-500/40 bg-emerald-900/20 text-emerald-300',
  error: 'border-red-500/40 bg-red-900/20 text-red-300',
  info: 'border-accent/40 bg-accent/10 text-accent',
};

export const ToastProvider = ({ children }) => {
  const [toasts, setToasts] = useState([]);

  const toast = useCallback((msg, type = 'info', duration = 3500) => {
    const id = Date.now() + Math.random();
    setToasts(t => [...t, { id, msg, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), duration);
  }, []);

  const dismiss = (id) => setToasts(t => t.filter(x => x.id !== id));

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none">
        {toasts.map(t => {
          const Icon = ICONS[t.type] || Info;
          return (
            <div key={t.id}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl border shadow-2xl backdrop-blur-sm pointer-events-auto max-w-sm text-sm font-medium ${COLORS[t.type] || COLORS.info}`}
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span className="flex-1">{t.msg}</span>
              <button onClick={() => dismiss(t.id)} className="shrink-0 opacity-60 hover:opacity-100"><X className="w-3.5 h-3.5" /></button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const ctx = useContext(ToastContext);
  if (!ctx) return (msg) => console.log('[toast]', msg); // graceful fallback
  return ctx;
};
