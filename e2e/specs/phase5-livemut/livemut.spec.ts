/**
 * Phase 5 — approved live mutations (project live-m, LIVE engine :8000).
 *
 * Exactly the operator-approved surface, nothing more (the guard aborts all
 * other non-GETs): calc create/cancel, /calculator/clear, match-window save,
 * news refresh. Every mutation records a cleanup assertion; the run's mutation
 * ledger is the JSONL in the run dir.
 *
 * Safety: the calc test picks a ticker with NO active calc and NO open position
 * on the live account (create SUPERSEDES the operator's active calc for the
 * same ticker+side; an in-window operator fill could auto-link to ours). The
 * whole calc lifecycle completes in <60 s and ends cancelled-terminal.
 *
 * Run:  $env:E2E_CONFIRM_LIVE='1'; $env:E2E_PHASE='5'; npm run e2e:livemut
 */
import * as fs from 'fs';
import * as path from 'path';
import { test, expect } from '../../lib/collector';
import { CHIP, gotoPage, pane, screenRoot } from '../../lib/selectors';
import { LEDGER_DIR } from '../../lib/targets';

const MUT_LEDGER = path.join(LEDGER_DIR, 'phase5-mutations.jsonl');
const mut = (row: object): void => {
  fs.mkdirSync(LEDGER_DIR, { recursive: true });
  fs.appendFileSync(MUT_LEDGER, JSON.stringify(row) + '\n', 'utf8');
};

test.describe('phase 5 — approved live mutations', () => {
  test('match window: save alternate → verify → restore original', async ({ page, collector }) => {
    await gotoPage(page, 'Pre-Trade');
    await expect(screenRoot(page, '02 Pre-Trade')).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(2_500);

    // The match-window select lives OUTSIDE any pane body (refresh strip);
    // the link-window-override select (also "min" options) lives inside one.
    const win = page
      .locator('[data-screen-label="02 Pre-Trade"] select')
      .filter({ has: page.locator('option', { hasText: /min/i }) })
      .filter({ hasNot: page.locator('xpath=ancestor::*[contains(@class,"qe-pane-body")]') })
      .first();
    await expect(win).toBeVisible({ timeout: 10_000 });
    const original = await win.inputValue();

    const options = await win.locator('option').evaluateAll((os) =>
      os.map((o) => (o as HTMLOptionElement).value),
    );
    const alternate = options.find((v) => v !== original)!;

    collector.setControl('livemut/match-window-save');
    await win.selectOption(alternate);
    await expect(page.locator('text=/✓|saved/i').first()).toBeVisible({ timeout: 10_000 });
    mut({ action: 'window-save', from: original, to: alternate });

    collector.setControl('livemut/match-window-restore');
    await win.selectOption(original);
    await expect(page.locator('text=/✓|saved/i').first()).toBeVisible({ timeout: 10_000 });
    await expect(win).toHaveValue(original);
    mut({ action: 'window-restore', to: original, cleanup: 'PASS' });
    await collector.checkpoint('window round-trip');
  });

  test('calc lifecycle: create → LINKABLE → Clear is NOT cancel → cancel via Linkage', async ({
    page,
    collector,
  }) => {
    test.setTimeout(300_000);

    // Pick a ticker the operator is NOT using: no active calc, no open position.
    const busy = await page.request
      .get('http://127.0.0.1:8000/api/linkage/calcs')
      .then(async (r) => JSON.stringify(await r.json()).toUpperCase())
      .catch(() => '');
    const pos = await page.request
      .get('http://127.0.0.1:8000/api/linkage/positions')
      .then(async (r) => JSON.stringify(await r.json()).toUpperCase())
      .catch(() => '');
    const ticker = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT'].find(
      (t) => !busy.includes(t) && !pos.includes(t),
    );
    expect(ticker, 'no safe ticker free of operator calcs/positions').toBeTruthy();
    console.log(`[e2e] phase5 calc ticker: ${ticker}`);

    await gotoPage(page, 'Pre-Trade');
    await expect(screenRoot(page, '02 Pre-Trade')).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(2_500);

    // MARKET + BY-% (side default): ticker, SL% required; TP% for a full plan.
    collector.setControl('livemut/calc-form');
    await page.locator('#pt-ticker').fill(ticker!);
    await page.waitForTimeout(2_500); // live price poll must land (market mode needs it)
    await page.locator('.qe-period > button', { hasText: /^BY %$|^BY-%$|%/ }).first().click();
    await page.waitForTimeout(400);
    await page.locator('#pt-tp').fill('2');
    await page.locator('#pt-sl').fill('1');

    collector.setControl('livemut/calc-create');
    await page.locator('button', { hasText: /^Calculate$/ }).first().click();
    const chip = page.locator(`text=${CHIP.linkable}`).first();
    await expect(chip).toBeVisible({ timeout: 15_000 }); // PENDING(≤5s) → LINKABLE
    const calcId = await page.evaluate(() => {
      try {
        return JSON.parse(sessionStorage.getItem('qe.v3.calc_result') || '{}').calc_id || '';
      } catch {
        return '';
      }
    });
    expect(calcId, 'calc_id must be recorded client-side').toBeTruthy();
    mut({ action: 'calc-create', ticker, calcId });

    // Clear ≠ cancel: locally resets, server-side the calc stays LINKABLE.
    collector.setControl('livemut/calc-clear');
    await page.locator('button', { hasText: /^Clear$/ }).first().click();
    await page.waitForTimeout(1_000);
    await expect(page.locator(`text=${CHIP.none}`).first()).toBeVisible({ timeout: 5_000 });
    const st = await page.request
      .get(`http://127.0.0.1:8000/calculator/link-window-status/${calcId}?format=json`)
      .then((r) => r.json());
    expect(
      ['LINKABLE', 'EXPIRING_SOON'],
      'Clear must NOT cancel — the calc stays linkable server-side (lifecycle-map pin)',
    ).toContain(st.status);
    mut({ action: 'calc-clear', calcId, serverStatus: st.status });

    // Cleanup: cancel via the Linkage Active Calcs ✕ → ModelDialog.
    await gotoPage(page, 'Linkage');
    await expect(screenRoot(page, '03 Linkage')).toBeVisible({ timeout: 15_000 });
    // Scope by ROW, not by pane subtree: Active Calcs' DataList is not always a
    // descendant of the head's parent (the pane() recipe missed it and the first
    // Phase-5 run left a live calc behind — cleanup must not depend on layout).
    const sym = ticker!.replace('USDT', '');
    const row = page
      .locator('tr')
      .filter({ hasText: sym })
      .filter({ has: page.getByTitle('Cancel this calc') })
      .first();
    await expect(row).toBeVisible({ timeout: 25_000 });

    collector.setControl('livemut/calc-cancel');
    await row.getByTitle('Cancel this calc').click();
    await page.waitForTimeout(800);
    await page.locator('input[type="text"]').last().fill('e2e phase5 cleanup').catch(() => undefined);
    await page.locator('button', { hasText: /^Cancel calc$/ }).first().click();
    await expect(page.locator('text=/Calc cancelled/i').first()).toBeVisible({ timeout: 10_000 });
    await expect(row).toHaveCount(0, { timeout: 15_000 });

    // E2E-P5-002 pin, end-to-end: a cancelled calc must NOT keep reporting
    // LINKABLE (it did — the chip advertised a plan the matcher can never take).
    const after = await page.request
      .get(`http://127.0.0.1:8000/calculator/link-window-status/${calcId}?format=json`)
      .then((r) => r.json());
    expect(
      after.status,
      'cancelled calc must report a TERMINAL status, never LINKABLE',
    ).toBe('EXPIRED');
    mut({ action: 'calc-cancel', calcId, cleanup: 'PASS', postCancelStatus: after.status });
    await collector.checkpoint('calc lifecycle complete');
  });

  test('news refresh: POST fires; outcome surfaces without breaking the pane', async ({
    page,
    collector,
  }) => {
    // Finnhub is currently degraded on this key (403 calendar / intermittent 502
    // news; monitoring shows "No news data" alerts) — success is NOT assertable.
    // The honest invariant: the POST fires, the outcome (fresh items OR an error)
    // surfaces, and the pane never crashes.
    collector.mute('body-alert', 'foot-degraded', 'console-error');
    await gotoPage(page, 'Regime');
    await expect(screenRoot(page, '07 Regime')).toBeVisible({ timeout: 15_000 });
    await page.locator('.qe-tabs > button', { hasText: /news/i }).first().click();
    await page.waitForTimeout(1_500);

    collector.setControl('livemut/news-refresh');
    const newsPane = pane(page, 'Market News');
    await newsPane.locator('button', { hasText: '↻' }).first().click();
    await page.waitForTimeout(8_000);
    await expect(newsPane.locator('.qe-pane-body').first()).toBeVisible();
    await collector.checkpoint('post news refresh');
    const crashed = collector.all().filter((f) => f.class === 'error-boundary');
    expect(crashed, 'news refresh must never crash the pane').toEqual([]);
    mut({ action: 'news-refresh', note: 'outcome not asserted (Finnhub degraded); no crash verified' });
  });
});
