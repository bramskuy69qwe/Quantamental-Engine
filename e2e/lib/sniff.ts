/**
 * Endpoints that answer HTTP 200 for EVERY outcome — success vs failure is
 * discriminated only by an alert-error/alert-warning class in the HTML body
 * (the client sniffs the same way, e.g. pages-linkage.jsx `_lkForm`).
 * A harness asserting on status alone reads a failed link as success.
 */
export const SNIFF_PATHS: RegExp[] = [
  /\/orders\/\d+\/manual_link$/,
  /\/orders\/\d+\/mark_unplanned$/,
  /\/calculator\/cancel\/[^/]+$/,
  /\/calculator\/window$/,
  /\/calculator\/clear$/,
  /\/accounts\/[^/]+\/(update|test|activate)$/,
  /\/connections(\/[^/]+)?(\/test)?$/,
  /\/api\/config\/apply-preset$/,
  /\/api\/regime\/(reclassify|backfill)$/,
  /\/api\/news\/refresh$/,
  // (close_reason dropped 2026-07-30: since the fragments slim-down it
  // returns real status codes + JSON, no longer 200-with-alert-body.)
];

export const ALERT_RE = /alert-(error|warning)/;

export function shouldSniff(url: string, method: string): boolean {
  if (method.toUpperCase() === 'GET') return false;
  let pathname: string;
  try {
    pathname = new URL(url).pathname;
  } catch {
    return false;
  }
  return SNIFF_PATHS.some((re) => re.test(pathname));
}
