import { defineConfig } from '@playwright/test';

// Click-through specs run against the built dashboard (vite preview) with the API stubbed in the browser
// (e2e/helpers.js), so they need no backend. `npm run test:e2e`; first time: `npx playwright install chromium`.
export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: 'http://localhost:4173/dashboard/', trace: 'retain-on-failure' },
  webServer: {
    command: 'npm run build && npx vite preview --port 4173 --strictPort',
    url: 'http://localhost:4173/dashboard/',
    reuseExistingServer: !process.env.CI,
    timeout: 180000,
  },
});
