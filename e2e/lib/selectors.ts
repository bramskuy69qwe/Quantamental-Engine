import type { Locator, Page } from '@playwright/test';

/**
 * The 9 pages (8 nav + gear-only Config). Labels are the `data-screen-label` roots —
 * the only reliable page anchors (NO data-testid exists anywhere in the app).
 * Hash routing accepts every name (app-shell.jsx QE_PAGES + hashchange listener).
 */
export const PAGES = [
  { label: '01 Dashboard', name: 'Dashboard' },
  { label: '02 Pre-Trade', name: 'Pre-Trade' },
  { label: '03 Linkage', name: 'Linkage' },
  { label: '04 History', name: 'History' },
  { label: '05 Analytics', name: 'Analytics' },
  { label: '06 Models', name: 'Models' },
  { label: '07 Regime', name: 'Regime' },
  { label: '00 Primitives', name: 'Primitives' },
  { label: '08 Config', name: 'Config' },
] as const;

export type PageName = (typeof PAGES)[number]['name'];

export const screenRoot = (page: Page, label: string): Locator =>
  page.locator(`[data-screen-label="${label}"]`);

/** Full-load navigation via hash — fresh mount, deterministic state. */
export async function gotoPage(page: Page, name: PageName): Promise<void> {
  await page.goto(`/v3#${encodeURIComponent(name)}`);
}

const reEscape = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * The real nav control for in-app routing. Config is the ⚙ gear
 * (title="Configuration"); Primitives' accessible name carries its DEV chip.
 */
export function navButton(page: Page, name: PageName): Locator {
  if (name === 'Config') return page.getByTitle('Configuration');
  return page.getByRole('button', { name: new RegExp(`^${reEscape(name)}( DEV)?$`) }).first();
}

/** Pane root via its head text (uppercased by CSS; DOM text is the literal prop). */
export const pane = (page: Page, title: string): Locator =>
  page.locator('.qe-pane-head', { hasText: title }).locator('..');

/** PaneFoot has NO className — it is the div sibling directly after the body. */
export const paneFoot = (paneRoot: Locator): Locator =>
  paneRoot.locator('.qe-pane-body + div').first();

/** Pre-Trade countdown chip states (exact rendered strings, pages-pretrade.jsx). */
export const CHIP = {
  none: 'no active calc',
  pending: '⌛ Confirming calc…',
  error: '✗ Submission failed to record',
  linked: '✓ LINKED',
  linkedConfirmed: '✓ LINKED (CONFIRMED)',
  expired: '✗ PLAN EXPIRED',
  linkable: '✓ LINKABLE',
  expiringSoon: '⚠ EXPIRING SOON',
} as const;
