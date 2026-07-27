import type { BrowserContext } from '@playwright/test';
import type { Mode } from './targets';

export type GuardReporter = (cls: 'mode-r-violation' | 'external-call', detail: string) => void;

// Operator-approved live mutation surface (plan §Operator decisions #3).
const ALLOW_M: RegExp[] = [
  /^POST \/calculator\/calculate$/,
  /^POST \/calculator\/cancel\/[^/]+$/,
  /^POST \/calculator\/clear$/,
  /^POST \/calculator\/window$/,
  /^POST \/api\/news\/refresh$/,
];

/** `METHOD /path` allowlists per mode. Everything non-GET outside the list is aborted. */
const ALLOW: Record<Mode, RegExp[]> = {
  selftest: [],
  // R: read-only sweep. /calculator/clear is the restore protocol for the ONE GET with a
  // server-side side effect (GET /api/price/{ticker} rebuilds the market-WS subscription set).
  R: [/^POST \/calculator\/clear$/],
  M: ALLOW_M,
  // T: trade scenarios — operator-supervised linkage/reason actions join the M surface.
  T: [
    ...ALLOW_M,
    /^POST \/orders\/\d+\/manual_link$/,
    /^POST \/orders\/\d+\/mark_unplanned$/,
    /^PUT \/history\/close_reason\/\d+$/,
  ],
  // W: sandbox — full mutation permitted (the whole point of the sandbox).
  W: [/.*/],
};

/**
 * The Mode-R tripwire. Route-intercepts the whole context:
 *  - non-GET to the engine outside the mode's allowlist → abort + CRIT `mode-r-violation`
 *  - any subresource/fetch to a NON-engine origin → abort + `external-call` (the app is
 *    fully vendored; an external call is itself a finding)
 *  - top-level navigations to external origins (news "open ↗" links) abort quietly so a
 *    sweep can never leave the app.
 * Aborts surface to the page as failed fetches; the collector's requestfailed listener
 * skips ERR_BLOCKED_BY_CLIENT so guard hits are not double-reported.
 */
export async function installGuard(
  context: BrowserContext,
  mode: Mode,
  engineOrigin: string,
  report: GuardReporter,
): Promise<void> {
  const allow = ALLOW[mode];
  await context.route('**/*', async (route) => {
    const req = route.request();
    const method = req.method().toUpperCase();
    let url: URL;
    try {
      url = new URL(req.url());
    } catch {
      return route.continue();
    }
    if (url.origin !== engineOrigin) {
      if (req.resourceType() !== 'document') {
        report('external-call', `${method} ${url.href}`);
      }
      return route.abort('blockedbyclient');
    }
    if (method === 'GET' || method === 'HEAD' || method === 'OPTIONS') return route.continue();
    const key = `${method} ${url.pathname}`;
    if (allow.some((re) => re.test(key))) return route.continue();
    report('mode-r-violation', key);
    return route.abort('blockedbyclient');
  });
}
