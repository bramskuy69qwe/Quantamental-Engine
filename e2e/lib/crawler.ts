import type { Page } from '@playwright/test';
import { Control, SelectorRecipe } from './manifest';
import { PageName, gotoPage, screenRoot, PAGES } from './selectors';

/**
 * In-page control snapshot. Names are NORMALIZED (digit-runs stripped when the text
 * carries letters, lowercased) so live-data counts ("Closed 47") don't churn ids;
 * pure-numeric names ("75" per-page button) keep their digits — they ARE the identity.
 * Identical (pane|kind|name|title) elements collapse into one record with an instance
 * count (per-row buttons on live tables would otherwise drift with the data).
 */
const SNAPSHOT_FN = `
(() => {
  const txt = (el) => (el.textContent || '').replace(/\\s+/g, ' ').trim();
  const norm = (s) => {
    s = (s || '').slice(0, 60).trim();
    if (/[a-zA-Z]/.test(s)) s = s.replace(/\\d[\\d.,%:/]*/g, ' ').replace(/\\s+/g, ' ').trim();
    return s.toLowerCase().slice(0, 40);
  };
  // Pane title = head text MINUS its ornaments (badges, buttons, selects, period
  // strips, grips, dots) — the raw head concatenates right-slot content into the name.
  const headTitle = (h) => {
    const clone = h.cloneNode(true);
    clone.querySelectorAll('.qe-badge, button, select, input, .qe-period, .qe-grip, .qe-pane-dots, .qe-pane-refresh, .qe-dot')
      .forEach((n) => n.remove());
    return (clone.textContent || '').replace(/[·⋯…]+/g, ' ').replace(/\\s+/g, ' ').trim();
  };
  const paneOf = (el) => {
    const body = el.closest('.qe-pane-body');
    if (body) {
      const h = body.parentElement && body.parentElement.querySelector('.qe-pane-head');
      if (h) return [norm(headTitle(h)) || '(pane)', headTitle(h).slice(0, 40)];
    }
    const head = el.closest('.qe-pane-head');
    if (head) return [norm(headTitle(head)) || '(pane)', headTitle(head).slice(0, 40)];
    if (el.closest('.qe-page-header')) return ['(page-header)', '(page-header)'];
    if (el.closest('.qe-dl-tools')) return ['(dl-tools)', '(dl-tools)'];
    return ['(chrome-or-page)', '(chrome-or-page)'];
  };
  // Nearest short label-ish text for unnamed inputs/selects: walk up a few levels
  // looking at previous siblings (the app's <Lbl>…</Lbl> convention).
  const nearLabel = (el) => {
    let n = el;
    for (let up = 0; up < 3 && n && n !== document.body; up++) {
      let sib = n.previousElementSibling;
      let hops = 0;
      while (sib && hops < 2) {
        const t = txt(sib);
        if (t && t.length <= 24 && /[a-zA-Z]/.test(t) && !sib.querySelector('input,select,button')) return t;
        sib = sib.previousElementSibling;
        hops++;
      }
      n = n.parentElement;
    }
    return '';
  };
  const out = new Map();
  const push = (el, kind, rawName) => {
    if (el.closest('#qe-e2e-overlay')) return;
    const [pane, paneRaw] = paneOf(el);
    const name = norm(rawName) || '(unnamed)';
    const title = el.getAttribute && (el.getAttribute('title') || undefined);
    const key = pane + '|' + kind + '|' + name + '|' + (title || '');
    const prev = out.get(key);
    if (prev) { prev.instances += 1; return; }
    let selector;
    if (el.id) selector = { strategy: 'id', value: '#' + el.id };
    else if (title) selector = { strategy: 'title', value: title };
    else if (name && name !== '(unnamed)') selector = { strategy: 'text', value: name, scope: paneRaw };
    else selector = { strategy: 'struct', value: kind, scope: paneRaw };
    out.set(key, {
      pane, paneRaw, kind, name,
      title, elemId: el.id || undefined,
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true' || undefined,
      instances: 1, selector,
      sampleText: txt(el).slice(0, 40) || undefined,
    });
  };
  document.querySelectorAll('button').forEach((el) => {
    const kind = el.closest('.qe-tabs') ? 'tab' : el.closest('.qe-period') ? 'period' : 'button';
    push(el, kind, el.getAttribute('title') || txt(el));
  });
  document.querySelectorAll('select').forEach((el) => {
    // Label text minus the select's own subtree (label textContent includes options).
    let lbl = '';
    const wrap = el.closest('label');
    if (wrap) {
      const clone = wrap.cloneNode(true);
      clone.querySelectorAll('select').forEach((n) => n.remove());
      lbl = (clone.textContent || '').trim();
    }
    push(el, 'select', el.getAttribute('title') || lbl || nearLabel(el) || 'select');
  });
  document.querySelectorAll('input, textarea').forEach((el) =>
    push(el, 'input', el.id || el.getAttribute('placeholder') || el.getAttribute('title') || nearLabel(el) || el.type || 'input'));
  document.querySelectorAll('th.qe-sort').forEach((el) => push(el, 'sort', txt(el)));
  document.querySelectorAll('a[href]').forEach((el) => push(el, 'link', txt(el) || el.getAttribute('href') || 'link'));
  return [...out.values()];
})()
`;

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
 * strips (Models detail tabs) are walked too.
 */
export async function crawlPage(page: Page, pageName: PageName): Promise<Control[]> {
  const label = PAGES.find((p) => p.name === pageName)!.label;
  await gotoPage(page, pageName);
  await screenRoot(page, label).waitFor({ state: 'visible', timeout: 15_000 });
  await page.waitForTimeout(3_000);

  const acc = new Map<string, Control>();
  const snap = async (tabPath: string): Promise<void> => {
    const list = (await page.evaluate(SNAPSHOT_FN)) as unknown as RawControl[];
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
