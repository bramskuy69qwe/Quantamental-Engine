import * as fs from 'fs';
import * as path from 'path';
import { E2E_ROOT, Mode } from './targets';

export type Risk = 'safe' | 'quasi' | 'mutating-live-allowed' | 'mutating-excluded' | 'unclassified';

export interface SelectorRecipe {
  strategy: 'id' | 'title' | 'text' | 'struct';
  value: string;
  scope?: string;
}

export interface Control {
  id: string;
  page: string;
  pane: string;
  paneRaw?: string;
  kind: string;
  name: string;
  title?: string;
  elemId?: string;
  disabled?: boolean;
  instances: number;
  selector: SelectorRecipe;
  tabPath?: string;
  sampleText?: string;
  source: 'crawled' | 'declared';
  // filled by classification:
  risk?: Risk;
  cluster?: string;
  confirm?: 'native' | 'in-dom';
  restore?: string;
  dataDependent?: boolean;
  note?: string;
}

export interface Rule {
  match: string;
  risk: Risk;
  cluster?: string;
  confirm?: 'native' | 'in-dom';
  restore?: string;
  dataDependent?: boolean;
  note?: string;
}

export const MANIFEST_DIR = path.join(E2E_ROOT, 'manifest');
export const CONTROLS_PATH = path.join(MANIFEST_DIR, 'controls.json');
export const PENDING_PATH = path.join(MANIFEST_DIR, 'controls.pending.json');
export const CLASSIFICATION_PATH = path.join(MANIFEST_DIR, 'classification.json');
export const DECLARED_PATH = path.join(MANIFEST_DIR, 'declared.json');

export const controlId = (c: Pick<Control, 'page' | 'pane' | 'kind' | 'name'>): string =>
  `${c.page}/${c.pane}/${c.kind}:${c.name}`;

export function loadRules(): Rule[] {
  const raw = JSON.parse(fs.readFileSync(CLASSIFICATION_PATH, 'utf8')) as { rules: Rule[] };
  return raw.rules;
}

export function loadDeclared(): Control[] {
  if (!fs.existsSync(DECLARED_PATH)) return [];
  const raw = JSON.parse(fs.readFileSync(DECLARED_PATH, 'utf8')) as { controls: Control[] };
  return raw.controls.map((c) => ({ ...c, source: 'declared' as const, id: c.id || controlId(c) }));
}

export function loadCommitted(): Control[] | null {
  if (!fs.existsSync(CONTROLS_PATH)) return null;
  return (JSON.parse(fs.readFileSync(CONTROLS_PATH, 'utf8')) as { controls: Control[] }).controls;
}

/**
 * First matching rule wins — order in classification.json is load-bearing.
 * DECLARED entries are hand-classified at declaration; rules never touch them
 * (a page-wide safe catch-all must not silently downgrade a declared mutation).
 */
export function classify(c: Control, rules: Rule[]): Control {
  if (c.source === 'declared' && c.risk) return c;
  for (const r of rules) {
    if (new RegExp(r.match).test(c.id)) {
      return {
        ...c,
        risk: r.risk,
        cluster: r.cluster ?? c.cluster,
        confirm: r.confirm ?? c.confirm,
        restore: r.restore ?? c.restore,
        dataDependent: r.dataDependent ?? c.dataDependent,
        note: r.note ?? c.note,
      };
    }
  }
  return { ...c, risk: 'unclassified' };
}

/**
 * Controls appearing (same pane|kind|name|title) on most pages are the shared chrome
 * (TopNav, WorkspaceBar, StatusFooter, banners render inside every page root) —
 * hoist them to a single `chrome/...` entry so 9 duplicates become one reviewable row.
 */
export function hoistChrome(controls: Control[], minPages = 7): Control[] {
  const byKey = new Map<string, Control[]>();
  for (const c of controls) {
    const key = `${c.pane}|${c.kind}|${c.name}|${c.title || ''}`;
    const arr = byKey.get(key) || [];
    arr.push(c);
    byKey.set(key, arr);
  }
  const out: Control[] = [];
  for (const group of byKey.values()) {
    const pages = new Set(group.map((g) => g.page));
    if (pages.size >= minPages) {
      const first = group[0];
      const hoisted: Control = {
        ...first,
        page: 'chrome',
        instances: Math.max(...group.map((g) => g.instances)),
      };
      hoisted.id = controlId(hoisted);
      out.push(hoisted);
    } else {
      out.push(...group);
    }
  }
  return out;
}

export interface ManifestDiff {
  added: string[];
  missing: string[];
  missingDataDependent: string[];
}

export function diffManifests(current: Control[], committed: Control[]): ManifestDiff {
  const cur = new Set(current.map((c) => c.id));
  const com = new Map(committed.map((c) => [c.id, c]));
  const added = [...cur].filter((id) => !com.has(id)).sort();
  const missing: string[] = [];
  const missingDataDependent: string[] = [];
  for (const [id, c] of com) {
    if (cur.has(id)) continue;
    if (c.dataDependent) missingDataDependent.push(id);
    else missing.push(id);
  }
  return { added, missing: missing.sort(), missingDataDependent: missingDataDependent.sort() };
}

export function writeManifest(file: string, controls: Control[]): void {
  const sorted = [...controls].sort((a, b) => a.id.localeCompare(b.id));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ generated: 'e2e:crawl', controls: sorted }, null, 2) + '\n', 'utf8');
}

/** Phase-2+ consumption: which controls may a given mode interact with. */
export function controlsFor(mode: Mode, controls: Control[]): Control[] {
  const allowed: Record<Mode, Risk[]> = {
    selftest: [],
    R: ['safe', 'quasi'],
    M: ['safe', 'quasi', 'mutating-live-allowed'],
    T: ['safe', 'quasi', 'mutating-live-allowed'],
    W: ['safe', 'quasi', 'mutating-live-allowed', 'mutating-excluded'],
  };
  const ok = new Set(allowed[mode]);
  return controls.filter((c) => ok.has((c.risk || 'unclassified') as Risk));
}
