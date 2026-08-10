/* ═══════════════════════════════════════════════════════════════════════════
 * THE PRODUCT MARK — single source of truth (2026-08-11).
 *
 * ►► TO CHANGE THE LOGO: edit QE_BRAND below, run `npm run build`. ◄◄
 *
 * That is the whole procedure. Everything downstream is GENERATED from this
 * one literal by frontend/build.mjs `emitBrandAssets()`:
 *   · static/brand/logo.svg      — favicon (v3.html + base.html) + boot overlay
 *   · static/icon-192.png        — PWA icon + /favicon.ico + apple-touch
 *   · static/icon-512.png        — PWA icon
 * and the in-app <BrandMark/> (TopNav) renders the same data from the bundle.
 * Nothing else in the repo may hard-code the mark's geometry or colors.
 *
 * ⚠ If the generated PNGs' CONTENT changes (any edit here), bump CACHE_NAME in
 * static/service-worker.js: the icons are precached CACHE-FIRST under stable
 * names, so without a bump every installed client keeps the old logo forever
 * (the C1 lesson — `activate` purges by NAME only).
 *
 * The mark: "10C FIELD" from the 2026-08-11 logo exploration (operator pick).
 * A 5×5 cell matrix; the M is lit, the complement cells ghost at 14% — the
 * letter powered on inside its grid — and the single accent cell sits on the
 * grid's vertical centerline: the meridian. The accent NEVER renders without
 * the M (it is the identity's signature), and cyan stays the only color —
 * the same scarcity rule DESIGN.md applies to accents in the UI (cyan is the
 * primary accent; color earns meaning by being rare).
 *
 * This file is PLAIN JS on purpose — no JSX. It executes in two worlds:
 * the browser bundle (window export, React available) and node inside
 * build.mjs (module.exports, React absent — BrandMark is defined but never
 * invoked there). Keep it parseable by both.
 * ═══════════════════════════════════════════════════════════════════════════ */

const QE_BRAND = {
  name: 'MERIDIAN',
  variant: '10C FIELD',
  viewBox: '0 0 100 100',
  cell: 10,                    // cell edge, viewBox units (grid pitch is 15)
  bg: '#000000',
  fg: '#ffffff',
  accent: '#00e7ff',           // == --qe-cyan
  ghostOpacity: 0.14,
  // the lit M (12 white cells; [x, y] of each 10-unit cell)
  cells: [
    [14, 14], [74, 14],
    [14, 29], [29, 29], [59, 29], [74, 29],
    [14, 44], [74, 44],
    [14, 59], [74, 59],
    [14, 74], [74, 74],
  ],
  // the meridian cell — on the vertical centerline, the only color
  accentCell: [44, 44],
  // the powered-off remainder of the 5×5 grid (12 ghost cells)
  ghostCells: [
    [29, 14], [44, 14], [59, 14],
    [44, 29],
    [29, 44], [59, 44],
    [29, 59], [44, 59], [59, 59],
    [29, 74], [44, 74], [59, 74],
  ],
};

/* <BrandMark size ghost title/> — the ONE in-app renderer of the mark.
   `ghost=false` drops the field (below ~20px the ghost cells are sub-pixel
   noise anyway — at favicon sizes FIELD degrades to the bare M by design). */
const BrandMark = function (props) {
  props = props || {};
  const size = props.size || 16;
  const ghost = props.ghost !== false;
  const b = QE_BRAND;
  const kids = [];
  if (ghost) {
    kids.push(React.createElement('g', { key: 'ghost', fill: b.fg, opacity: b.ghostOpacity },
      b.ghostCells.map(function (c, i) {
        return React.createElement('rect', { key: i, x: c[0], y: c[1], width: b.cell, height: b.cell });
      })));
  }
  kids.push(React.createElement('g', { key: 'm', fill: b.fg },
    b.cells.map(function (c, i) {
      return React.createElement('rect', { key: i, x: c[0], y: c[1], width: b.cell, height: b.cell });
    })));
  kids.push(React.createElement('rect', {
    key: 'meridian', x: b.accentCell[0], y: b.accentCell[1],
    width: b.cell, height: b.cell, fill: b.accent,
  }));
  return React.createElement('svg', {
    viewBox: b.viewBox, width: size, height: size,
    style: props.style, 'aria-label': b.name, role: 'img',
  }, kids);
};

if (typeof window !== 'undefined') {
  Object.assign(window, { QE_BRAND, BrandMark });
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { QE_BRAND };
}
