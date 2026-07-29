/**
 * Phase 6 — operator-in-the-loop trade scenarios (project trade-t: LIVE engine,
 * HEADED, full trace). The operator places every real order; the script drives
 * the UI, pauses with an on-screen instruction, and asserts each lifecycle
 * transition inside the verified budgets.
 *
 * Select a group (default: all):
 *   $env:E2E_CONFIRM_LIVE='1'; $env:E2E_PHASE='6'; $env:E2E_TRADE_TICKER='ETHUSDT'
 *   npm run e2e:trade                       # every scenario
 *   npx playwright test --project=trade-t -g "H1"    # one scenario
 *
 * Nothing here places an order. Every operator step is explicit, skippable
 * (F10), and every scenario ends with an asserted cleanup prompt.
 */
import * as fs from 'fs';
import * as path from 'path';
import { test, expect } from '../../lib/collector';
import { SCENARIOS, type Scenario } from '../../scenarios/trade-scenarios';
import { CHIP, gotoPage, screenRoot } from '../../lib/selectors';
import { operatorNotice, operatorStep } from '../../lib/operator';
import { runOracle } from '../../lib/trade-oracles';
import { LEDGER_DIR } from '../../lib/targets';

const TICKER = process.env.E2E_TRADE_TICKER || 'ETHUSDT';
const JOURNAL = path.join(LEDGER_DIR, 'phase6-journal.jsonl');
const rec = (row: object): void => {
  fs.mkdirSync(LEDGER_DIR, { recursive: true });
  fs.appendFileSync(JOURNAL, JSON.stringify({ ts: new Date().toISOString(), ...row }) + '\n', 'utf8');
};

async function submitCalc(page: import('@playwright/test').Page, ticker: string): Promise<string> {
  await gotoPage(page, 'Pre-Trade');
  await expect(screenRoot(page, '02 Pre-Trade')).toBeVisible({ timeout: 15_000 });
  await page.locator('#pt-ticker').fill(ticker);
  // Wait for a live price — MARKET mode refuses to size without one, and the
  // boot-burst weight saturation can starve the price door for minutes (P5-R5).
  await expect
    .poll(
      async () => {
        const r = await page.request.get(`http://127.0.0.1:8000/api/price/${ticker}`);
        if (!r.ok()) return 0;
        return Number(((await r.json()) as { price?: number })?.price ?? 0);
      },
      { timeout: 120_000, intervals: [2_000], message: 'no live price (engine weight budget?)' },
    )
    .toBeGreaterThan(0);
  await page.locator('.qe-period > button', { hasText: /^BY %$|^BY-%$|%/ }).first().click();
  await page.waitForTimeout(400);
  await page.locator('#pt-tp').fill('2');
  await page.locator('#pt-sl').fill('1');
  await page.locator('button', { hasText: /^Calculate$/ }).first().click();
  await expect(page.locator(`text=${CHIP.linkable}`).first()).toBeVisible({ timeout: 20_000 });
  return page.evaluate(() => {
    try {
      return JSON.parse(sessionStorage.getItem('qe.v3.calc_result') || '{}').calc_id || '';
    } catch {
      return '';
    }
  });
}

for (const scenario of SCENARIOS) {
  test(`${scenario.id} — ${scenario.title}`, async ({ page, collector }) => {
    test.setTimeout(0); // operator-paced
    const ctx: { ticker: string; calcId?: string } = { ticker: TICKER };
    rec({ event: 'scenario-start', id: scenario.id, ticker: TICKER });

    await gotoPage(page, 'Dashboard');
    await expect(screenRoot(page, '01 Dashboard')).toBeVisible({ timeout: 20_000 });

    // Brief the operator: why this scenario exists + its make-or-break rules.
    const brief = await operatorStep(page, {
      scenario: scenario.id,
      step: 0,
      total: scenario.steps.length,
      title: scenario.title,
      body:
        `${scenario.why}\n\nPRECONDITIONS:\n` +
        scenario.preconditions.map((p) => `  • ${p}`).join('\n') +
        `\n\nTicker for this run: ${TICKER}. Press DONE to begin, SKIP to skip the scenario.`,
    });
    if (brief.action === 'skip') {
      rec({ event: 'scenario-skipped', id: scenario.id, note: brief.note });
      test.skip(true, 'operator skipped');
      return;
    }

    for (let i = 0; i < scenario.steps.length; i++) {
      const step = scenario.steps[i];
      const label = `${scenario.id}#${i + 1}`;
      collector.setControl(label);

      if (step.kind === 'auto') {
        await operatorNotice(page, `AUTO: ${step.manual}`);
        if (step.action === 'goto-linkage') {
          await gotoPage(page, 'Linkage');
          await expect(screenRoot(page, '03 Linkage')).toBeVisible({ timeout: 20_000 });
          // First paint after a fresh load costs more than one poll interval:
          // the page mounts, THEN the 5 s lane fetches, THEN rows render. Two
          // late-passes in a row (chip-linked, position-linked) traced to this —
          // the harness was manufacturing misses the operator had to adjudicate.
          // Wait for a table to actually carry rows before asserting on them.
          await page
            .locator('table.qe-table tbody tr')
            .first()
            .waitFor({ state: 'visible', timeout: 20_000 })
            .catch(() => undefined); // genuinely-empty panes are a valid state
          await page.waitForTimeout(2_000);
        } else if (step.action === 'goto-history') {
          await gotoPage(page, 'History');
          await expect(screenRoot(page, '04 History')).toBeVisible({ timeout: 20_000 });
        } else if (step.action === 'goto-pretrade') {
          await gotoPage(page, 'Pre-Trade');
          await expect(screenRoot(page, '02 Pre-Trade')).toBeVisible({ timeout: 20_000 });
        } else if (step.action === 'submit-calc') {
          ctx.calcId = await submitCalc(page, TICKER);
          rec({ event: 'calc-created', id: scenario.id, calcId: ctx.calcId });
        }
        rec({ event: 'auto-step', id: scenario.id, step: i + 1, action: step.action });
        continue;
      }

      if (step.kind === 'operator') {
        const res = await operatorStep(page, {
          scenario: scenario.id,
          step: i + 1,
          total: scenario.steps.length,
          title: 'YOUR MOVE — place / modify / close on Binance',
          body: step.manual,
        });
        rec({ event: 'operator-step', id: scenario.id, step: i + 1, ...res, text: step.manual });
        if (res.action === 'skip') {
          rec({ event: 'scenario-aborted', id: scenario.id, at: i + 1 });
          test.skip(true, `operator skipped at step ${i + 1}`);
          return;
        }
        continue;
      }

      // assert
      const budget = step.budgetMs ?? 20_000;
      try {
        const evidence = await runOracle(page, step.oracle!, { ...ctx, ...(step.params as object) }, budget);
        rec({ event: 'assert-pass', id: scenario.id, step: i + 1, oracle: step.oracle, evidence });
        await operatorNotice(page, `✓ ${step.oracle}: ${evidence}`, 3500);
      } catch (e) {
        rec({
          event: 'assert-FAIL',
          id: scenario.id,
          step: i + 1,
          oracle: step.oracle,
          budgetMs: budget,
          error: String(e).slice(0, 400),
        });
        // Let the operator judge: a miss may be a real defect OR an environment
        // artifact (rate limit, they placed something different). Their call is
        // recorded either way — never silently swallowed.
        const verdict = await operatorStep(page, {
          scenario: scenario.id,
          step: i + 1,
          total: scenario.steps.length,
          title: `ASSERTION MISSED after ${Math.round(budget / 1000)}s — ${step.oracle}`,
          body:
            `Expected: ${step.manual}\n\n` +
            `If the UI actually shows the expected state now, press DONE (recorded as a LATE pass).\n` +
            `If it genuinely does not, press SKIP (recorded as a CONFIRMED FINDING).\n\n` +
            String(e).slice(0, 300),
        });
        rec({
          event: verdict.action === 'done' ? 'assert-late-pass' : 'assert-confirmed-finding',
          id: scenario.id,
          step: i + 1,
          oracle: step.oracle,
          note: verdict.note,
        });
        if (verdict.action !== 'done') {
          expect(verdict.action, `${step.oracle} confirmed failing by operator: ${verdict.note}`).toBe('done');
        }
      }
    }

    const cleanup = await operatorStep(page, {
      scenario: scenario.id,
      step: scenario.steps.length,
      total: scenario.steps.length,
      title: 'CLEANUP — confirm before the scenario closes',
      body: scenario.cleanup.map((c) => `  • ${c}`).join('\n') + '\n\nPress DONE when all of the above is true.',
    });
    rec({ event: 'scenario-end', id: scenario.id, cleanup: cleanup.action, note: cleanup.note });
    await collector.checkpoint(`${scenario.id} complete`);
  });
}
