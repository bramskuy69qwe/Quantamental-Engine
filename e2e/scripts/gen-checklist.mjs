/**
 * Render scenarios/trade-scenarios.ts → scenarios/checklist.generated.md.
 * ONE source drives both the semi-automated spec and the manual checklist, so
 * the two can never drift (the operator chose BOTH modes).
 *
 *   node e2e/scripts/gen-checklist.mjs
 */
import { readFileSync, writeFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'scenarios', 'trade-scenarios.ts'), 'utf8');

// The scenario array is plain data; evaluate just that literal.
const start = src.indexOf('export const SCENARIOS');
const arrStart = src.indexOf('[', start);
const arrEnd = src.lastIndexOf('];', src.indexOf('export const GROUPS'));
const literal = src.slice(arrStart, arrEnd + 1);
const SCENARIOS = eval(literal); // eslint-disable-line no-eval

const budget = (ms) => (ms ? ` _(allow ${Math.round(ms / 1000)}s)_` : '');
const out = [];
out.push('# Phase-6 trade scenarios — operator checklist');
out.push('');
out.push('> GENERATED from `e2e/scenarios/trade-scenarios.ts` — do not edit by hand.');
out.push('> Regenerate: `node e2e/scripts/gen-checklist.mjs`');
out.push('>');
out.push('> Use this when running the scenarios BY HAND. The semi-automated runner');
out.push('> (`npm --prefix e2e run e2e:trade`) executes the same steps with an on-screen');
out.push('> prompt and asserts every oracle for you.');
out.push('');
out.push('**Standing rules** (make-or-break, from the verified lifecycle map):');
out.push('');
out.push('- Auto-link needs **both** a TP and an SL live on Binance — a naked entry never reaches the matcher, and never appears in the Linkage inbox.');
out.push('- A **TP ladder blocks auto-link** (ambiguity bail) — single TP for link scenarios.');
out.push('- `NEEDS_MANUAL_REVIEW` is **sticky**: always calc FIRST, order second.');
out.push('- Leave **>2s between identical orders** (duplicate-order detector).');
out.push('- Stay in **HEDGE** mode throughout (one-way breaks position-id attribution).');
out.push('- `—` in an excursion column means *not measured*, not zero.');
out.push('');

for (const s of SCENARIOS) {
  out.push(`## ${s.id} — ${s.title}`);
  out.push('');
  out.push(`**Group**: \`${s.group}\`  •  **Why**: ${s.why}`);
  out.push('');
  out.push('**Preconditions**');
  for (const p of s.preconditions) out.push(`- ${p}`);
  out.push('');
  out.push('| # | Who | Step | Expected |');
  out.push('|---|---|---|---|');
  s.steps.forEach((st, i) => {
    const who = st.kind === 'operator' ? '**YOU**' : st.kind === 'auto' ? 'script' : 'assert';
    const expected = st.kind === 'assert' ? `${st.manual}${budget(st.budgetMs)}` : '—';
    const text = st.kind === 'assert' ? `_check_ \`${st.oracle}\`` : st.manual.replace(/\n/g, '<br>');
    out.push(`| ${i + 1} | ${who} | ${text} | ${expected} |`);
  });
  out.push('');
  out.push('**Cleanup**');
  for (const c of s.cleanup) out.push(`- [ ] ${c}`);
  out.push('');
}

writeFileSync(join(here, '..', 'scenarios', 'checklist.generated.md'), out.join('\n') + '\n', 'utf8');
console.log(`[e2e] checklist written: ${SCENARIOS.length} scenarios`);
