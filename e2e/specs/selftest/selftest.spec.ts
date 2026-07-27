/**
 * Engine-independent harness self-tests (project `selftest`, no baseURL).
 * Prove the tripwire, the oracles, the dedupe, and the dialog policy actually
 * detect what they claim to detect — BEFORE any run is trusted on a live engine.
 */
import { test, expect } from '../../lib/collector';
import { installGuard } from '../../lib/guard';
import { findingSig, normalizeMessage } from '../../lib/findings';
import { scanOracles } from '../../lib/oracles';

test('guard: non-allowlisted POST is aborted and reported; allowlisted POST passes through', async ({
  page,
  context,
  collector,
}) => {
  // The aborted + refused fetches surface as requestfailed + console noise — expected
  // in a selftest that deliberately fetches a down engine; muted, asserted directly.
  collector.mute('requestfailed', 'console-error');
  const hits: string[] = [];
  await installGuard(context, 'R', 'http://127.0.0.1:8000', (cls, d) => hits.push(`${cls}: ${d}`));

  await page.goto('about:blank');
  const blocked = await page.evaluate(async () => {
    try {
      await fetch('http://127.0.0.1:8000/e2e-guard-selftest', { method: 'POST' });
      return 'sent';
    } catch (e) {
      return 'blocked: ' + String(e);
    }
  });
  expect(blocked).toContain('blocked');
  expect(hits).toContain('mode-r-violation: POST /e2e-guard-selftest');

  // Allowlisted POST /calculator/clear must NOT be reported as a violation (with the
  // engine down it fails at the network layer instead — that is the desired shape).
  await page.evaluate(async () => {
    try {
      await fetch('http://127.0.0.1:8000/calculator/clear', { method: 'POST' });
    } catch {
      /* connection refused is fine — it got PAST the guard */
    }
  });
  expect(hits.filter((h) => h.includes('/calculator/clear'))).toEqual([]);

  // External non-document requests are aborted AND reported.
  await page.evaluate(async () => {
    try {
      await fetch('https://e2e-selftest.invalid/x');
    } catch {
      /* expected */
    }
  });
  expect(hits.some((h) => h.startsWith('external-call: GET https://e2e-selftest.invalid/'))).toBe(true);
});

test('oracles: degraded foot + error boundary + toast buffer are detected', async ({
  page,
  collector,
}) => {
  collector.mute('foot-degraded', 'error-boundary');
  await page.setContent(`
    <div data-screen-label="99 Selftest" class="qe-scope">
      <div class="qe-pane">
        <div class="qe-pane-head">Test Pane</div>
        <div class="qe-pane-body"></div>
        <div>✗ no network — engine unreachable</div>
      </div>
      <div class="qe-pane">
        <div class="qe-pane-head">Healthy Pane</div>
        <div class="qe-pane-body"></div>
        <div>✓ connected [12ms]</div>
      </div>
      <div class="qe-pane">
        <div class="qe-pane-head">Crashed Pane</div>
        <div class="qe-pane-body">
          <div class="qe-empty err fill">
            <div class="qe-empty-glyph">⚠</div>
            <div class="qe-empty-msg">Crashed Pane failed to render</div>
          </div>
        </div>
        <div>✗ Crashed Pane render failed · reload to recover</div>
      </div>
    </div>
  `);
  const hits = await scanOracles(page);
  const kinds = hits.map((h) => `${h.kind}:${h.pane}`).sort();
  expect(kinds).toContain('foot-degraded:Test Pane');
  expect(kinds).toContain('foot-degraded:Crashed Pane');
  expect(kinds).toContain('error-boundary:Crashed Pane');
  // The healthy foot must NOT be flagged.
  expect(hits.filter((h) => h.pane === 'Healthy Pane')).toEqual([]);

  // Toast buffer: the MutationObserver init script captures transient .qe-toast nodes.
  await page.evaluate(() => {
    const t = document.createElement('div');
    t.className = 'qe-toast';
    t.textContent = 'selftest toast';
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 50);
  });
  await page.waitForTimeout(200);
  const drained = await scanOracles(page);
  expect(drained.some((h) => h.kind === 'toast' && /selftest toast/.test(h.text))).toBe(true);

  await page.setContent('<html><body></body></html>'); // leave the page clean for teardown scan
});

test('findings: volatile tokens normalize away so repeats dedupe to one signature', async () => {
  const a = normalizeMessage('calc 12345 failed at 2026-07-28T10:00:01 (id abc123def456) after 250ms');
  const b = normalizeMessage('calc 99999 failed at 2026-07-29T23:59:59 (id 0f0f0f0f0f0f) after 8ms');
  expect(a).toBe(b);
  expect(findingSig('p', 'c', 'pageerror', a)).toBe(findingSig('p', 'c', 'pageerror', b));
  expect(findingSig('p', 'c', 'pageerror', a)).not.toBe(findingSig('p2', 'c', 'pageerror', a));
});

test('dialogs: expected confirm follows policy; unexpected confirm is dismissed + reported', async ({
  page,
  collector,
}) => {
  collector.mute('unexpected-dialog');
  await page.setContent('<html><body></body></html>');

  collector.expectDialog(/e2e-expected/, 'accept');
  const accepted = await page.evaluate(() => confirm('e2e-expected: proceed?'));
  expect(accepted).toBe(true);

  const dismissed = await page.evaluate(() => confirm('e2e-UNexpected: proceed?'));
  expect(dismissed).toBe(false);
  await expect
    .poll(() => collector.all().some((f) => f.class === 'unexpected-dialog' && /UNexpected/.test(f.raw || '')))
    .toBe(true);
});
