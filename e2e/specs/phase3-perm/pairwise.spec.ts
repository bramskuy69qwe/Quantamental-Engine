/**
 * Phase 3 — cluster order-permutations (mode R, live engine).
 *
 * For each declared cluster: full permutations (<=4 members) or all ordered pairs,
 * each ordering from a clean reset (storage reset + fresh goto; the DataList
 * cluster re-runs each ordering with a tab-switch remount too). Collector oracles
 * gate every ordering; orderings composed only of ROUND-TRIP controls
 * (input/select/sort — actOnControl restores each) must fingerprint back to the
 * baseline, else `ordering-divergence`.
 *
 * Run:  $env:E2E_CONFIRM_LIVE='1'; $env:E2E_PHASE='3'; npm run e2e:perm
 */
import * as fs from 'fs';
import * as path from 'path';
import { test, expect } from '../../lib/collector';
import { Control, controlsFor, loadCommitted } from '../../lib/manifest';
import { PAGES, PageName, gotoPage, screenRoot } from '../../lib/selectors';
import { actOnControl } from '../../lib/sweep';
import { fingerprint, fingerprintDiff, orderings } from '../../lib/perm';
import { resetAppStorage } from '../../lib/storage';
import { LEDGER_DIR } from '../../lib/targets';

interface ClusterDef {
  id: string;
  page: PageName;
  reset: 'reload';
  remountAlso?: { away: string; back: string };
  maxMembers: number;
  members: string[];
  note?: string;
}

const CLUSTERS = (
  JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', '..', 'manifest', 'clusters.json'), 'utf8'),
  ) as { clusters: ClusterDef[] }
).clusters;

const committed = loadCommitted();
if (!committed) throw new Error('[e2e] no manifest/controls.json — run Phase 1 first');
const SAFE = controlsFor('R', committed).filter((c) => c.risk === 'safe');

const ROUNDTRIP_KINDS = new Set(['input', 'select', 'sort']);

function resolveMembers(def: ClusterDef): { members: Control[]; dropped: string[] } {
  const seen = new Set<string>();
  const members: Control[] = [];
  for (const pat of def.members) {
    const re = new RegExp(pat);
    for (const c of SAFE.filter((x) => re.test(x.id)).sort((a, b) => a.id.localeCompare(b.id))) {
      if (!seen.has(c.id)) {
        seen.add(c.id);
        members.push(c);
      }
    }
  }
  const dropped = members.slice(def.maxMembers).map((c) => c.id);
  return { members: members.slice(0, def.maxMembers), dropped };
}

const PERM_OUT = path.join(LEDGER_DIR, 'perm-outcomes.jsonl');
const persist = (row: object): void => {
  fs.mkdirSync(LEDGER_DIR, { recursive: true });
  fs.appendFileSync(PERM_OUT, JSON.stringify(row) + '\n', 'utf8');
};

test.describe('phase 3 — cluster order-permutations', () => {
  for (const def of CLUSTERS) {
    test(`cluster ${def.id} (${def.page})`, async ({ page, collector }) => {
      test.setTimeout(900_000);
      const label = PAGES.find((p) => p.name === def.page)!.label;
      const { members, dropped } = resolveMembers(def);
      for (const d of dropped) console.log(`[e2e] cluster ${def.id}: DROPPED over maxMembers: ${d}`);
      console.log(`[e2e] cluster ${def.id}: members = ${members.map((m) => m.id).join(' · ')}`);
      expect(members.length, `cluster ${def.id} resolved no members — patterns stale?`).toBeGreaterThan(1);

      const reset = async (): Promise<void> => {
        // Same-hash goto is SAME-DOCUMENT navigation — no remount, React state
        // (tab/period) leaks across "resets" (run 3-20260728-1124's history
        // divergences). about:blank forces a real document teardown.
        await resetAppStorage(page).catch(() => undefined);
        await page.goto('about:blank');
        await gotoPage(page, def.page);
        await screenRoot(page, label).waitFor({ state: 'visible', timeout: 15_000 });
        await page.waitForTimeout(2_500);
      };
      const remount = async (): Promise<void> => {
        for (const t of [def.remountAlso!.away, def.remountAlso!.back]) {
          const tab = page.locator('.qe-tabs > button', { hasText: t }).first();
          await tab.click().catch(() => undefined);
          await page.waitForTimeout(900);
        }
      };

      await reset();
      const baseline = await fingerprint(page);
      const seqs = orderings(members);
      const resetStyles: ('reload' | 'remount')[] = def.remountAlso ? ['reload', 'remount'] : ['reload'];
      console.log(`[e2e] cluster ${def.id}: ${seqs.length} orderings × ${resetStyles.length} reset styles`);

      for (const style of resetStyles) {
        for (let s = 0; s < seqs.length; s++) {
          const seq = seqs[s];
          const orderLabel = `${def.id}[${style}]#${s}: ${seq.map((c) => c.name).join(' → ')}`;
          if (style === 'reload') await reset();
          else {
            await remount();
          }
          const acted: string[] = [];
          for (const c of seq) {
            collector.setControl(`${def.id}/${c.id}`);
            const o = await actOnControl(page, c);
            acted.push(`${c.name}:${o.action}`);
          }
          await collector.checkpoint(orderLabel);
          const roundtripOnly = seq.every((c) => ROUNDTRIP_KINDS.has(c.kind));
          let fpMatch: boolean | null = null;
          if (roundtripOnly && style === 'reload') {
            const fp = await fingerprint(page);
            const diffs = fingerprintDiff(baseline, fp);
            fpMatch = diffs.length === 0;
            if (!fpMatch) {
              collector.note(
                'ordering-divergence',
                `round-trip ordering did not restore baseline: ${orderLabel}`,
                diffs.join('\n'),
              );
            }
          }
          persist({ cluster: def.id, style, seq: seq.map((c) => c.id), acted, fpMatch });
        }
      }
    });
  }
});
