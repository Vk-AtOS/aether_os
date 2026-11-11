import React, { useEffect, useState } from 'react';
import ConfirmDialog from './ConfirmDialog';

// A drop-in, awaitable replacement for window.confirm that uses the app's own
// dialog: `if (!(await confirmAction('Delete this?'))) return;`
// One <ConfirmHost /> is mounted in App; it shows whichever request is pending.
let show = null;

export const confirmAction = (message, title = 'Are you sure?') =>
  new Promise((resolve) => {
    // If the host is not mounted there is nothing to ask with; refuse rather than proceed.
    if (!show) return resolve(false);
    show({ message, title, resolve });
  });

export const ConfirmHost = () => {
  const [request, setRequest] = useState(null);

  useEffect(() => {
    show = setRequest;
    return () => { show = null; };
  }, []);

  const answer = (ok) => {
    request?.resolve(ok);
    setRequest(null);
  };

  return (
    <ConfirmDialog
      open={Boolean(request)}
      danger
      title={request?.title}
      message={request?.message}
      onConfirm={() => answer(true)}
      onCancel={() => answer(false)}
    />
  );
};
