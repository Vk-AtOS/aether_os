import React from 'react';

const EmptyState = ({ icon: Icon, title, description, action, actionLabel }) => (
  <div className="flex flex-col items-center justify-center py-16 px-4 text-center space-y-4">
    <div className="w-16 h-16 rounded-2xl bg-border/20 flex items-center justify-center">
      {Icon && <Icon className="w-8 h-8 text-muted/40" />}
    </div>
    <div className="space-y-1">
      <p className="text-base font-bold text-bright">{title}</p>
      {description && <p className="text-sm text-muted max-w-sm">{description}</p>}
    </div>
    {action && (
      <button
        onClick={action}
        className="mt-2 px-5 py-2 bg-accent hover:bg-accent/90 text-white text-sm font-bold rounded-lg transition-colors"
      >
        {actionLabel}
      </button>
    )}
  </div>
);

export default EmptyState;
