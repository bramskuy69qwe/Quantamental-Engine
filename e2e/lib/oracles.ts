import type { Page } from '@playwright/test';

export interface OracleHit {
  kind: 'error-boundary' | 'foot-degraded' | 'toast';
  page: string;
  pane: string;
  text: string;
}

/**
 * PaneFoot degraded tiers (qeFootState, primitives.jsx). Deliberately EXCLUDES the
 * healthy/transient tiers (`connected [Nms]`, `delayed [Nms]`, `loading…`) — a sweep
 * flagging every transient `delayed` would drown the ledger; `delayed` is asserted
 * explicitly where a test cares.
 */
export const DEGRADED_FOOT_RE_SRC =
  '(no network|corrupt|endpoint not found|unauthorized \\((?:401|403)\\)|server error|request failed|render failed|showing last data|reconnecting)';

/**
 * (Re)arm the transient-toast MutationObserver and expose the buffer. Idempotent and
 * re-entrant: document.open() (page.setContent, document.write) can silently kill an
 * observer armed by an init script, so this is evaluated BOTH as the context init
 * script AND at every checkpoint scan (pending records are drained before re-arming).
 * Captures .qe-toast insertions only — the class-less bespoke Linkage/Models toasts
 * are asserted by text in scenarios. The #qe-e2e-overlay subtree is excluded.
 */
export const OBSERVER_ENSURE_SRC = `
(() => {
  const w = window;
  w.__qeObs = w.__qeObs || [];
  const consider = (n) => {
    if (!n || n.nodeType !== 1) return;
    if (n.closest && n.closest('#qe-e2e-overlay')) return;
    const hits = [];
    if (n.classList && n.classList.contains('qe-toast')) hits.push(n);
    if (n.querySelectorAll) hits.push(...n.querySelectorAll('.qe-toast'));
    for (const t of hits) {
      w.__qeObs.push({ kind: 'toast', text: (t.textContent || '').slice(0, 200) });
      if (w.__qeObs.length > 200) w.__qeObs.shift();
    }
  };
  if (w.__qeObsMo) {
    try { for (const m of w.__qeObsMo.takeRecords()) for (const n of m.addedNodes) consider(n); } catch (e) {}
    try { w.__qeObsMo.disconnect(); } catch (e) {}
  }
  w.__qeObsMo = new MutationObserver((muts) => {
    for (const m of muts) for (const n of m.addedNodes) consider(n);
  });
  w.__qeObsMo.observe(document, { childList: true, subtree: true });
})();
`;

/**
 * The checkpoint scanner — one evaluate covering the PERSISTENT oracles:
 *  - PaneErrorBoundary: `.qe-empty.err .qe-empty-msg` containing "failed to render"
 *  - degraded pane feet: PaneFoot has NO className — it is the div sibling directly
 *    after `.qe-pane-body` (primitives.jsx renders body then foot)
 * plus a drain of the toast buffer, then a re-arm of the observer (setContent /
 * document.write can have killed it).
 */
export async function scanOracles(page: Page): Promise<OracleHit[]> {
  const hits = await page.evaluate((degradedSrc: string) => {
    const degraded = new RegExp(degradedSrc, 'i');
    const out: { kind: string; page: string; pane: string; text: string }[] = [];
    const screen =
      document.querySelector('[data-screen-label]')?.getAttribute('data-screen-label') || '?';

    const paneTitle = (el: Element | null): string => {
      const root = el?.closest('.qe-pane-body')?.parentElement || el?.parentElement || null;
      const head = root?.querySelector('.qe-pane-head');
      return (head?.textContent || '').trim().slice(0, 60) || '(no pane)';
    };

    document.querySelectorAll('.qe-empty.err .qe-empty-msg').forEach((el) => {
      const t = (el.textContent || '').trim();
      if (/failed to render/i.test(t)) {
        out.push({ kind: 'error-boundary', page: screen, pane: paneTitle(el), text: t });
      }
    });

    document.querySelectorAll('.qe-pane-body').forEach((body) => {
      const foot = body.nextElementSibling;
      if (!foot || foot.tagName !== 'DIV') return;
      const t = (foot.textContent || '').trim();
      if (t && degraded.test(t)) {
        out.push({ kind: 'foot-degraded', page: screen, pane: paneTitle(body), text: t.slice(0, 200) });
      }
    });

    const w = window as unknown as { __qeObsMo?: MutationObserver; __qeObs?: { text: string }[] };
    try {
      if (w.__qeObsMo) {
        for (const m of w.__qeObsMo.takeRecords()) {
          m.addedNodes.forEach((n) => {
            const el = n as Element;
            if (el.nodeType === 1 && el.classList?.contains('qe-toast')) {
              w.__qeObs!.push({ text: (el.textContent || '').slice(0, 200) });
            }
          });
        }
      }
    } catch {
      /* observer dead */
    }
    if (w.__qeObs && w.__qeObs.length) {
      for (const b of w.__qeObs.splice(0)) {
        out.push({ kind: 'toast', page: screen, pane: '(toast)', text: b.text });
      }
    }
    return out as never;
  }, DEGRADED_FOOT_RE_SRC);
  // Re-arm AFTER the drain so mutations between scans are always observed.
  await page.evaluate(OBSERVER_ENSURE_SRC).catch(() => undefined);
  return hits as OracleHit[];
}
