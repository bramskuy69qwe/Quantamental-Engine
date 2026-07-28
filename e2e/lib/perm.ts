import type { Page } from '@playwright/test';

/** Deterministic RNG — same seed, same walk. Seed goes in the run report. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function permutations<T>(items: T[]): T[][] {
  if (items.length <= 1) return [items];
  const out: T[][] = [];
  for (let i = 0; i < items.length; i++) {
    const rest = [...items.slice(0, i), ...items.slice(i + 1)];
    for (const p of permutations(rest)) out.push([items[i], ...p]);
  }
  return out;
}

/**
 * The ordering set for a cluster: FULL permutations when <= 4 members
 * (<= 24 sequences), otherwise every ordered pair A->B and B->A — pairwise
 * coverage catches the large majority of interaction faults without the
 * factorial bill (the operator's "button 1 then 2, and 2 then 1", scoped).
 */
export function orderings<T>(members: T[]): T[][] {
  if (members.length <= 4) return permutations(members);
  const out: T[][] = [];
  for (let i = 0; i < members.length; i++) {
    for (let j = 0; j < members.length; j++) {
      if (i !== j) out.push([members[i], members[j]]);
    }
  }
  return out;
}

export interface Fp {
  tabs: string[];
  periods: string[];
  panes: Record<string, { searches: string[]; facets: string[]; sorts: string[] }>;
}

/**
 * End-state fingerprint for round-trip invariance — pure UI-CONTROL state:
 * active tabs/periods (digit-stripped), and per-pane search values, facet-select
 * values and active sort columns. Row content AND row counts are deliberately
 * excluded — on a live engine both change under real trading (mark/uPnL ticks
 * produced 17 false divergences in run -1124; live position churn produced 10
 * row-count false divergences in run -1143, including a table legitimately
 * vanishing at zero rows). An ordering bug leaks CONTROL state — assert that.
 */
export async function fingerprint(page: Page): Promise<Fp> {
  return page.evaluate(() => {
    const strip = (s: string) => s.replace(/\d+/g, '').replace(/\s+/g, ' ').trim().slice(0, 60);
    const txt = (el: Element) => strip(el.textContent || '');
    const panes: Record<string, { searches: string[]; facets: string[]; sorts: string[] }> = {};
    document.querySelectorAll('.qe-pane-body').forEach((body) => {
      const head = body.parentElement?.querySelector('.qe-pane-head');
      const name = head ? txt(head) : '(no pane)';
      const rec = {
        searches: [...body.querySelectorAll('.qe-dl-search input')].map(
          (i) => (i as HTMLInputElement).value,
        ),
        facets: [...body.querySelectorAll('.qe-dl-facet select')].map(
          (s) => (s as HTMLSelectElement).value,
        ),
        sorts: [...body.querySelectorAll('th.qe-sort.on')].map(txt),
      };
      if (rec.searches.length || rec.facets.length || rec.sorts.length) panes[name] = rec;
    });
    return {
      tabs: [...document.querySelectorAll('.qe-tabs > button.on')].map(txt),
      periods: [...document.querySelectorAll('.qe-period > button.on')].map(txt),
      panes,
    };
  });
}

/** Diffs two fingerprints; panes absent on either side are ignored (live tables vanish at zero rows). */
export function fingerprintDiff(base: Fp, after: Fp): string[] {
  const diffs: string[] = [];
  if (JSON.stringify(base.tabs) !== JSON.stringify(after.tabs)) {
    diffs.push(`tabs: ${JSON.stringify(base.tabs)} -> ${JSON.stringify(after.tabs)}`);
  }
  if (JSON.stringify(base.periods) !== JSON.stringify(after.periods)) {
    diffs.push(`periods: ${JSON.stringify(base.periods)} -> ${JSON.stringify(after.periods)}`);
  }
  for (const [pane, b] of Object.entries(base.panes)) {
    const a = after.panes[pane];
    if (!a) continue;
    if (JSON.stringify(b) !== JSON.stringify(a)) {
      diffs.push(`pane ${pane}: ${JSON.stringify(b)} -> ${JSON.stringify(a)}`);
    }
  }
  return diffs;
}
