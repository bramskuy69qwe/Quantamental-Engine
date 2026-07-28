/**
 * Phase 4 — degraded-state walk (sandbox ONLY: this spec KILLS the engine).
 * The one test class impossible against the live engine: with a loaded page,
 * hard-kill the backend and assert every pane walks to the truthful degraded
 * tiers (`no network — engine unreachable` / `… · showing last data`), with
 * ZERO error boundaries; then relaunch and assert recovery.
 *
 * File is m2- so it runs AFTER the mutation sweep (alphabetical order).
 */
import { test, expect } from '../../lib/collector';
import { gotoPage, screenRoot } from '../../lib/selectors';
import { scanOracles } from '../../lib/oracles';
import { sandboxKill, sandboxLaunch, sandboxPid } from '../../lib/sandbox';

test.describe('phase 4 — degraded state (engine kill)', () => {
  test('feet degrade truthfully when the engine dies; page never crashes', async ({
    page,
    collector,
  }) => {
    test.setTimeout(420_000);
    // These are EXPECTED here — the whole point is to provoke them; the real
    // assertions are explicit below (degraded feet present, boundaries absent).
    collector.mute('foot-degraded', 'requestfailed', 'console-error', 'console-warn', 'http-5xx');

    await gotoPage(page, 'Dashboard');
    await expect(screenRoot(page, '01 Dashboard')).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(4_000);

    expect(sandboxPid(), 'sandbox must be running before the kill').not.toBeNull();
    collector.setControl('degraded/engine-kill');
    expect(sandboxKill()).toBe(true);

    // Poll lanes: chrome 10s + snapshot 15/30s + SSE death — give two full cycles.
    await page.waitForTimeout(40_000);
    const hits = await scanOracles(page);
    const degradedFeet = hits.filter(
      (h) => h.kind === 'foot-degraded' && /no network|showing last data|reconnecting/i.test(h.text),
    );
    const boundaries = hits.filter((h) => h.kind === 'error-boundary');
    expect(
      degradedFeet.length,
      `engine dead 40s — expected >=2 truthfully degraded feet, saw: ${hits.map((h) => `${h.kind}:${h.text}`).join(' | ')}`,
    ).toBeGreaterThanOrEqual(2);
    expect(boundaries, 'an engine outage must NEVER crash a pane').toEqual([]);

    collector.setControl('degraded/relaunch');
    await sandboxLaunch();
    await gotoPage(page, 'Dashboard');
    await expect(screenRoot(page, '01 Dashboard')).toBeVisible({ timeout: 20_000 });
    await page.waitForTimeout(8_000);
    const after = await scanOracles(page);
    expect(
      after.filter((h) => h.kind === 'foot-degraded' && /no network/i.test(h.text)),
      'after relaunch + reload the no-network tier must clear',
    ).toEqual([]);
    expect(after.filter((h) => h.kind === 'error-boundary')).toEqual([]);
  });
});
