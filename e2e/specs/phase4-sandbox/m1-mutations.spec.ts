/**
 * Phase 4 — sandbox mutation sweep (project sandbox-w, :8010, guard unrestricted).
 * Exercises exactly the mutating-excluded surface the live sweeps never touch.
 * The collector's 200-body alert-sniff stays armed throughout: these endpoints
 * answer HTTP 200 for every outcome, so failures surface as body-alert findings
 * unless a test EXPECTS the failure (explicit mute + assertion, never silent).
 *
 * Prereqs: e2e/scripts/sandbox-up.ps1 + seed-sandbox.py (marker account
 * 'Sandbox Second' is verified by the preflight before anything runs).
 *
 * Run:  $env:E2E_PHASE='4'; npm run e2e:sandbox
 */
import { test, expect } from '../../lib/collector';
import { gotoPage, screenRoot, navButton, pane } from '../../lib/selectors';

const SETTLE = 2_500;

test.describe('phase 4 — sandbox mutations', () => {
  test('connections: add → listed → remove', async ({ page, collector }) => {
    await gotoPage(page, 'Config');
    await expect(screenRoot(page, '08 Config')).toBeVisible({ timeout: 15_000 });
    await page.locator('.qe-tabs > button', { hasText: /connection/i }).first().click();
    await page.waitForTimeout(1_000);

    // Scope to the ADD row: existing provider cards each carry their own
    // "API Key" input, and .first() typed the probe into bwe_news — which the
    // news WS then used as its URL (log spam until cleaned). Anchor on the
    // add-row's own provider input instead.
    const addRow = page
      .locator('div')
      .filter({ has: page.getByPlaceholder(/provider id/i) })
      .last();
    await page.getByPlaceholder(/provider id/i).fill('e2etest');
    await page.getByPlaceholder(/^label$/i).fill('E2E Probe');
    await addRow.getByPlaceholder(/api key/i).last().fill('e2e-fake-key');
    collector.setControl('connections/add');
    await page.locator('button', { hasText: /^Add$/ }).first().click();
    await page.waitForTimeout(1_500);
    await expect(page.getByText('e2etest').first()).toBeVisible({ timeout: 10_000 });

    collector.setControl('connections/remove');
    collector.expectDialog(/remove|delete|e2etest/i, 'accept');
    // Connections render as cards, not table rows — remove within the e2etest card.
    // Provider cards render in list order; the new one is appended last.
    await page.locator('button', { hasText: /^Remove$/ }).last().click();
    await page.waitForTimeout(1_500);
    await expect(page.getByText('e2etest')).toHaveCount(0, { timeout: 10_000 });
  });

  test('account settings: no-op save round-trips with "saved"', async ({ page, collector }) => {
    await gotoPage(page, 'Config');
    await expect(screenRoot(page, '08 Config')).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(SETTLE);
    collector.setControl('account-settings/save');
    const savePane = pane(page, 'Account Settings');
    await savePane.locator('button', { hasText: /^Save$/ }).first().click();
    await expect(savePane.locator('text=/saved/i').first()).toBeVisible({ timeout: 10_000 });
  });

  test('risk preset: apply to the NON-active account', async ({ page, collector }) => {
    await gotoPage(page, 'Config');
    await expect(screenRoot(page, '08 Config')).toBeVisible({ timeout: 15_000 });
    await page.locator('.qe-tabs > button', { hasText: /preset/i }).first().click();
    await page.waitForTimeout(1_000);
    // "Apply to" picker → the NON-active account (the cross-account write path).
    // MUST be scoped to the pane: an unscoped select-filter matched the NAV
    // account switcher and fired a real account activation instead.
    const presetPane = page.locator('.qe-pane-body').filter({ hasText: /Apply to/i }).first();
    const target = presetPane.locator('select').first();
    await expect(target).toBeVisible({ timeout: 10_000 });
    await target.selectOption('2');
    collector.setControl('presets/apply');
    collector.expectDialog(/preset|apply|dd|posture/i, 'accept');
    const applyBtn = page.locator('button', { hasText: /^Apply Preset$/ }).first();
    await expect(applyBtn).toBeVisible({ timeout: 10_000 });
    await applyBtn.click();
    // The endpoint answers 200-for-everything: the collector's body sniff is the
    // real oracle (an alert-error would fail the test); assert the picker still
    // targets account 2 and no pane crashed.
    await page.waitForTimeout(3_000);
    await collector.checkpoint('post-preset-apply');
    // NB: no assertion on the picker's value afterwards — the pane refetches and
    // re-defaults the target to the ACTIVE account, which is legitimate.
  });

  test('models: create → visible in library → delete', async ({ page, collector }) => {
    await gotoPage(page, 'Models');
    await expect(screenRoot(page, '06 Models')).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(SETTLE);
    collector.setControl('models/create');
    await page.locator('button', { hasText: /new model/i }).first().click();
    await page.waitForTimeout(800);
    await page.getByPlaceholder('e.g. BTC Macro Trend').fill('e2e-model-x');
    await page.locator('button', { hasText: /^Create model$/ }).first().click();
    await page.waitForTimeout(2_000);
    await expect(page.locator('text=e2e-model-x').first()).toBeVisible({ timeout: 10_000 });

    collector.setControl('models/delete');
    await page.locator('button', { hasText: /^e2e-model-x/ }).first().click().catch(() => undefined);
    await page.waitForTimeout(1_500);
    await page.locator('button', { hasText: /^Delete$/ }).first().click();
    await page.waitForTimeout(500);
    await page.locator('button', { hasText: /^Confirm$/ }).first().click();
    await page.waitForTimeout(2_000);
    await expect(page.locator('button', { hasText: /^e2e-model-x/ })).toHaveCount(0);
  });

  test('manual link: ADA review order links to the seeded calc', async ({ page, collector }) => {
    await gotoPage(page, 'Linkage');
    await expect(screenRoot(page, '03 Linkage')).toBeVisible({ timeout: 15_000 });
    // Poll for the strip instead of sleeping: the inbox mounts on the 5 s lane
    // and a fixed wait resolved the locator against a not-yet-settled pane.
    const inboxPane = pane(page, 'MANUAL LINK');
    const adaStrip = inboxPane.locator('text=ADA').first();
    await expect(adaStrip).toBeVisible({ timeout: 20_000 });
    await adaStrip.click();
    await page.waitForTimeout(800);
    collector.setControl('linkage/manual-link');
    // E2E-P6-003: the confirm is now the ModelDialog primitive, not a native
    // window.confirm — click through the dialog's own action button.
    await page.locator('button', { hasText: /^Link$/ }).first().click();
    await page.locator('button', { hasText: /^Link calc$/ }).first().click();
    await page.waitForTimeout(2_500);
    await expect(inboxPane.locator('text=/\\bLINK\\b.*ADA|ADA.*\\[REVIEW\\]/').first()).not.toBeVisible({
      timeout: 10_000,
    });
    await collector.checkpoint('post-manual-link');
  });

  test('mark unplanned: XLM review order', async ({ page, collector }) => {
    await gotoPage(page, 'Linkage');
    await expect(screenRoot(page, '03 Linkage')).toBeVisible({ timeout: 15_000 });
    const inboxPane = pane(page, 'MANUAL LINK');
    const xlmStrip = inboxPane.locator('text=XLM').first();
    await expect(xlmStrip).toBeVisible({ timeout: 20_000 });
    await xlmStrip.click();
    await page.waitForTimeout(800);
    collector.setControl('linkage/mark-unplanned');
    // E2E-P6-003: ModelDialog confirm (was a native window.confirm).
    await page.locator('button', { hasText: /^UNPLANNED$/ }).first().click();
    await page.locator('button', { hasText: /^Mark UNPLANNED$/ }).first().click();
    await page.waitForTimeout(2_500);
    await expect(inboxPane.locator('text=XLM')).toHaveCount(0, { timeout: 10_000 });
  });

  test('close reason: XRP MANUAL close refined to Intervention', async ({ page, collector }) => {
    await gotoPage(page, 'History');
    await expect(screenRoot(page, '04 History')).toBeVisible({ timeout: 15_000 });
    // History strips the USDT suffix — the cell renders 'XRP', never 'XRPUSDT'.
    const row = page.locator('tr', { hasText: 'XRP' }).first();
    await expect(row).toBeVisible({ timeout: 20_000 });
    collector.setControl('history/close-reason');
    // The handler sits on a titled SPAN wrapping the badge (pages-history.jsx:250)
    // — not the cell, and not the badge. The title IS the stable hook.
    const reasonSpan = row.getByTitle('Set / edit the close reason');
    await expect(reasonSpan).toBeVisible({ timeout: 15_000 });
    await reasonSpan.click();
    await page.waitForTimeout(800);
    // The reason buttons carry a title + description sub-line ("Intervention
    // Judgement call — exited against the plan deliberately"), so an exact
    // /^Intervention$/ can never match — textContent concatenates the two
    // children without whitespace, which also rules out a \b after the title.
    // Prefix-match the title. (This locator was wrong since inception: the
    // step was red in every phase-4 run, undispositioned at phase close.)
    await page.locator('button', { hasText: /^Intervention/ }).first().click();
    await page.locator('input[type="text"]').last().fill('e2e sandbox note').catch(() => undefined);
    await page.locator('button', { hasText: /^Save$/ }).first().click();
    await page.waitForTimeout(2_000);
    await expect(row.locator('.qe-badge', { hasText: /Intervention/i }).first()).toBeVisible({
      timeout: 10_000,
    });
  });

  test('regime: reclassify-all round-trips on the empty label set', async ({ page, collector }) => {
    await gotoPage(page, 'Regime');
    await expect(screenRoot(page, '07 Regime')).toBeVisible({ timeout: 15_000 });
    await page.locator('.qe-tabs > button', { hasText: /config/i }).first().click();
    await page.waitForTimeout(1_000);
    collector.setControl('regime/reclassify');
    collector.expectDialog(/reclassify/i, 'accept');
    await page.locator('button', { hasText: /reclassify/i }).first().click();
    await page.waitForTimeout(2_500);
    await collector.checkpoint('post-reclassify');
  });

  test('regime: keyless backfill PARTIALLY succeeds without crashing', async ({ page, collector }) => {
    // Investigated live: yfinance (VIX) and Binance-public sources need NO key,
    // so a keyless backfill is a PARTIAL success — FRED/Finnhub signals stay
    // 'NOT BACKFILLED'. The honest invariant: partial coverage renders, page
    // never crashes. (First spec version wrongly demanded a loud total failure.)
    test.setTimeout(240_000);
    await gotoPage(page, 'Regime');
    await expect(screenRoot(page, '07 Regime')).toBeVisible({ timeout: 15_000 });
    await page.locator('.qe-tabs > button', { hasText: /backfill/i }).first().click();
    await page.waitForTimeout(1_000);
    collector.setControl('regime/backfill');
    await page.locator('button', { hasText: /start backfill/i }).first().click();
    await page.waitForTimeout(20_000);
    await expect(page.getByText(/NOT BACKFILLED/i).first()).toBeVisible({ timeout: 30_000 });
    await collector.checkpoint('post-backfill-partial');
  });

  test('account activate: keyless switch FAILS GRACEFULLY and rolls back', async ({
    page,
    collector,
  }) => {
    // Investigated: activate's _reinit() calls fetch_exchange_info/account/
    // positions, which raise "No active account credentials available" on a
    // keyless sandbox account -> the route's documented rollback path returns
    // 500 and restores the previous account (routes_accounts.py:201-216).
    // A successful switch is therefore NOT provable without live credentials;
    // what IS provable here is the failure contract: surfaced, rolled back,
    // no crash. (The first spec version asserted success and mis-read the
    // 500 as a finding.)
    test.setTimeout(300_000);
    collector.mute('http-5xx', 'console-error'); // the 500 is the expected outcome
    await gotoPage(page, 'Dashboard');
    await expect(screenRoot(page, '01 Dashboard')).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(SETTLE);

    collector.setControl('accounts/activate-2-keyless');
    const picker = page.getByTitle('Switch active account (reloads)');
    await picker.selectOption('2');
    await page.waitForTimeout(15_000); // teardown + failed reinit + rollback reinit

    const state = await page.evaluate(async () => {
      const r = await fetch('/accounts');
      return (await r.json()) as { id: number; is_active: number }[];
    });
    const active = state.filter((a) => a.is_active);
    expect(active.map((a) => a.id), 'rollback must leave account 1 active').toEqual([1]);
    await collector.checkpoint('post-failed-switch');
    const boundaries = collector
      .all()
      .filter((f) => f.class === 'error-boundary');
    expect(boundaries, 'a failed switch must not crash a pane').toEqual([]);
  });
});
