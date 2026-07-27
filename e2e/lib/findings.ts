import * as crypto from 'crypto';

export type FindingClass =
  | 'pageerror'
  | 'console-error'
  | 'console-warn'
  | 'requestfailed'
  | 'http-4xx'
  | 'http-5xx'
  | 'body-alert'
  | 'mode-r-violation'
  | 'external-call'
  | 'error-boundary'
  | 'foot-degraded'
  | 'dl-empty-unexpected'
  | 'unexpected-dialog'
  | 'ordering-divergence'
  | 'storage-drift'
  | 'toast-observed'
  | 'harness-note';

export type Severity = 'CRIT' | 'HIGH' | 'MED' | 'LOW' | 'INFO';

/** Default severities — triage refines per finding; the gate reads these. */
export const SEVERITY: Record<FindingClass, Severity> = {
  'pageerror': 'CRIT',
  'mode-r-violation': 'CRIT',
  'error-boundary': 'CRIT',
  'http-5xx': 'CRIT',
  'body-alert': 'HIGH',
  'external-call': 'HIGH',
  'http-4xx': 'HIGH',
  'unexpected-dialog': 'HIGH',
  'console-error': 'MED',
  'requestfailed': 'MED',
  'foot-degraded': 'MED',
  'dl-empty-unexpected': 'MED',
  'ordering-divergence': 'MED',
  'storage-drift': 'LOW',
  'console-warn': 'LOW',
  'toast-observed': 'INFO',
  'harness-note': 'INFO',
};

/** Findings at or above this tier fail the emitting test (trace retained). */
export const GATE_TIERS: ReadonlySet<Severity> = new Set(['CRIT', 'HIGH', 'MED']);

export interface Finding {
  runId: string;
  ts: string;
  mode: string;
  phase: string;
  page: string;
  controlPath: string;
  class: FindingClass;
  severity: Severity;
  message: string;
  raw?: string;
  sig: string;
  test: string;
  count: number;
  artifacts?: { screenshot?: string };
}

/**
 * Strip volatile tokens (ids, hashes, timestamps, counts) so repeats of the same
 * defect collapse to one signature. Hex runs FIRST — otherwise the digit pass
 * shreds hex ids into unstable fragments.
 */
export function normalizeMessage(msg: string): string {
  return msg
    .replace(/[0-9a-f]{8,}/gi, '<hex>')
    .replace(/\d[\d.,:]*/g, '<n>')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 300);
}

export function findingSig(page: string, controlPath: string, cls: FindingClass, normMsg: string): string {
  return crypto
    .createHash('sha1')
    .update(`${page}|${controlPath}|${cls}|${normMsg}`)
    .digest('hex')
    .slice(0, 16);
}

/**
 * Known-benign console noise — curated, additions need a comment naming the source.
 * Kept deliberately tiny: an over-broad allowlist is how real findings vanish.
 */
export const CONSOLE_BENIGN: RegExp[] = [
  /Download the React DevTools/i,
  // The console echo of a guard abort — the violation itself is already reported by
  // the route layer (mode-r-violation / external-call); the echo is pure duplication.
  /net::ERR_BLOCKED_BY_CLIENT/,
];

/** Response URLs whose 404 is environmental noise, not an app defect. */
export const HTTP_BENIGN: RegExp[] = [
  /\/favicon\.ico$/,
];
