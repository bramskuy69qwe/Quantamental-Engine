import * as fs from 'fs';
import * as path from 'path';
import { test as base, expect, type Page, type TestInfo } from '@playwright/test';
import {
  CONSOLE_BENIGN,
  Finding,
  FindingClass,
  GATE_TIERS,
  HTTP_BENIGN,
  SEVERITY,
  findingSig,
  normalizeMessage,
} from './findings';
import { installGuard } from './guard';
import { ALERT_RE, shouldSniff } from './sniff';
import { OBSERVER_ENSURE_SRC, scanOracles } from './oracles';
import { unknownAppKeys } from './storage';
import { DialogPolicy, installDialogPolicy } from './dialogs';
import { LEDGER_DIR, Mode, RUN_ID, modeForProject, preflight } from './targets';

const pageFromUrl = (u: string): string => {
  try {
    const h = decodeURIComponent(new URL(u).hash.replace(/^#/, ''));
    return h || '(root)';
  } catch {
    return '(unknown)';
  }
};

/**
 * The bug harvest. Attached to every test as an auto-fixture: everything the page
 * does wrong lands here as a deduped finding; gate-tier findings fail the test at
 * teardown so the trace is retained.
 */
export class Collector {
  private readonly bySig = new Map<string, Finding>();
  private readonly muted = new Set<FindingClass>();
  private readonly shots: Promise<void>[] = [];
  readonly dialogPolicies: DialogPolicy[] = [];
  private controlPath = '(page)';

  constructor(
    private readonly page: Page,
    private readonly testInfo: TestInfo,
    readonly mode: Mode,
  ) {}

  /** Name the control the next findings should be attributed to. */
  setControl(pathLabel: string): void {
    this.controlPath = pathLabel;
  }

  /** Exclude classes from the GATE for this test (still recorded). Selftests + expected-error probes. */
  mute(...classes: FindingClass[]): void {
    for (const c of classes) this.muted.add(c);
  }

  expectDialog(pattern: RegExp, action: 'accept' | 'dismiss', once = true): void {
    this.dialogPolicies.push({ pattern, action, once });
  }

  note(cls: FindingClass, message: string, raw?: string): void {
    const pageLabel = pageFromUrl(this.page.url());
    const norm = normalizeMessage(message);
    const sig = findingSig(pageLabel, this.controlPath, cls, norm);
    const existing = this.bySig.get(sig);
    if (existing) {
      existing.count += 1;
      return;
    }
    const severity = SEVERITY[cls];
    const f: Finding = {
      runId: RUN_ID,
      ts: new Date().toISOString(),
      mode: this.mode,
      phase: process.env.E2E_PHASE || '?',
      page: pageLabel,
      controlPath: this.controlPath,
      class: cls,
      severity,
      message: norm,
      raw: raw ? raw.slice(0, 1000) : message.slice(0, 1000),
      sig,
      test: this.testInfo.titlePath.join(' › '),
      count: 1,
    };
    this.bySig.set(sig, f);
    if (severity === 'CRIT' || severity === 'HIGH') {
      const shot = path.join(LEDGER_DIR, 'screens', `${sig}.png`);
      f.artifacts = { screenshot: path.relative(LEDGER_DIR, shot) };
      this.shots.push(
        fs.promises
          .mkdir(path.dirname(shot), { recursive: true })
          .then(() => this.page.screenshot({ path: shot, fullPage: false }))
          .then(() => undefined)
          .catch(() => undefined),
      );
    }
  }

  /** Run the persistent-oracle scan (error boundaries, degraded feet, toast drain). */
  async checkpoint(where = ''): Promise<void> {
    let hits;
    try {
      hits = await scanOracles(this.page);
    } catch {
      return; // page navigating/closed — nothing to scan
    }
    for (const h of hits) {
      const cls: FindingClass = h.kind === 'toast' ? 'toast-observed' : h.kind;
      this.note(cls, `[${h.pane}]${where ? ` (${where})` : ''} ${h.text}`);
    }
  }

  all(): Finding[] {
    return [...this.bySig.values()];
  }

  gateFailures(): Finding[] {
    return this.all().filter((f) => GATE_TIERS.has(f.severity) && !this.muted.has(f.class));
  }

  async flush(): Promise<void> {
    await Promise.allSettled(this.shots);
    const rows = this.all();
    if (!rows.length) return;
    await fs.promises.mkdir(LEDGER_DIR, { recursive: true });
    const lines = rows.map((r) => JSON.stringify(r)).join('\n') + '\n';
    await fs.promises.appendFile(path.join(LEDGER_DIR, 'findings.jsonl'), lines, 'utf8');
    await this.testInfo.attach('e2e-findings', {
      body: JSON.stringify(rows, null, 2),
      contentType: 'application/json',
    });
  }
}

interface Fixtures {
  collector: Collector;
}

interface WorkerFixtures {
  workerPreflight: void;
}

export const test = base.extend<Fixtures, WorkerFixtures>({
  // Reachability + live-confirm gate, once per worker. The harness never starts an engine.
  workerPreflight: [
    async ({}, use, workerInfo) => {
      const mode = modeForProject(workerInfo.project.name);
      const baseURL = (workerInfo.project.use as { baseURL?: string }).baseURL;
      if (mode !== 'selftest' && baseURL) await preflight(baseURL, mode);
      await use();
    },
    { scope: 'worker', auto: true },
  ],

  collector: [
    async ({ page, context }, use, testInfo) => {
      const mode = modeForProject(testInfo.project.name);
      const c = new Collector(page, testInfo, mode);

      page.on('pageerror', (err) => c.note('pageerror', String(err?.message || err), err?.stack));
      page.on('console', (msg) => {
        const t = msg.type();
        if (t !== 'error' && t !== 'warning') return;
        const text = msg.text();
        if (CONSOLE_BENIGN.some((re) => re.test(text))) return;
        c.note(t === 'error' ? 'console-error' : 'console-warn', text);
      });
      page.on('requestfailed', (req) => {
        const err = req.failure()?.errorText || '';
        // Guard aborts are already reported as violations; ERR_ABORTED is routine
        // in-flight-poll cancellation on navigation, not a defect.
        if (err.includes('ERR_BLOCKED_BY_CLIENT') || err.includes('ERR_ABORTED')) return;
        c.note('requestfailed', `${req.method()} ${req.url()} — ${err}`);
      });
      page.on('response', (res) => {
        void (async () => {
          const status = res.status();
          const url = res.url();
          const method = res.request().method();
          if (status >= 500) {
            c.note('http-5xx', `${status} ${method} ${url}`);
            return;
          }
          if (status >= 400) {
            if (!HTTP_BENIGN.some((re) => re.test(url))) {
              c.note('http-4xx', `${status} ${method} ${url}`);
            }
            return;
          }
          if (status === 200 && shouldSniff(url, method)) {
            try {
              const body = await res.text();
              const m = body.match(ALERT_RE);
              if (m) {
                c.note(
                  'body-alert',
                  `200-with-${m[0]} ${method} ${url}`,
                  body.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 400),
                );
              }
            } catch {
              /* body unavailable (navigation) */
            }
          }
        })();
      });
      installDialogPolicy(page, c.dialogPolicies, (d) => c.note('unexpected-dialog', d));
      await context.addInitScript(OBSERVER_ENSURE_SRC);

      const baseURL = (testInfo.project.use as { baseURL?: string }).baseURL;
      if (mode !== 'selftest' && baseURL) {
        await installGuard(context, mode, new URL(baseURL).origin, (cls, d) => c.note(cls, d));
      }

      await use(c);

      await c.checkpoint('teardown');
      try {
        const drift = await unknownAppKeys(page);
        if (drift.length) c.note('storage-drift', `unknown qe.* keys: ${drift.join(', ')}`);
      } catch {
        /* page closed */
      }
      await c.flush();
      const gate = c.gateFailures();
      expect
        .soft(
          gate.map((f) => `${f.severity} ${f.class} @ ${f.page}/${f.controlPath}: ${f.message}`),
          'collector gate — see e2e-findings attachment + ledger JSONL',
        )
        .toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
