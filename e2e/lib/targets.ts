import * as fs from 'fs';
import * as path from 'path';

export type Mode = 'selftest' | 'R' | 'W' | 'M' | 'T';

export const RUN_ID: string = process.env.E2E_RUN_ID || 'adhoc';
export const E2E_ROOT = path.resolve(__dirname, '..');
export const LEDGER_DIR = path.join(E2E_ROOT, 'ledger', 'raw', RUN_ID);

export function modeForProject(projectName: string): Mode {
  switch (projectName) {
    case 'live-r': return 'R';
    case 'sandbox-w': return 'W';
    case 'live-m': return 'M';
    case 'trade-t': return 'T';
    default: return 'selftest';
  }
}

export const isLiveMode = (m: Mode): boolean => m === 'R' || m === 'M' || m === 'T';

/** Live projects refuse to run without the operator's explicit env opt-in. */
export function assertLiveConfirmed(mode: Mode): void {
  if (isLiveMode(mode) && process.env.E2E_CONFIRM_LIVE !== '1') {
    throw new Error(
      '[e2e] this project targets the LIVE engine — set E2E_CONFIRM_LIVE=1 to confirm. ' +
      'Standing rule: never run the pytest gate concurrently with live driving ' +
      '(tests/conftest.py live-data tripwire would fire and mask real findings).',
    );
  }
}

/**
 * Reachability preflight. The harness NEVER starts or stops an engine itself
 * (no webServer block by design) — it verifies and refuses instead.
 */
export async function preflight(baseURL: string, mode: Mode): Promise<void> {
  assertLiveConfirmed(mode);
  let res: Response;
  try {
    res = await fetch(baseURL + '/v3', { redirect: 'manual' });
  } catch (e) {
    throw new Error(`[e2e] engine unreachable at ${baseURL} (mode ${mode}) — start it first. ${e}`);
  }
  if (res.status !== 200) throw new Error(`[e2e] ${baseURL}/v3 returned HTTP ${res.status}`);
  const html = await res.text();
  if (html.includes('v3 bundle not built')) {
    throw new Error(`[e2e] ${baseURL}/v3 served the missing-bundle panel — build the frontend first`);
  }
  // Sandbox identity check — the seeded marker account must be present; a live-shaped
  // engine (the operator's real account names) hard-fails here. Belt-and-braces on top
  // of provision_test_env.py's own refusals.
  if (mode === 'W') {
    const res2 = await fetch(baseURL + '/accounts');
    const accounts = (await res2.json()) as { name: string }[];
    const names = accounts.map((a) => a.name);
    if (!names.includes('Sandbox Second (Binance Futures)')) {
      throw new Error(
        `[e2e] ${baseURL} does not look like the seeded sandbox (accounts: ${names.join(', ')}) — REFUSING mutations`,
      );
    }
  }
  fs.mkdirSync(LEDGER_DIR, { recursive: true });
  const info = {
    runId: RUN_ID,
    mode,
    baseURL,
    bundle: await bundleHash(baseURL),
    startedAt: new Date().toISOString(),
  };
  fs.writeFileSync(path.join(LEDGER_DIR, 'runinfo.json'), JSON.stringify(info, null, 2));
  // eslint-disable-next-line no-console
  console.log(`[e2e] preflight ok — ${baseURL} mode=${mode} bundle=${info.bundle} runId=${RUN_ID}`);
}

/** Content-derived bundle hash — pins WHICH build a run tested. */
export async function bundleHash(baseURL: string): Promise<string> {
  try {
    const res = await fetch(baseURL + '/static/v3/manifest.json');
    const man = (await res.json()) as Record<string, unknown>;
    const joined = JSON.stringify(man);
    const m = joined.match(/app\.([0-9a-f]{10})\.js/);
    return m ? m[1] : 'unknown';
  } catch {
    return 'unknown';
  }
}
