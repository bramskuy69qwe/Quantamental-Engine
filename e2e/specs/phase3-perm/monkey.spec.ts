/**
 * Phase 3 — seeded monkey (mode R, live engine). The long tail beyond pairwise:
 * a random walk over each page's SAFE controls with a deterministic RNG — every
 * crash replays from the seed + breadcrumb trail. Page-scoped (nav excluded); a
 * step that navigates away is corrected and recorded.
 *
 * Run:  $env:E2E_CONFIRM_LIVE='1'; $env:E2E_PHASE='3'; [$env:E2E_SEED=N] npm run e2e:monkey
 */
import * as fs from 'fs';
import * as path from 'path';
import { test, expect } from '../../lib/collector';
import { controlsFor, loadCommitted } from '../../lib/manifest';
import { PAGES, gotoPage, screenRoot } from '../../lib/selectors';
import { actOnControl } from '../../lib/sweep';
import { mulberry32 } from '../../lib/perm';
import { LEDGER_DIR, RUN_ID } from '../../lib/targets';

const committed = loadCommitted();
if (!committed) throw new Error('[e2e] no manifest/controls.json — run Phase 1 first');

const STEPS = Number(process.env.E2E_MONKEY_STEPS || 120);
// Seed must be IDENTICAL in the runner and every worker process (titles and the
// walk both derive from it) — Date.now() differs per process and made every test
// title mismatch ("Test not found in the worker"). RUN_ID is env-inherited and
// stable; E2E_SEED overrides for replay.
const seedFrom = (s: string): number => {
  let h = 0;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) | 0;
  return Math.abs(h) || 1;
};
const BASE_SEED = Number(process.env.E2E_SEED || 0) || seedFrom(RUN_ID);

const BREADCRUMBS = path.join(LEDGER_DIR, 'monkey-breadcrumbs.jsonl');
const crumb = (row: object): void => {
  fs.mkdirSync(LEDGER_DIR, { recursive: true });
  fs.appendFileSync(BREADCRUMBS, JSON.stringify(row) + '\n', 'utf8');
};

test.describe('phase 3 — seeded monkey', () => {
  for (let pi = 0; pi < PAGES.length; pi++) {
    const p = PAGES[pi];
    test(`monkey ${p.label} (${STEPS} steps)`, async ({ page, collector }) => {
      test.setTimeout(600_000);
      const rng = mulberry32(BASE_SEED + pi);
      const candidates = controlsFor('R', committed!).filter(
        (c) =>
          c.risk === 'safe' &&
          (c.page === p.name || c.page === 'chrome') &&
          c.cluster !== 'nav' &&
          !/load into pre-trade|use backfill tab/.test(c.id) && // client-side navigators
          c.kind !== 'link',
      );
      expect(candidates.length).toBeGreaterThan(5);

      await gotoPage(page, p.name);
      await expect(screenRoot(page, p.label)).toBeVisible({ timeout: 15_000 });
      await page.waitForTimeout(3_000);

      let acted = 0;
      let absent = 0;
      let navCorrections = 0;
      for (let step = 0; step < STEPS; step++) {
        const c = candidates[Math.floor(rng() * candidates.length)];
        collector.setControl(`monkey/${c.id}`);
        const o = await actOnControl(page, c);
        crumb({ seed: BASE_SEED + pi, page: p.name, step, id: c.id, action: o.action });
        if (o.action === 'acted') acted++;
        else absent++;
        // A step may have routed elsewhere (unexpected navigator = worth knowing).
        const stillOn = await screenRoot(page, p.label).isVisible().catch(() => false);
        if (!stillOn) {
          navCorrections++;
          collector.note(
            'harness-note',
            `monkey step ${step} on ${c.id} navigated off ${p.label} — corrected`,
          );
          await gotoPage(page, p.name);
          await screenRoot(page, p.label).waitFor({ state: 'visible', timeout: 15_000 });
          await page.waitForTimeout(1_500);
        }
        if (step % 5 === 4) await collector.checkpoint(`monkey step ${step}`);
      }
      await collector.checkpoint('monkey end');
      console.log(
        `[e2e] monkey ${p.label}: acted=${acted} absent/skip=${absent} navCorrections=${navCorrections} seed=${BASE_SEED + pi}`,
      );
      fs.mkdirSync(LEDGER_DIR, { recursive: true });
      fs.appendFileSync(
        path.join(LEDGER_DIR, 'monkey-report.jsonl'),
        JSON.stringify({ page: p.name, seed: BASE_SEED + pi, steps: STEPS, acted, absent, navCorrections }) + '\n',
        'utf8',
      );
    });
  }
});
