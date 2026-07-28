/**
 * Phase 1 — control inventory. Crawls all 9 pages read-only (the ONLY clicks are
 * `.qe-tabs` buttons; the mode-R guard is armed, so a tab firing a non-GET becomes a
 * CRIT finding). Produces manifest/controls.pending.json, then classifies every
 * control via manifest/classification.json and pins the result:
 *
 *  - any UNCLASSIFIED control fails the run (the review loop);
 *  - against a committed controls.json, NEW ids or VANISHED non-dataDependent ids
 *    fail (the manifest is a UI-surface regression pin); vanished dataDependent ids
 *    are notes (live data varies).
 *
 * Bootstrap / deliberate update:  E2E_ACCEPT_MANIFEST=1  rewrites controls.json.
 * Run:  $env:E2E_CONFIRM_LIVE='1'; $env:E2E_PHASE='1'; npm run e2e:crawl
 */
import { test, expect } from '../../lib/collector';
import { crawlPage } from '../../lib/crawler';
import {
  CONTROLS_PATH,
  Control,
  PENDING_PATH,
  classify,
  diffManifests,
  hoistChrome,
  loadCommitted,
  loadDeclared,
  loadRules,
  writeManifest,
} from '../../lib/manifest';
import { PAGES } from '../../lib/selectors';

const collected: Control[] = [];

test.describe.serial('phase 1 — control inventory', () => {
  for (const p of PAGES) {
    test(`crawl ${p.label}`, async ({ page, collector }) => {
      collector.setControl(`crawl/${p.name}`);
      const controls = await crawlPage(page, p.name);
      expect(controls.length, `${p.label} should expose at least a handful of controls`).toBeGreaterThan(3);
      collected.push(...controls);
      await collector.checkpoint(`${p.label} after-crawl`);
    });
  }

  test('merge, classify, drift-pin', async () => {
    expect(collected.length, 'crawl accumulated nothing — did the page tests run?').toBeGreaterThan(50);

    const merged = [...hoistChrome(collected), ...loadDeclared()];
    const rules = loadRules();
    const classified = merged.map((c) => classify(c, rules));
    writeManifest(PENDING_PATH, classified);

    const unclassified = classified.filter((c) => c.risk === 'unclassified').map((c) => c.id).sort();
    expect(
      unclassified,
      `UNCLASSIFIED controls — add rules to manifest/classification.json (pending manifest written):`,
    ).toEqual([]);

    const committed = loadCommitted();
    if (!committed || process.env.E2E_ACCEPT_MANIFEST === '1') {
      writeManifest(CONTROLS_PATH, classified);
      const byRisk = new Map<string, number>();
      for (const c of classified) byRisk.set(c.risk!, (byRisk.get(c.risk!) || 0) + 1);
      console.log(
        `[e2e] manifest ${committed ? 'UPDATED' : 'BOOTSTRAPPED'}: ${classified.length} controls — ` +
          [...byRisk.entries()].map(([k, v]) => `${k}=${v}`).join(' '),
      );
      return;
    }

    const diff = diffManifests(classified, committed);
    for (const id of diff.missingDataDependent) {
      console.log(`[e2e] note: dataDependent control absent this run (live data varies): ${id}`);
    }
    expect(diff.added, 'NEW controls since the committed manifest — review + E2E_ACCEPT_MANIFEST=1').toEqual([]);
    expect(diff.missing, 'controls VANISHED since the committed manifest (UI-surface regression?)').toEqual([]);
  });
});
