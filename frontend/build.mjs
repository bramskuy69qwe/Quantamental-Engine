/* v3.0 frontend build — BUILD-TIME ONLY (never runs at engine runtime).
 *
 * Two jobs:
 *   1. Vendor the runtime deps from node_modules → static/vendor/ (React prod
 *      UMD, ECharts 5.5.1, GridStack js+css, the two fonts as local woff2 +
 *      @font-face css). Drops every CDN dependency — offline/localhost doctrine.
 *   2. esbuild-transform each JSX module under src/ (classic React.createElement,
 *      NO bundling — the modules share via window globals, exactly as the
 *      reference loaded them as separate <script> tags) and CONCATENATE in the
 *      fixed load order into one content-hashed bundle static/v3/app.<hash>.js.
 *      tokens.css + shell.css are emitted with the same build hash so a rebuild
 *      changes their FILENAMES, not just a query string — the root-scoped,
 *      cache-first service worker (base.html registers it at scope '/', so it
 *      intercepts /static/* even though /v3 registers none of its own) can
 *      therefore never stale-serve the app bundle or its CSS. CAVEAT: the
 *      vendored /static/vendor/* deps keep STABLE filenames, so a same-name
 *      re-vendor could be served stale by that SW until CACHE_NAME bumps —
 *      scoping /v3 away from the root SW (or hashing the vendored files) is
 *      deferred coexistence work (plan §1.4/§1.5).
 *
 * The build OUTPUT (static/v3/, static/vendor/) is committed; node_modules is
 * gitignored. Run: `npm run build` (from frontend/).
 */
import { transform } from 'esbuild';
import vm from 'node:vm';
import { createHash } from 'node:crypto';
import { readFile, writeFile, copyFile, mkdir, rm, readdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { deflateSync } from 'node:zlib';

const HERE = dirname(fileURLToPath(import.meta.url));           // frontend/
const ROOT = dirname(HERE);                                     // repo root
const SRC = join(HERE, 'src');
const NM = join(HERE, 'node_modules');
const V3 = join(ROOT, 'static', 'v3');
const VENDOR = join(ROOT, 'static', 'vendor');
const FONTS = join(VENDOR, 'fonts');

/* ── JSX load order ───────────────────────────────────────────────────────
 * ORDER IS LOAD-BEARING (modules read each other's globals). This is the P0
 * shared-foundation subset; page phases (P1–P7) APPEND their modules here,
 * before app-shell.jsx which must stay LAST (it calls ReactDOM.createRoot).
 * Mirrors docs/design/meridian_v3/Meridian v3.0.html:106-125. */
const JSX_ORDER = [
  'brand.js',                 // product-mark single source of truth; FIRST — no deps, everyone may read it
  'primitives.jsx',
  'charts.jsx',
  'grid-workspace.jsx',
  'chrome-live.js',           // P8 — shared chrome store; MUST precede nav-and-data (its consumer)
  'nav-and-data.jsx',
  'notifications.jsx',
  'sse-adapter.js',           // SSE client-adapter skeleton (§1.2)
  'operator-seat.js',         // H6 — seat register/heartbeat store; AFTER chrome-live (consumes onAccountChange at eval)
  'dash-tiled.jsx',           // P1 — Dashboard page (wired to snapshot + SSE)
  'pages-config.jsx',         // P2 — Config page (accounts/connections/presets/system)
  'pages-pretrade.jsx',       // P3 — Pre-Trade page (calc JSON mirror + §1.3 freeze overlay)
  'link-primitives.jsx',      // P4 — linkage vocabulary (badges, diff, countdown)
  'pages-linkage.jsx',        // P4 — Linkage triage board (needs_review + mirrors)
  'pages-history.jsx',        // P4 — History page (JSON doors + drilldown)
  'pages-analytics.jsx',      // P5 — Analytics page (11 tabs; G-O4 exec/dist)
  'pages-regime.jsx',         // P6 — Regime page (4 sub-tabs; all-JSON surface)
  'pages-models-data.jsx',    // P7 — Models data layer (fetch + capture utils)
  'pages-models-lib.jsx',     // P7 — library vocabulary (cards, KPI tiles)
  'pages-models-report.jsx',  // P7 — run report tabs (render-as-is sections)
  'pages-models-overview.jsx',// P7 — Overview sub-tab (aggregates+leaderboard)
  'pages-models-detail.jsx',  // P7 — model detail + ModelView section shell
  'pages-models.jsx',         // P7 — dialogs + ModelsPage orchestrator
  'app-shell.jsx',            // MUST be last
];

/* Fonts vendored from @fontsource (latin, weights 400/500/600/700). */
const FONT_FACES = [
  { family: 'Space Grotesk', pkg: 'space-grotesk', weights: [400, 500, 600, 700] },
  { family: 'JetBrains Mono', pkg: 'jetbrains-mono', weights: [400, 500, 600, 700] },
];

async function freshDir(p) {
  if (existsSync(p)) await rm(p, { recursive: true, force: true });
  await mkdir(p, { recursive: true });
}

/* ── Brand assets — GENERATED from frontend/src/brand.js ──────────────────
 * One literal drives everything: the bundle's <BrandMark/> ships brand.js
 * verbatim, and this step derives static/brand/logo.svg + the two PWA PNGs
 * from the SAME data, so the mark cannot fork between renderers. To change
 * the logo: edit QE_BRAND in src/brand.js, run `npm run build` — and bump
 * CACHE_NAME in static/service-worker.js (the PNGs are precached CACHE-FIRST
 * under stable names; without a bump installed clients keep the old mark
 * forever — the C1 lesson).
 *
 * The PNG encoder is deliberately dependency-free: the mark is axis-aligned
 * rects on black, which needs no rasterizer — just RGBA rows, filter-0
 * scanlines and zlib (node builtin). Cell edges are rounded per-edge so a
 * non-integer scale (192/100) costs at most ±1px cell variance, invisible at
 * icon sizes and fully deterministic. */

function _crc32(buf) {
  let c, table = _crc32.T;
  if (!table) {
    table = _crc32.T = new Int32Array(256);
    for (let n = 0; n < 256; n++) {
      c = n;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      table[n] = c;
    }
  }
  c = 0xFFFFFFFF;
  for (let i = 0; i < buf.length; i++) c = table[(c ^ buf[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

function _pngChunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(_crc32(body));
  return Buffer.concat([len, body, crc]);
}

function _hexRgb(hex) {
  return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
}

function renderBrandPng(brand, size) {
  const px = Buffer.alloc(size * size * 4);
  const bg = _hexRgb(brand.bg);
  for (let i = 0; i < size * size; i++) {
    px[i * 4] = bg[0]; px[i * 4 + 1] = bg[1]; px[i * 4 + 2] = bg[2]; px[i * 4 + 3] = 255;
  }
  // Scale derives from brand.viewBox, NOT a hardcoded 100: the audit built a
  // surviving mutation out of exactly that fork (viewBox changed → SVG/nav
  // shrink to a quadrant while the PNGs silently stay full-size).
  const vb = brand.viewBox.split(/\s+/).map(Number);
  if (vb.length !== 4 || vb[2] !== vb[3]) {
    throw new Error(`brand.viewBox must be square, got '${brand.viewBox}'`);
  }
  const s = size / vb[2];
  const fill = (cx, cy, rgb) => {
    const x0 = Math.round(cx * s), x1 = Math.round((cx + brand.cell) * s);
    const y0 = Math.round(cy * s), y1 = Math.round((cy + brand.cell) * s);
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
      const o = (y * size + x) * 4;
      px[o] = rgb[0]; px[o + 1] = rgb[1]; px[o + 2] = rgb[2];
    }
  };
  const fg = _hexRgb(brand.fg), ac = _hexRgb(brand.accent);
  // ghost = fg composited over bg at ghostOpacity (straight alpha-over)
  const gh = fg.map((v, i) => Math.round(v * brand.ghostOpacity + bg[i] * (1 - brand.ghostOpacity)));
  for (const [x, y] of brand.ghostCells) fill(x, y, gh);
  for (const [x, y] of brand.cells) fill(x, y, fg);
  fill(brand.accentCell[0], brand.accentCell[1], ac);
  // filter-0 scanlines → IDAT
  const raw = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    px.copy(raw, y * (size * 4 + 1) + 1, y * size * 4, (y + 1) * size * 4);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0); ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;  // 8-bit RGBA
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]),
    _pngChunk('IHDR', ihdr),
    _pngChunk('IDAT', deflateSync(raw, { level: 9 })),
    _pngChunk('IEND', Buffer.alloc(0)),
  ]);
}

function renderBrandSvg(brand) {
  const rect = (c, extra) =>
    `  <rect x="${c[0]}" y="${c[1]}" width="${brand.cell}" height="${brand.cell}"${extra || ''}/>`;
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${brand.viewBox}" role="img" aria-label="${brand.name}">`,
    `<!-- GENERATED by frontend/build.mjs from frontend/src/brand.js (${brand.variant}). DO NOT EDIT. -->`,
    `<rect width="100" height="100" fill="${brand.bg}"/>`,
    `<g fill="${brand.fg}" opacity="${brand.ghostOpacity}">`,
    ...brand.ghostCells.map((c) => rect(c)),
    `</g>`,
    `<g fill="${brand.fg}">`,
    ...brand.cells.map((c) => rect(c)),
    `</g>`,
    rect(brand.accentCell, ` fill="${brand.accent}"`).trim(),
    `</svg>`,
    ``,
  ].join('\n');
}

async function emitBrandAssets() {
  // NOT require(): frontend/package.json is "type":"module", which makes
  // src/brand.js ESM under require(esm) — `module` is undefined inside it and
  // the CJS export lane never runs. A vm sandbox with a `module` stub executes
  // the file byte-for-byte as written (the same text the bundle ships), which
  // is exactly the single-source guarantee this step exists to provide.
  const code = await readFile(join(SRC, 'brand.js'), 'utf8');
  const sandbox = { module: { exports: {} } };
  vm.runInNewContext(code, sandbox, { filename: 'brand.js' });
  const { QE_BRAND } = sandbox.module.exports;
  if (!QE_BRAND) throw new Error('brand.js did not export QE_BRAND');
  const brandDir = join(ROOT, 'static', 'brand');
  await mkdir(brandDir, { recursive: true });
  await writeFile(join(brandDir, 'logo.svg'), renderBrandSvg(QE_BRAND), 'utf8');
  await writeFile(join(ROOT, 'static', 'icon-192.png'), renderBrandPng(QE_BRAND, 192));
  await writeFile(join(ROOT, 'static', 'icon-512.png'), renderBrandPng(QE_BRAND, 512));
  return QE_BRAND;
}

async function vendorDeps() {
  await freshDir(VENDOR);
  await mkdir(FONTS, { recursive: true });

  const copies = [
    [join(NM, 'react', 'umd', 'react.production.min.js'), join(VENDOR, 'react.production.min.js')],
    [join(NM, 'react-dom', 'umd', 'react-dom.production.min.js'), join(VENDOR, 'react-dom.production.min.js')],
    [join(NM, 'echarts', 'dist', 'echarts.min.js'), join(VENDOR, 'echarts.min.js')],
    [join(NM, 'gridstack', 'dist', 'gridstack-all.js'), join(VENDOR, 'gridstack-all.js')],
    [join(NM, 'gridstack', 'dist', 'gridstack.min.css'), join(VENDOR, 'gridstack.min.css')],
  ];
  for (const [from, to] of copies) {
    if (!existsSync(from)) throw new Error(`vendor source missing: ${from} (run npm install)`);
    await copyFile(from, to);
  }

  // Fonts: copy woff2 + synthesize a local @font-face sheet.
  const faceRules = [];
  for (const { family, pkg, weights } of FONT_FACES) {
    for (const w of weights) {
      const file = `${pkg}-latin-${w}-normal.woff2`;
      const from = join(NM, '@fontsource', pkg, 'files', file);
      if (!existsSync(from)) throw new Error(`font source missing: ${from}`);
      await copyFile(from, join(FONTS, file));
      faceRules.push(
        `@font-face{font-family:'${family}';font-style:normal;font-weight:${w};` +
        `font-display:swap;src:url('/static/vendor/fonts/${file}') format('woff2');}`
      );
    }
  }
  const fontsCss =
    `/* v3.0 vendored fonts — Space Grotesk + JetBrains Mono (latin, 400/500/600/700).\n` +
    `   Generated by frontend/build.mjs from @fontsource. Replaces the Google Fonts CDN link. */\n` +
    faceRules.join('\n') + '\n';
  await writeFile(join(VENDOR, 'fonts', 'fonts.css'), fontsCss, 'utf8');

  return copies.map(([, to]) => to).concat([join(FONTS, 'fonts.css')]);
}

async function buildBundle() {
  const parts = [
    `/* v3.0 app bundle — precompiled from frontend/src/ by build.mjs.\n` +
    `   DO NOT EDIT: regenerate with \`npm run build\`. Concatenated modules share\n` +
    `   window globals in load order (classic React.createElement). */\n`,
  ];
  for (const name of JSX_ORDER) {
    const path = join(SRC, name);
    if (!existsSync(path)) throw new Error(`JSX source missing: ${path}`);
    const code = await readFile(path, 'utf8');
    const out = await transform(code, {
      loader: 'jsx',
      jsx: 'transform',
      jsxFactory: 'React.createElement',
      jsxFragment: 'React.Fragment',
      target: 'es2019',
      sourcefile: name,
    });
    parts.push(`\n/* ==== ${name} ==== */\n`, out.code, '\n;\n');
  }
  return parts.join('');
}

async function main() {
  const t0 = Date.now();
  const vendored = await vendorDeps();
  const brand = await emitBrandAssets();

  const bundleJs = await buildBundle();

  // Fail-loud parse guardrail (plan §1.6 / L3·Finding 8): esbuild transforms
  // each module INDEPENDENTLY, so a cross-module collision (a duplicate
  // top-level const/let/class once page phases append modules) or any defect
  // spanning the concatenation join is invisible per-file and would only
  // blank-page in the browser. Compile the whole concatenated bundle here so it
  // becomes a BUILD failure instead.
  try {
    new vm.Script(bundleJs, { filename: 'app.bundle.js' });
  } catch (e) {
    throw new Error(`concatenated bundle failed to parse: ${e.message}`);
  }

  const tokensCss = await readFile(join(SRC, 'tokens.css'), 'utf8');
  const shellCss = await readFile(join(SRC, 'shell.css'), 'utf8');

  const hash = createHash('sha256')
    .update(bundleJs).update(tokensCss).update(shellCss)
    .digest('hex').slice(0, 10);

  await freshDir(V3);
  const appName = `app.${hash}.js`;
  const tokensName = `tokens.${hash}.css`;
  const shellName = `shell.${hash}.css`;
  await writeFile(join(V3, appName), bundleJs, 'utf8');
  await writeFile(join(V3, tokensName), tokensCss, 'utf8');
  await writeFile(join(V3, shellName), shellCss, 'utf8');

  const manifest = {
    hash,
    app: appName,
    tokens: tokensName,
    shell: shellName,
    modules: JSX_ORDER,
    note: 'Generated by frontend/build.mjs — do not edit by hand.',
  };
  await writeFile(join(V3, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n', 'utf8');

  const kb = (n) => (Buffer.byteLength(n, 'utf8') / 1024).toFixed(1) + ' KB';
  console.log('[v3 build] hash', hash, 'in', Date.now() - t0, 'ms');
  console.log('  static/v3/' + appName, kb(bundleJs));
  console.log('  static/v3/' + tokensName, kb(tokensCss));
  console.log('  static/v3/' + shellName, kb(shellCss));
  console.log('  vendored →', vendored.length, 'files under static/vendor/');
  console.log('  brand →', brand.variant, '· static/brand/logo.svg + icon-192/512.png');
}

main().catch((e) => {
  console.error('[v3 build] FAILED:', e.message);
  process.exit(1);
});
