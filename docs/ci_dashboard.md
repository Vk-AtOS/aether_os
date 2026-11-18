# Dashboard CI

`.github/workflows/ci.yml` job `dashboard` runs, in `dashboard/`: `npm ci --no-audit --no-fund`, `npm run lint`
(eslint), `npm test` (`vitest run`; tests in `dashboard/src/__tests__`), `npm audit --omit=dev --audit-level=high`
and `npm run build` (`vite build`). Every step is blocking.

`npm ci` needs the committed `dashboard/package-lock.json` (tracked in git). The `Dockerfile` (line 9),
`deploy/deploy.sh` (line 72) and `deploy/setup_vps.sh` (line 77) use the same `npm ci`. After changing
`package.json`, run `npm install` and commit both files.

- `VITE_PREVIEW_FRAME_SRC` (build time) is the preview origin put into the meta CSP `frame-src` of
  `dashboard/index.html` (`dashboard/vite.config.js:6-13`). Unset means `frame-src 'self'` only, so previews
  are blocked.
- Browser click-through specs: `npm run test:e2e` (Playwright, specs in `dashboard/e2e`). They are not in the CI
  job. Whether they need a running backend or only `npx playwright install chromium`: not verified here.
- The `npm audit` step needs network access; run it locally where the network is available.
- Whether the job has ever run on GitHub: not verified.
