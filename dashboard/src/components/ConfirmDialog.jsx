import React, { useEffect } from 'react';
import { AlertTriangle } from 'lucide-react';

/**
 * ConfirmDialog — accessible modal for destructive action confirmation.
 *
 * Props:
 *   open      {boolean}  — show/hide
 *   title     {string}   — dialog heading
 *   message   {string}   — body copy
 *   onConfirm {Function} — called when user clicks Confirm
 *   onCancel  {Function} — called when user clicks Cancel or presses Escape
 *   danger    {boolean}  — red confirm button (default false = accent colour)
 */
const ConfirmDialog = ({ open, title, message, onConfirm, onCancel, danger = false }) => {
  // Close on Escape key
  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (e.key === 'Escape') onCancel?.(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      role="presentation"
      onClick={onCancel}
    >
      <div
        className="bg-panel border border-border rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-msg"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 mb-4">
          {danger && (
            <div className="w-9 h-9 rounded-full bg-red-500/10 flex items-center justify-center shrink-0 mt-0.5">
              <AlertTriangle className="w-4.5 h-4.5 text-red-400" aria-hidden="true" />
            </div>
          )}
          <div>
            <h3 id="confirm-dialog-title" className="text-base font-bold text-bright">{title}</h3>
            <p id="confirm-dialog-msg" className="text-sm text-muted mt-1 leading-relaxed">{message}</p>
          </div>
        </div>
        <div className="flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-muted border border-border rounded-lg hover:text-bright hover:border-border/80 transition-colors focus:outline-none focus:ring-2 focus:ring-accent/40"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={`px-4 py-2 text-sm font-bold rounded-lg text-white transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-panel ${
              danger
                ? 'bg-red-600 hover:bg-red-500 focus:ring-red-500'
                : 'bg-accent hover:bg-accent/90 focus:ring-accent'
            }`}
            autoFocus
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmDialog;
