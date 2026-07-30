import type { Page } from '@playwright/test';

/** Every storage key the app writes (verified inventory, 2026-07-30 —
 *  `qe.page` removed: the shell no longer persists the active page). */
export const LOCAL_KEYS = [
  'qe.workspace.locked',
  'qe.ws.layout.dashboard',
  'qe.v3.calc_state',
  'qe.v3.calc_history',
  'qe.haltUntil',
  'qe.haltAt',
] as const;

export const SESSION_KEYS = ['qe.v3.calc_result'] as const;

/** Reset app state between scenarios (fresh contexts already start clean). */
export async function resetAppStorage(page: Page): Promise<void> {
  await page.evaluate(
    ({ lk, sk }) => {
      for (const k of lk) try { localStorage.removeItem(k); } catch { /* disabled ctx */ }
      for (const k of sk) try { sessionStorage.removeItem(k); } catch { /* disabled ctx */ }
    },
    { lk: [...LOCAL_KEYS], sk: [...SESSION_KEYS] },
  );
}

/**
 * Drift check: any `qe.*` key outside the known inventory means the app grew a new
 * storage surface the harness (and the reset protocol) does not cover.
 */
export async function unknownAppKeys(page: Page): Promise<string[]> {
  return page.evaluate(
    ({ lk, sk }) => {
      const known = new Set([...lk, ...sk]);
      const out: string[] = [];
      try {
        for (let i = 0; i < localStorage.length; i++) {
          const k = localStorage.key(i) || '';
          if (k.startsWith('qe.') && !known.has(k)) out.push(`local:${k}`);
        }
        for (let i = 0; i < sessionStorage.length; i++) {
          const k = sessionStorage.key(i) || '';
          if (k.startsWith('qe.') && !known.has(k)) out.push(`session:${k}`);
        }
      } catch { /* disabled ctx */ }
      return out;
    },
    { lk: [...LOCAL_KEYS], sk: [...SESSION_KEYS] },
  );
}
