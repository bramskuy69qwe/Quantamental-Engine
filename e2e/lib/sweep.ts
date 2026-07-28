import type { ElementHandle, Page } from '@playwright/test';
import type { Collector } from './collector';
import { Control } from './manifest';
import { finderSrc } from './inpage';

export interface SweepOutcome {
  id: string;
  action:
    | 'acted'
    | 'absent'
    | 'disabled'
    | 'skipped-kind'
    | 'skipped-date'
    | 'skipped-declared-synthetic'
    | 'error';
  detail?: string;
}

const controlKey = (c: Control): string => `${c.pane}|${c.kind}|${c.name}|${c.title || ''}`;

async function findControl(page: Page, c: Control): Promise<ElementHandle<HTMLElement> | null> {
  try {
    const h = await page.evaluateHandle(finderSrc(controlKey(c)));
    return h.asElement() as ElementHandle<HTMLElement> | null;
  } catch (e) {
    if (process.env.E2E_DEBUG_FINDER === '1') {
      console.log(`[finder-ex] ${c.id} :: ${String(e).slice(0, 300)}`);
    }
    return null;
  }
}

/**
 * Panes flap during debounced refetch re-renders (a restored search/select fires
 * another fetch ~250 ms later, briefly swapping the table out) — a single-instant
 * lookup misses elements that are back 400 ms later. Raw evaluateHandle bypasses
 * Playwright's auto-waiting, so the waiting is ours to do: retry the find.
 * (Run 2-20260728-0446: 126 sort headers "not found" this way — all found fine
 * on a settled page.)
 */
async function findControlRetry(
  page: Page,
  c: Control,
  attempts = 4,
  delayMs = 400,
  tag = '?',
): Promise<ElementHandle<HTMLElement> | null> {
  for (let i = 0; i < attempts; i++) {
    const el = await findControl(page, c);
    if (process.env.E2E_DEBUG_FINDER === '1' && c.kind === 'sort') {
      console.log(`[find] ${tag}#${i} ${c.id} -> ${el ? 'FOUND' : 'null'}`);
    }
    if (el) return el;
    await page.waitForTimeout(delayMs);
  }
  return findControl(page, c);
}

/**
 * React re-renders REPLACE nodes: a probe typed into a DataList search re-renders
 * the toolbar, detaching the very element we hold — the restore step then throws
 * "Element is not attached to the DOM" (16/20 errors of the first sweep run were
 * exactly this). Every action step therefore re-finds its element on detach and
 * retries once.
 */
async function withRefind<T>(
  page: Page,
  c: Control,
  fn: (el: ElementHandle<HTMLElement>) => Promise<T>,
): Promise<T> {
  let el = await findControlRetry(page, c, 4, 400, 'entry');
  if (!el) throw new Error('element not found @withRefind-entry');
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn(el);
    } catch (e) {
      const msg = String(e);
      if (attempt >= 2 || !/not attached|detached|Element is not/i.test(msg)) throw e;
      await page.waitForTimeout(250);
      el = await findControlRetry(page, c);
      if (!el) throw new Error(`element vanished after re-render: ${msg.slice(0, 120)}`);
    }
  }
}

/** Close any app modal left open by an action (ModelDialog ✕ carries title="Close"). */
export async function dismissModals(page: Page): Promise<void> {
  for (let i = 0; i < 2; i++) {
    const close = page.locator('button[title="Close"]').first();
    if (!(await close.isVisible().catch(() => false))) break;
    await close.click().catch(() => undefined);
    await page.waitForTimeout(200);
  }
}

/** Activate the tab a control was discovered under (labels are digit-normalized). */
export async function ensureTab(page: Page, tabPathRaw: string): Promise<void> {
  const label = tabPathRaw.replace(/\d[\d.,%:/]*/g, ' ').replace(/\s+/g, ' ').trim();
  if (!label) return;
  const tab = page.locator('.qe-tabs > button', { hasText: label }).first();
  if (!(await tab.isVisible().catch(() => false))) return;
  const isOn = await tab.evaluate((el) => el.classList.contains('on')).catch(() => true);
  if (!isOn) {
    await tab.click().catch(() => undefined);
    await page.waitForTimeout(800);
  }
}

const probeForInput = (c: Control): string => {
  if (c.name === 'pt-ticker') return 'BTCUSDT';
  const t = `${c.name} ${c.sampleText || ''}`;
  if (/%|amount|size|price|qty|leverage/i.test(t)) return '1';
  return 'e2e';
};

/**
 * Action one control with probe-and-restore semantics:
 *  - button/tab/period: one click (sort: click then cycle back to off);
 *  - select: switch to a different option, settle, restore the original;
 *  - input: type a probe, settle (debounce + fetch), restore the original value;
 *  - checkbox: toggle and toggle back;
 *  - links + date inputs + synthetic declared groups: skipped (recorded).
 * The caller runs a collector checkpoint after each action.
 */
export async function actOnControl(page: Page, c: Control): Promise<SweepOutcome> {
  if (c.kind === 'link') return { id: c.id, action: 'skipped-kind', detail: 'links not actioned in sweep' };
  if (c.kind === 'cell' || /drawer-controls/.test(c.id)) {
    return { id: c.id, action: 'skipped-declared-synthetic' };
  }
  if (c.tabPath) await ensureTab(page, c.tabPath);
  if (!(await findControlRetry(page, c, 3, 400, 'pre'))) return { id: c.id, action: 'absent' };
  try {
    const meta = await withRefind(page, c, (el) =>
      el.evaluate((n) => ({
        disabled: !!(n as HTMLButtonElement).disabled || n.getAttribute('aria-disabled') === 'true',
        type: (n as HTMLInputElement).type || '',
        readOnly: !!(n as HTMLInputElement).readOnly,
        value: (n as HTMLInputElement).value ?? '',
      })),
    );
    if (meta.disabled) return { id: c.id, action: 'disabled' };

    if (c.kind === 'sort') {
      await withRefind(page, c, (el) => el.click());
      await page.waitForTimeout(300);
      await withRefind(page, c, (el) => el.click());
      await withRefind(page, c, (el) => el.click()); // asc → desc → off: leave unsorted
      return { id: c.id, action: 'acted' };
    }
    if (c.kind === 'button' || c.kind === 'tab' || c.kind === 'period') {
      await withRefind(page, c, (el) => el.click());
      await page.waitForTimeout(c.kind === 'button' ? 400 : 600);
      return { id: c.id, action: 'acted' };
    }
    if (c.kind === 'select') {
      const restore = await withRefind(page, c, (el) =>
        el.evaluate((n) => {
          const s = n as HTMLSelectElement;
          const orig = s.value;
          const alt = [...s.options].find((o) => o.value !== orig && !o.disabled);
          return { orig, alt: alt ? alt.value : null };
        }),
      );
      if (restore.alt === null) return { id: c.id, action: 'acted', detail: 'single-option select' };
      await withRefind(page, c, (el) => el.selectOption(restore.alt!));
      await page.waitForTimeout(600);
      await withRefind(page, c, (el) => el.selectOption(restore.orig));
      await page.waitForTimeout(300);
      return { id: c.id, action: 'acted' };
    }
    if (c.kind === 'input') {
      if (meta.type === 'checkbox') {
        await withRefind(page, c, (el) => el.click());
        await page.waitForTimeout(300);
        await withRefind(page, c, (el) => el.click());
        return { id: c.id, action: 'acted' };
      }
      if (meta.type === 'date') return { id: c.id, action: 'skipped-date' };
      if (meta.readOnly) return { id: c.id, action: 'acted', detail: 'readOnly — focus only' };
      const probe = probeForInput(c);
      await withRefind(page, c, (el) => el.fill(probe));
      await page.waitForTimeout(700); // debounce (250ms) + fetch
      await withRefind(page, c, (el) => el.fill(meta.value));
      await page.waitForTimeout(300);
      return { id: c.id, action: 'acted' };
    }
    return { id: c.id, action: 'skipped-kind', detail: c.kind };
  } catch (e) {
    return { id: c.id, action: 'error', detail: String(e).slice(0, 200) };
  } finally {
    await dismissModals(page);
  }
}

/**
 * The quasi ticker's restore protocol: probing it flipped the SERVER's calculator
 * symbol (GET /api/price side effect) — clicking Clear posts /calculator/clear
 * (the one POST the mode-R guard allows) and returns the engine to the
 * no-active-symbol state. Recorded in the sweep report either way.
 */
export async function restoreCalcSymbol(page: Page, collector: Collector): Promise<boolean> {
  const clear = page.locator('button', { hasText: /^Clear$/i }).first();
  if (!(await clear.isVisible().catch(() => false))) return false;
  collector.setControl('restore/calculator-clear');
  await clear.click().catch(() => undefined);
  await page.waitForTimeout(600);
  return true;
}
