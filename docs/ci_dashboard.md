# CI for the dashboard (snippet for A7, who owns .github/workflows)

The dashboard has `npm test` (vitest) and `npm run lint`; CI has no dashboard job yet.

```yaml
  dashboard:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: dashboard } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22 }
      - run: npm install --no-audit --no-fund
      - run: npm run lint
      - run: npm test
      - run: npm run build
        env:
          # frame-src of the meta CSP; the preview origin of the target environment
          VITE_PREVIEW_FRAME_SRC: https://*.preview.example.com
      - run: npm audit --audit-level=high --omit=dev   # fails the job on high+ in runtime deps
```

Notes
- `VITE_PREVIEW_FRAME_SRC` is read by `dashboard/vite.config.js` at build time. Unset means previews are blocked by the meta CSP (fails closed).
- `package-lock.json` is git-ignored (.gitignore:98), so CI uses `npm install`; un-ignore and commit it to get `npm ci`, caching and a reproducible audit.
- `npm run build:ci` runs lint, tests and build in one go for local use.
