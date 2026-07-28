import type { Page } from '@playwright/test';
import { Control } from './manifest';
import { SNAPSHOT_SRC } from './inpage';
import { PageName, gotoPage, screenRoot, PAGES } from './selectors';

/** Tab strips keyed by a digit-normalized label signature (stable across count changes). */
const STRIPS_FN = `
(() => {
  const txt = (el) => (el.textContent || '').replace(/\\s+/g, ' ').trim();
  const norm = (s) => {
    s = (s || '').slice(0, 60).trim();
    if (/[a-zA-Z]/.test(s)) s = s.replace(/\\d[\\d.,%:/]*/g, ' ').replace(/\\s+/g, ' ').trim();
    return s.toLowerCase().slice(0, 40);
  };
  return [...document.querySelectorAll('.qe-tabs')].map((s) => ({
    sig: [...s.querySelectorAll(':scope > button')].map((b) => norm(txt(b))).join('|'),
    labels: [...s.querySelectorAll(':scope > button')].map((b) => txt(b).slice(0, 40)),
  }));
})()
`;

interface RawControl extends Omit<Control, 'id' | 'page' | 'source'> {}

async function clickTabBySig(page: Page, sig: string, idx: number): Promise<boolean> {
  const handle = await page.evaluateHandle(
    ({ sig, idx }: { sig: string; idx: number }) => {
      const txt = (el: Element) => (el.textContent || '').replace(/\s+/g, ' ').trim();
      const norm = (s: string) => {
        s = (s || '').slice(0, 60).trim();
        if (/[a-zA-Z]/.test(s)) s = s.replace(/\d[\d.,%:/]*/g, ' ').replace(/\s+/g, ' ').trim();
        return s.toLowerCase().slice(0, 40);
      };
      for (const strip of document.querySelectorAll('.qe-tabs')) {
        const btns = [...strip.querySelectorAll(':scope > button')];
        if (btns.map((b) => norm(txt(b))).join('|') === sig) return btns[idx] || null;
      }
      return null;
    },
    { sig, idx },
  );
  const el = handle.asElement();
  if (!el) return false;
  try {
    await el.click();
    return true;
  } catch {
    return false;
  }
}

const MAX_TAB_CLICKS = 40;

/**
 * Crawl one page: initial snapshot, then a bounded tab-walk — the ONLY clicks the
 * crawler performs are `.qe-tabs > button` (client-side switches + GET fetches; the
 * mode-R guard is armed throughout, so any tab firing a non-GET becomes a CRIT
 * finding, which is the tripwire doing its job). Re-scans after each click so nested
 * strips (Models detail tabs) are walked too. Enumeration logic lives in
 * lib/inpage.ts — shared with the Phase-2 sweep's element finder by construction.
 */
export async function crawlPage(page: Page, pageName: PageName): Promise<Control[]> {
  const label = PAGES.find((p) => p.name === pageName)!.label;
  await gotoPage(page, pageName);
  await screenRoot(page, label).waitFor({ state: 'visible', timeout: 15_000 });
  await page.waitForTimeout(3_000);

  const acc = new Map<string, Control>();
  const snap = async (tabPath: string): Promise<void> => {
    const list = (await page.evaluate(SNAPSHOT_SRC)) as unknown as RawControl[];
    for (const raw of list) {
      const c: Control = {
        ...raw,
        page: pageName,
        source: 'crawled',
        tabPath: tabPath || undefined,
        id: '',
      };
      c.id = `${c.page}/${c.pane}/${c.kind}:${c.name}`;
      const key = `${c.id}|${c.title || ''}`;
      const prev = acc.get(key);
      if (prev) prev.instances = Math.max(prev.instances, c.instances);
      else acc.set(key, c);
    }
  };

  await snap('');
  const visited = new Set<string>();
  let clicks = 0;
  for (let round = 0; round < 6 && clicks < MAX_TAB_CLICKS; round++) {
    const strips = (await page.evaluate(STRIPS_FN)) as unknown as { sig: string; labels: string[] }[];
    let clickedThisRound = false;
    for (const s of strips) {
      for (let i = 0; i < s.labels.length && clicks < MAX_TAB_CLICKS; i++) {
        const key = `${s.sig}::${i}`;
        if (visited.has(key)) continue;
        visited.add(key);
        if (!(await clickTabBySig(page, s.sig, i))) continue;
        clicks += 1;
        clickedThisRound = true;
        await page.waitForTimeout(1_200);
        await snap(s.labels[i]);
      }
    }
    if (!clickedThisRound) break;
  }
  return [...acc.values()];
}
