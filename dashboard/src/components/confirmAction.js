// A drop-in, awaitable replacement for window.confirm that uses the app's own
// dialog: `if (!(await confirmAction('Delete this?'))) return;`
// One <ConfirmHost /> (components/ConfirmHost.jsx) is mounted in App; it shows whichever request is pending.
let show = null;

export const setConfirmHandler = (fn) => { show = fn; };

export const confirmAction = (message, title = 'Are you sure?') =>
  new Promise((resolve) => {
    // If the host is not mounted there is nothing to ask with; refuse rather than proceed.
    if (!show) return resolve(false);
    show({ message, title, resolve });
  });
