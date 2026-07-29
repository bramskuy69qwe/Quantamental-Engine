import type { Page } from '@playwright/test';

/**
 * Operator-in-the-loop pause. Injects a fixed banner carrying the instruction
 * plus DONE / SKIP controls, then waits for the operator.
 *
 * Chosen over the alternatives (evaluated in the plan): a Node `readline` prompt
 * cannot work — Playwright tests run in worker child processes with no TTY —
 * and `page.pause()` is the Inspector affordance (global timeout kill, separate
 * window, no per-step instruction text). An on-page overlay works in workers,
 * survives navigation via re-injection, keeps the instruction in view beside the
 * app, and is excluded from the collector's MutationObserver by id.
 */
const OVERLAY_ID = 'qe-e2e-overlay';

export interface StepResult {
  action: 'done' | 'skip';
  note: string;
  waitedMs: number;
}

export async function operatorStep(
  page: Page,
  opts: { title: string; body: string; scenario: string; step: number; total: number },
): Promise<StepResult> {
  const t0 = Date.now();
  await page.evaluate(
    ({ id, o }) => {
      const w = window as unknown as { __qeStep?: { action: string; note: string } };
      w.__qeStep = undefined;
      document.getElementById(id)?.remove();
      const el = document.createElement('div');
      el.id = id;
      el.style.cssText = [
        'position:fixed', 'left:0', 'right:0', 'bottom:0', 'z-index:2147483647',
        'background:#0b0f14', 'border-top:2px solid #22d3ee', 'padding:14px 18px',
        'font-family:ui-monospace,Consolas,monospace', 'color:#e5e7eb',
        'box-shadow:0 -8px 32px rgba(0,0,0,.6)',
      ].join(';');
      el.innerHTML = `
        <div style="display:flex;align-items:flex-start;gap:16px">
          <div style="flex:1">
            <div style="color:#22d3ee;font-size:11px;letter-spacing:.08em">
              E2E ${o.scenario} — STEP ${o.step}/${o.total}
            </div>
            <div style="font-size:15px;font-weight:700;margin:4px 0 6px">${o.title}</div>
            <div style="font-size:13px;line-height:1.5;white-space:pre-wrap;color:#cbd5e1">${o.body}</div>
            <input id="${id}-note" placeholder="optional note (what you actually did / observed)"
              style="margin-top:8px;width:60%;background:#111827;border:1px solid #334155;color:#e5e7eb;
                     padding:6px 8px;font-family:inherit;font-size:12px"/>
          </div>
          <div style="display:flex;flex-direction:column;gap:8px;min-width:150px">
            <button id="${id}-done" style="background:#059669;color:#fff;border:0;padding:12px 18px;
              font-size:14px;font-weight:700;cursor:pointer">DONE ✓ (F9)</button>
            <button id="${id}-skip" style="background:#334155;color:#e5e7eb;border:0;padding:8px 18px;
              font-size:12px;cursor:pointer">SKIP (F10)</button>
          </div>
        </div>`;
      document.body.appendChild(el);
      const note = () => (document.getElementById(`${id}-note`) as HTMLInputElement)?.value || '';
      const finish = (action: string) => { w.__qeStep = { action, note: note() }; };
      document.getElementById(`${id}-done`)!.addEventListener('click', () => finish('done'));
      document.getElementById(`${id}-skip`)!.addEventListener('click', () => finish('skip'));
      const onKey = (e: KeyboardEvent) => {
        if (e.key === 'F9') finish('done');
        if (e.key === 'F10') finish('skip');
      };
      document.addEventListener('keydown', onKey);
    },
    { id: OVERLAY_ID, o: opts },
  );

  const res = await page.waitForFunction(
    () => (window as unknown as { __qeStep?: unknown }).__qeStep,
    undefined,
    { timeout: 0, polling: 300 },
  );
  const val = (await res.jsonValue()) as { action: 'done' | 'skip'; note: string };
  await page.evaluate((id) => document.getElementById(id)?.remove(), OVERLAY_ID);
  return { ...val, waitedMs: Date.now() - t0 };
}

/** Progress toast for automated (non-pausing) steps — no interaction needed. */
export async function operatorNotice(page: Page, text: string, ms = 2500): Promise<void> {
  await page.evaluate(
    ({ id, text, ms }) => {
      const el = document.createElement('div');
      el.id = id + '-notice';
      el.style.cssText = [
        'position:fixed', 'left:50%', 'transform:translateX(-50%)', 'bottom:24px',
        'z-index:2147483646', 'background:#0b0f14', 'border:1px solid #22d3ee',
        'color:#e5e7eb', 'padding:10px 16px', 'font-family:ui-monospace,monospace',
        'font-size:12px',
      ].join(';');
      el.textContent = text;
      document.body.appendChild(el);
      setTimeout(() => el.remove(), ms);
    },
    { id: OVERLAY_ID, text, ms },
  );
}
