import { expect, type Page } from '@playwright/test';
import { pane } from './selectors';

/**
 * Phase-6 assertion oracles. Each returns a short evidence string on success and
 * throws on timeout. Row selection is ALWAYS by symbol AND side where hedge mode
 * makes symbol alone ambiguous.
 */
const ENGINE = 'http://127.0.0.1:8000';

export interface OracleCtx {
  ticker: string;
  side?: 'LONG' | 'SHORT';
  calcId?: string;
  reason?: string;
}

const sym = (t: string): string => t.replace('USDT', '');

export async function runOracle(
  page: Page,
  oracle: string,
  ctx: OracleCtx,
  budgetMs: number,
): Promise<string> {
  switch (oracle) {
    case 'chip-linkable': {
      const chip = page.locator('text=✓ LINKABLE').first();
      await expect(chip).toBeVisible({ timeout: budgetMs });
      return 'chip: ✓ LINKABLE';
    }
    case 'chip-linked': {
      const chip = page.locator('text=/✓ LINKED/').first();
      await expect(chip).toBeVisible({ timeout: budgetMs });
      return 'chip: ✓ LINKED';
    }
    case 'ws-sourced-fill': {
      // The P5-001 proof: the fill must arrive via the user-data WS, not REST.
      let last = '(none)';
      await expect
        .poll(
          async () => {
            const r = await page.request.get(`${ENGINE}/fragments/history/fills?format=json`);
            if (!r.ok()) return false;
            const j = (await r.json()) as { rows?: { symbol?: string; source?: string; timestamp_ms?: number }[] };
            const recent = (j.rows || []).filter(
              (x) => (x.symbol || '').includes(sym(ctx.ticker)) &&
                Date.now() - Number(x.timestamp_ms || 0) < 15 * 60_000,
            );
            last = recent.map((x) => `${x.symbol}:${x.source}`).join(', ') || '(no recent fills)';
            return recent.some((x) => x.source === 'binance_ws');
          },
          { timeout: budgetMs, intervals: [2_000], message: `fill source never became binance_ws (saw: ${last})` },
        )
        .toBe(true);
      return `fill source=binance_ws (${last})`;
    }
    case 'calc-row-present':
    case 'calc-row-absent': {
      // CALC-SCOPED, not ticker-scoped. A ticker filter cannot tell OUR calc
      // from any other live calc on the same symbol: in run 6-20260729-1120 a
      // second SOLUSDT calc appeared 27 s later, so the ticker-scoped oracle
      // reported "row still present" while our calc had correctly gone to
      // `matched` — a FALSE finding the operator was asked to rule on.
      // The active-calcs door carries calc_id, so assert on identity.
      if (!ctx.calcId) throw new Error('calc oracle needs ctx.calcId');
      let ids: string[] = [];
      const present = async (): Promise<boolean> => {
        const r = await page.request.get(`${ENGINE}/api/linkage/calcs`);
        if (!r.ok()) return false;
        const j = (await r.json()) as { calcs?: { calc_id?: string }[] };
        ids = (j.calcs || []).map((x) => String(x.calc_id || ''));
        return ids.includes(ctx.calcId!);
      };
      const want = oracle === 'calc-row-present';
      await expect
        .poll(present, {
          timeout: budgetMs,
          intervals: [2_000],
          message: `calc ${ctx.calcId} ${want ? 'never appeared in' : 'never left'} Active Calcs`,
        })
        .toBe(want);
      return want
        ? `Active Calcs contains ${ctx.calcId!.slice(0, 8)}…`
        : `Active Calcs no longer lists ${ctx.calcId!.slice(0, 8)}… (others live: ${ids.length})`;
    }
    case 'position-linked-onplan': {
      const row = positionRow(page, ctx);
      await expect(row.locator('text=LINKED').first()).toBeVisible({ timeout: budgetMs });
      const dev = await row.locator('.qe-badge').allTextContents();
      return `position: LINKED · badges ${JSON.stringify(dev)}`;
    }
    case 'position-unplanned': {
      const row = positionRow(page, ctx);
      await expect(row.first()).toBeVisible({ timeout: budgetMs });
      const badges = await row.locator('.qe-badge').allTextContents();
      expect(badges.join(' ')).toMatch(/UNPLANNED|OFF-PLAN/i);
      return `position: ${JSON.stringify(badges)}`;
    }
    case 'inbox-review-row': {
      const inbox = pane(page, 'MANUAL LINK');
      const strip = inbox.locator(`text=${sym(ctx.ticker)}`).first();
      await expect(strip).toBeVisible({ timeout: budgetMs });
      await strip.click();
      await page.waitForTimeout(800);
      return 'inbox: [REVIEW] strip present + selected';
    }
    case 'inbox-empty-of': {
      const inbox = pane(page, 'MANUAL LINK');
      await expect(inbox.locator(`text=${sym(ctx.ticker)}`)).toHaveCount(0, { timeout: budgetMs });
      return 'inbox: cleared for this symbol';
    }
    case 'plan-badge-amended':
    case 'plan-badge-offplan': {
      const want = oracle === 'plan-badge-amended' ? /AMENDED/i : /OFF-PLAN/i;
      let seen = '';
      await expect
        .poll(
          async () => {
            const row = positionRow(page, ctx);
            const n = await row.count();
            if (!n) {
              // closed already → check History's PLAN column instead
              const hr = page.locator('tr').filter({ hasText: sym(ctx.ticker) }).first();
              seen = (await hr.locator('.qe-badge').allTextContents().catch(() => [])).join(' ');
            } else {
              seen = (await row.locator('.qe-badge').allTextContents()).join(' ');
            }
            return want.test(seen);
          },
          { timeout: budgetMs, intervals: [3_000], message: `plan badge never matched ${want} (saw: ${seen})` },
        )
        .toBe(true);
      return `plan badge: ${seen}`;
    }
    case 'closed-row-present': {
      let n = 0;
      await expect
        .poll(
          async () => {
            const r = await page.request.get(`${ENGINE}/fragments/history/closed_positions?format=json`);
            if (!r.ok()) return 0;
            const j = (await r.json()) as { rows?: { symbol?: string; exit_time_ms?: number }[] };
            n = (j.rows || []).filter(
              (x) => (x.symbol || '').includes(sym(ctx.ticker)) &&
                Date.now() - Number(x.exit_time_ms || 0) < 30 * 60_000,
            ).length;
            return n;
          },
          { timeout: budgetMs, intervals: [3_000], message: 'no recent closed row appeared' },
        )
        .toBeGreaterThan(0);
      return `History: ${n} recent closed row(s)`;
    }
    case 'closed-row-reason': {
      let got = '';
      await expect
        .poll(
          async () => {
            const r = await page.request.get(`${ENGINE}/fragments/history/closed_positions?format=json`);
            if (!r.ok()) return false;
            const j = (await r.json()) as { rows?: { symbol?: string; exit_reason?: string; exit_time_ms?: number }[] };
            const row = (j.rows || []).find(
              (x) => (x.symbol || '').includes(sym(ctx.ticker)) &&
                Date.now() - Number(x.exit_time_ms || 0) < 30 * 60_000,
            );
            got = row?.exit_reason || '';
            return /MANUAL/i.test(got);
          },
          { timeout: budgetMs, intervals: [3_000], message: `exit_reason never matched (saw: ${got})` },
        )
        .toBe(true);
      return `exit_reason: ${got}`;
    }
    default:
      throw new Error(`unknown oracle ${oracle}`);
  }
}

/** Hedge-safe: match by symbol AND (when known) the side badge in the same row. */
function positionRow(page: Page, ctx: OracleCtx) {
  let row = page.locator('tr').filter({ hasText: sym(ctx.ticker) });
  if (ctx.side) {
    const badge = ctx.side === 'LONG' ? /^L$|LONG/ : /^S$|SHORT/;
    row = row.filter({ has: page.locator('.qe-badge', { hasText: badge }) });
  }
  return row.first();
}
