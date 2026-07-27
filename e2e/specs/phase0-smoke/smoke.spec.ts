/**
 * Phase 0 smoke — every page of /v3 loads clean against the LIVE engine (mode R:
 * the guard aborts any non-GET except the restore-protocol POST /calculator/clear).
 *
 * "Clean" = the collector gate: no pageerror, console error, failed/4xx/5xx request,
 * error boundary, degraded pane foot, or mode-R violation. Two nav paths are covered:
 * fresh full-load per page (hash routing) and the real nav controls (incl. the ⚙ gear).
 *
 * Run:  $env:E2E_CONFIRM_LIVE='1'; $env:E2E_PHASE='0'; npm run e2e:smoke
 * Never run the pytest gate concurrently with live driving (conftest tripwire).
 */
import { test, expect } from '../../lib/collector';
import { PAGES, gotoPage, navButton, screenRoot } from '../../lib/selectors';

// First full poll cycle: 5 s lanes (+ chrome 10 s tick) with slack. Fixed wait is
// deliberate — the app polls forever, so networkidle never settles.
const SETTLE_MS = 6_000;

test.describe('phase 0 — smoke', () => {
  for (const p of PAGES) {
    test(`${p.label} loads clean (fresh mount)`, async ({ page, collector }) => {
      await gotoPage(page, p.name);
      await expect(screenRoot(page, p.label)).toBeVisible({ timeout: 15_000 });
      await page.waitForTimeout(SETTLE_MS);
      await collector.checkpoint(`${p.label} after-load`);
    });
  }

  test('nav walk — the real nav controls route every page (incl. the ⚙ gear)', async ({
    page,
    collector,
  }) => {
    await gotoPage(page, 'Dashboard');
    await expect(screenRoot(page, '01 Dashboard')).toBeVisible({ timeout: 15_000 });
    for (const p of PAGES.filter((x) => x.name !== 'Dashboard')) {
      collector.setControl(`nav/${p.name}`);
      await navButton(page, p.name).click();
      await expect(screenRoot(page, p.label)).toBeVisible({ timeout: 10_000 });
      await page.waitForTimeout(1_500);
      await collector.checkpoint(`nav→${p.label}`);
    }
  });
});
