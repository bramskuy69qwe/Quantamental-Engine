import { defineConfig } from '@playwright/test';

// One runId per invocation, stable across workers (workers inherit the runner's env).
const stamp = new Date().toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 13);
const RUN_ID = process.env.E2E_RUN_ID || `${process.env.E2E_PHASE || 'run'}-${stamp}`;
process.env.E2E_RUN_ID = RUN_ID;

const LIVE = 'http://127.0.0.1:8000';
const SANDBOX = 'http://127.0.0.1:8010';

export default defineConfig({
  testDir: './specs',
  // ONE stateful engine per target: GET /api/price/{ticker} mutates the server-global
  // calculator symbol + market-WS subscription set, pubsub is in-process, and live is the
  // operator's real account. Parallel contexts would cross-contaminate — do not raise.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 10_000 },
  outputDir: `./ledger/raw/${RUN_ID}/test-results`,
  reporter: [
    ['list'],
    ['json', { outputFile: `./ledger/raw/${RUN_ID}/report.json` }],
  ],
  use: {
    // The service worker (qre-v3 as of 2026-07-31) is cache-first for
    // /static/vendor, whose filenames are stable, so it would mask stale assets
    // and real 4xx/5xx from the response oracles.
    // NB blocking it here is also why this suite could never have caught the
    // CRIT that worker shipped with — it cached every API response and replayed
    // it on failure. That behaviour is pinned in
    // tests/test_service_worker_default_deny.py instead, at the source level.
    serviceWorkers: 'block',
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    viewport: { width: 1600, height: 900 },
  },
  projects: [
    // Engine-independent harness self-tests (no baseURL, no preflight, no guard).
    { name: 'selftest', testMatch: 'selftest/**/*.spec.ts' },
    // R: read-only vs the LIVE engine. Guard aborts every non-GET except POST /calculator/clear.
    { name: 'live-r', use: { baseURL: LIVE }, testMatch: 'phase{0,1,2,3}-*/**/*.spec.ts' },
    // W: full-mutation vs the SANDBOX engine (provisioned worktree OUTSIDE the repo — .env parent-walk).
    { name: 'sandbox-w', use: { baseURL: SANDBOX }, testMatch: 'phase4-*/**/*.spec.ts' },
    // M: operator-approved live mutations (calc create/cancel/clear/window + news refresh) with cleanup.
    { name: 'live-m', use: { baseURL: LIVE }, testMatch: 'phase5-*/**/*.spec.ts' },
    // T: operator-in-the-loop trade scenarios — headed, full trace (this IS the acceptance evidence).
    {
      name: 'trade-t',
      use: { baseURL: LIVE, trace: 'on', video: 'retain-on-failure', headless: false },
      testMatch: 'phase6-*/**/*.spec.ts',
      timeout: 0,
    },
  ],
});
