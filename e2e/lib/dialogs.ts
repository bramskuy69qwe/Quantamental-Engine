import type { Dialog, Page } from '@playwright/test';

export interface DialogPolicy {
  pattern: RegExp;
  action: 'accept' | 'dismiss';
  once?: boolean;
}

export type DialogReporter = (detail: string) => void;

/**
 * Three app sites use native window.confirm (Linkage link/unplanned, Regime
 * reclassify, Config activate/preset/connection-remove). Tests declare expected
 * dialogs; anything unexpected is DISMISSED (never accepted — an unexpected
 * confirm on a live engine must not proceed) and reported as a finding.
 * Playwright's silent auto-dismiss would otherwise mask these entirely.
 */
export function installDialogPolicy(
  page: Page,
  policies: DialogPolicy[],
  reportUnexpected: DialogReporter,
): void {
  page.on('dialog', (dlg: Dialog) => {
    void (async () => {
      const idx = policies.findIndex((p) => p.pattern.test(dlg.message()));
      if (idx >= 0) {
        const pol = policies[idx];
        if (pol.once) policies.splice(idx, 1);
        if (pol.action === 'accept') await dlg.accept();
        else await dlg.dismiss();
        return;
      }
      reportUnexpected(`${dlg.type()}: ${dlg.message().slice(0, 200)}`);
      await dlg.dismiss();
    })().catch(() => { /* dialog already handled/page closing */ });
  });
}
