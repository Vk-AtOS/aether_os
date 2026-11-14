// Absolute URL of an in-app path. The SPA lives under Vite's base (/dashboard/), so a return
// URL built from window.location.origin alone lands outside it (Stripe, full-page redirects).
export const appPath = (path) => `${import.meta.env.BASE_URL.replace(/\/$/, '')}${path.startsWith('/') ? path : `/${path}`}`;
export const appUrl = (path) => `${window.location.origin}${appPath(path)}`;
