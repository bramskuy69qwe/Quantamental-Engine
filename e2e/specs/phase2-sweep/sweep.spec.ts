/**
 * Phase 2 — exhaustive single-action sweep (mode R, live engine).
 *
 * One generated test per (page, pane): every safe control is actioned once with
 * probe-and-restore semantics; a collector checkpoint runs after each action; the
 * quasi ticker is probed LAST in its pane and restored via the Clear button (the one
 * POST the mode-R guard allows). Mutating controls never appear here — controlsFor('R')
 * filters to safe+quasi, and the guard would abort + CRIT anything that slipped through.
 *
 * Chrome controls run once from Dashboard; the nav cluster is skipped (smoke's nav
 * walk already covers it). Coverage is reported per control — no silent caps.
 *
 * Run:  $env:E2E_CONFIRM_LIVE='1'; $env:E2E_PHASE='2'; npm run e2e:sweep
 */
import * as fs from 'fs';
import * as path from 'path';
import { test, expect } from '../../lib/collector';
import { Control, controlsFor, loadCommitted } from '../../lib/manifest';
import { PAGES, PageName, gotoPage, screenRoot } from '../../lib/selectors';
import { SweepOutcome, actOnControl, restoreCalcSymbol } from '../../lib/sweep';
import { LEDGER_DIR } from '../../lib/targets';

const committed = loadCommitted();
if (!committed) throw new Error('[e2e] no manifest/controls.json — run Phase 1 (e2e:crawl) first');

const sweepable = controlsFor('R', committed).filter((c) => {
  if (c.page === 'chrome' && c.cluster === 'nav') return false; // smoke nav-walk covers these
  return true;
});

// Group by page → pane; quasi controls sort last within their pane (restore follows).
const byPage = new Map<string, Map<string, Control[]>>();
for (const c of sweepable) {
  const pageMap = byPage.get(c.page) || new Map<string, Control[]>();
  const arr = pageMap.get(c.pane) || [];
  arr.push(c);
  pageMap.set(c.pane, arr);
  byPage.set(c.page, pageMap);
}
for (const pageMap of byPage.values()) {
  for (const arr of pageMap.values()) {
    arr.sort((a, b) => {
      const q = Number(a.risk === 'quasi') - Number(b.risk === 'quasi');
      if (q) return q;
      const t = (a.tabPath || '').localeCompare(b.tabPath || '');
      return t || a.id.localeCompare(b.id);
    });
  }
}

// Outcomes persist to disk per test: a failing test restarts the worker (wiping
// module state), and a harvest sweep must neither lose coverage data nor let one
// failure skip the remaining panes (NO .serial here — that skips on failure).
const OUTCOMES_PATH = path.join(LEDGER_DIR, 'sweep-outcomes.jsonl');
const persistOutcomes = (rows: SweepOutcome[]): void => {
  fs.mkdirSync(LEDGER_DIR, { recursive: true });
  fs.appendFileSync(OUTCOMES_PATH, rows.map((r) => JSON.stringify(r)).join('\n') + '\n', 'utf8');
};
const loadOutcomes = (): SweepOutcome[] =>
  fs.existsSync(OUTCOMES_PATH)
    ? fs.readFileSync(OUTCOMES_PATH, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l) as SweepOutcome)
    : [];

const hostPage = (page: string): PageName => (page === 'chrome' ? 'Dashboard' : (page as PageName));

test.describe('phase 2 — exhaustive sweep', () => {
  for (const [pageName, panes] of [...byPage.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    for (const [pane, controls] of [...panes.entries()].sort(([a], [b]) => a.localeCompare(b))) {
      test(`sweep ${pageName} :: ${pane} (${controls.length})`, async ({ page, collector }) => {
        const host = hostPage(pageName);
        const label = PAGES.find((p) => p.name === host)!.label;
        await gotoPage(page, host);
        await expect(screenRoot(page, label)).toBeVisible({ timeout: 15_000 });
        await page.waitForTimeout(3_000);

        const testOutcomes: SweepOutcome[] = [];
        let probedTicker = false;
        try {
          for (const c of controls) {
            collector.setControl(c.id);
            const o = await actOnControl(page, c);
            testOutcomes.push(o);
            if (o.action === 'acted') {
              if (c.risk === 'quasi') probedTicker = true;
              await collector.checkpoint(c.id);
            }
          }
          if (probedTicker) {
            const restored = await restoreCalcSymbol(page, collector);
            testOutcomes.push({
              id: 'restore/calculator-clear',
              action: restored ? 'acted' : 'error',
              detail: restored ? 'server calc symbol cleared' : 'Clear button not found — RESTORE FAILED',
            });
            expect(restored, 'quasi-ticker restore protocol must complete').toBe(true);
            await collector.checkpoint('post-restore');
          }
        } finally {
          persistOutcomes(testOutcomes);
        }
      });
    }
  }

  test('coverage report — no silent caps', async () => {
    const outcomes = loadOutcomes();
    const counts = new Map<string, number>();
    for (const o of outcomes) counts.set(o.action, (counts.get(o.action) || 0) + 1);
    const total = outcomes.length;
    const acted = counts.get('acted') || 0;
    fs.mkdirSync(LEDGER_DIR, { recursive: true });
    fs.writeFileSync(
      path.join(LEDGER_DIR, 'sweep-report.json'),
      JSON.stringify(
        {
          total,
          counts: Object.fromEntries(counts),
          skippedOrAbsent: outcomes.filter((o) => o.action !== 'acted'),
        },
        null,
        2,
      ) + '\n',
      'utf8',
    );
    console.log(
      `[e2e] sweep coverage: ${acted}/${total} acted — ` +
        [...counts.entries()].map(([k, v]) => `${k}=${v}`).join(' '),
    );
    const errors = outcomes.filter((o) => o.action === 'error');
    expect(errors, 'sweep action errors (element vanished mid-action / click failed)').toEqual([]);
    expect(acted / total, 'finder should reach most of the manifest').toBeGreaterThan(0.6);
  });
});
