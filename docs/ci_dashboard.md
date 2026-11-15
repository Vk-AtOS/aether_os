# Dashboard CI

`.github/workflows/ci.yml` job `dashboard` runs `npm ci`, `npm run lint`, `npm test` (vitest, jsdom component
tests in `dashboard/src/__tests__`) and `npm run build`. `npm ci` needs the committed
`dashboard/package-lock.json` (the same install the Dockerfile, deploy.sh and setup_vps.sh use). Update it
with `npm install` after changing package.json and commit both.

- `VITE_PREVIEW_FRAME_SRC` (build time) is the preview origin for the meta CSP `frame-src`; unset means previews are blocked (fails closed).
- Browser click-through specs: `npm run test:e2e` (Playwright, `dashboard/e2e`); they stub the API, so they need only
  `npx playwright install chromium`, no running backend. They are not in the default CI job (browser download); add a job when wanted.
- `npm audit --audit-level=high --omit=dev` is the supply-chain check; run it where the network is available.
