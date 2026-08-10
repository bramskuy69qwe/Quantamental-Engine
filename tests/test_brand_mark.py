"""The unified product mark (2026-08-11): one source of truth, generated cuts.

`frontend/src/brand.js` holds the ONLY definition of the logo (the operator's
pick: "10C FIELD" — the pixel-matrix M lit inside its ghosted 5×5 grid, one
cyan cell on the meridian). `frontend/build.mjs` GENERATES every other cut
from that literal: static/brand/logo.svg (favicons + boot overlay) and
static/icon-192/512.png (PWA + /favicon.ico), while the bundle ships brand.js
itself for the in-app <BrandMark/>. Changing the logo is: edit QE_BRAND, run
`npm run build`, bump CACHE_NAME (the PNGs are precached cache-first under
stable names — the C1 lesson).

What this file guards, in order of what would actually hurt:
  1. THE FORK. Two renderers drifting apart (svg says one thing, brand.js
     another) silently re-creates the multi-source mess the module exists to
     kill — so the generated artifacts are PARITY-checked against brand.js,
     executed the same way build.mjs executes it (vm with a module stub;
     require() can't see the exports because frontend/ is "type":"module").
  2. THE STALE ICON. CACHE_NAME below the brand generation re-poisons every
     installed client with the old logo forever.
  3. THE IDENTITY RULES. The accent cell sits ON the meridian and is the only
     color; the ghost field is exactly the M's complement in the 5×5 grid.

The PNG probes decode the real bytes (pure python: our encoder writes
filter-0 scanlines precisely so tests can read pixels without a codec).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests._srcpin import code as _code  # noqa: E402

_ROOT = Path(__file__).parent.parent
_NODE = shutil.which("node")

_BRAND_JS = (_ROOT / "frontend" / "src" / "brand.js").read_text(encoding="utf-8")
_SVG = (_ROOT / "static" / "brand" / "logo.svg").read_text(encoding="utf-8")
_SW = (_ROOT / "static" / "service-worker.js").read_text(encoding="utf-8")
_V3 = (_ROOT / "templates" / "v3.html").read_text(encoding="utf-8")
_BASE = (_ROOT / "templates" / "base.html").read_text(encoding="utf-8")
_BUILD = (_ROOT / "frontend" / "build.mjs").read_text(encoding="utf-8")
_NAV = _code((_ROOT / "frontend" / "src" / "nav-and-data.jsx").read_text(encoding="utf-8"))

# The 5×5 grid the mark lives on (10-unit cells at 15-unit pitch).
_GRID = [14, 29, 44, 59, 74]
# 10C FIELD, from the ratified exploration sheet: the lit M…
_EXPECTED_M = {
    (14, 14), (74, 14),
    (14, 29), (29, 29), (59, 29), (74, 29),
    (14, 44), (74, 44),
    (14, 59), (74, 59),
    (14, 74), (74, 74),
}
_EXPECTED_ACCENT = (44, 44)
# …and the powered-off complement.
_EXPECTED_GHOST = {(x, y) for x in _GRID for y in _GRID} - _EXPECTED_M - {_EXPECTED_ACCENT}


def _load_brand() -> dict:
    """Execute brand.js EXACTLY the way build.mjs does (vm + module stub)."""
    out = subprocess.run(
        [_NODE, "-e",
         "const vm=require('vm'),fs=require('fs');"
         "const sb={module:{exports:{}}};"
         f"vm.runInNewContext(fs.readFileSync({json.dumps(str(_ROOT / 'frontend' / 'src' / 'brand.js'))},'utf8'),sb);"
         "console.log(JSON.stringify(sb.module.exports.QE_BRAND))"],
        capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ── 1. the source of truth itself ───────────────────────────────────────────

@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
class TestBrandDefinition:
    def test_the_mark_is_10C_FIELD_exactly(self):
        b = _load_brand()
        assert {tuple(c) for c in b["cells"]} == _EXPECTED_M
        assert tuple(b["accentCell"]) == _EXPECTED_ACCENT
        assert {tuple(c) for c in b["ghostCells"]} == _EXPECTED_GHOST

    def test_the_accent_sits_on_the_meridian_and_is_the_only_color(self):
        """The identity's signature: one cyan cell, centered on the vertical
        line the product is named for. DERIVED against the grid's own axis,
        not the viewBox's: the ratified sheet geometry spans units 14–84, so
        the grid center is 49 while the canvas center is 50 — asserting 50
        failed on the sheet's true geometry (caught on first run). The claim
        that matters is accent-centered-IN-THE-GRID; the 1-unit canvas offset
        is the sheet's, and the sheet is the design authority."""
        b = _load_brand()
        xs = [c[0] for c in b["cells"]] + [c[0] for c in b["ghostCells"]] + [b["accentCell"][0]]
        grid_center = (min(xs) + max(xs) + b["cell"]) / 2
        assert b["accentCell"][0] + b["cell"] / 2 == grid_center
        assert b["accent"].lower() == "#00e7ff"     # == --qe-cyan
        assert b["fg"].lower() == "#ffffff" and b["bg"].lower() == "#000000"
        assert b["ghostOpacity"] == 0.14

    def test_the_viewbox_is_the_canvas_every_renderer_assumes(self):
        """audit #2 — the constructed SURVIVOR: viewBox '0 0 200 200' shrank
        the SVG/nav mark to a quadrant while the PNGs stayed full-size, with
        all 20 tests green. The PNG scale now DERIVES from viewBox (build.mjs
        throws on a non-square one), and this pin holds the contract: the
        ratified cell geometry is authored in 100-space, so the viewBox IS
        part of the identity, not a free parameter."""
        b = _load_brand()
        assert b["viewBox"] == "0 0 100 100"
        # and the emitted SVG carries the SAME canvas — the fork the audit built
        assert f'viewBox="{b["viewBox"]}"' in _SVG

    def test_the_grid_is_complete_and_disjoint(self):
        """M + ghost + accent tile the 5×5 grid with no overlap — a cell in
        two sets would double-paint and shift color at PNG time."""
        b = _load_brand()
        m = {tuple(c) for c in b["cells"]}
        g = {tuple(c) for c in b["ghostCells"]}
        a = {tuple(b["accentCell"])}
        assert not (m & g) and not (m & a) and not (g & a)
        assert m | g | a == {(x, y) for x in _GRID for y in _GRID}

    def test_the_change_procedure_is_documented_at_the_definition(self):
        """The operator's requirement was 'changing the logo must not be a
        pain'. The procedure lives AT the data it applies to."""
        assert "TO CHANGE THE LOGO" in _BRAND_JS
        assert "npm run build" in _BRAND_JS
        assert "CACHE_NAME" in _BRAND_JS           # the stale-icon trap is named


# ── 2. the generated SVG is a pure function of brand.js (anti-fork) ─────────

@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
class TestSvgParity:
    def test_every_rect_derives_from_the_brand_data(self):
        b = _load_brand()
        rects = re.findall(r'<rect x="(\d+)" y="(\d+)" width="10" height="10"(.*?)/>', _SVG)
        got = {(int(x), int(y)): extra.strip() for x, y, extra in rects}
        assert set(got) == _EXPECTED_M | _EXPECTED_GHOST | {_EXPECTED_ACCENT}
        assert got[_EXPECTED_ACCENT] == f'fill="{b["accent"]}"'
        # ghost cells carry no per-rect fill — they inherit the ghost group
        ghost_group = re.search(
            r'<g fill="#ffffff" opacity="0\.14">(.*?)</g>', _SVG, re.S)
        assert ghost_group, "the ghost group (fill+opacity from brand.js) is gone"
        in_ghost = {(int(x), int(y)) for x, y in
                    re.findall(r'x="(\d+)" y="(\d+)"', ghost_group.group(1))}
        assert in_ghost == _EXPECTED_GHOST

    def test_the_svg_declares_itself_generated(self):
        assert "GENERATED by frontend/build.mjs" in _SVG
        assert "DO NOT EDIT" in _SVG

    def test_background_and_identity_attrs(self):
        assert '<rect width="100" height="100" fill="#000000"/>' in _SVG
        assert 'aria-label="MERIDIAN"' in _SVG


# ── 3. the PNG cuts, decoded byte-for-byte ──────────────────────────────────

def _decode_png(path: Path):
    d = path.read_bytes()
    assert d[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(d):
        ln = struct.unpack(">I", d[pos:pos + 4])[0]
        typ = d[pos + 4:pos + 8]
        if typ == b"IHDR":
            w, h, bit, ctype = struct.unpack(">IIBB", d[pos + 8:pos + 18])
            assert (bit, ctype) == (8, 6), "encoder contract: 8-bit RGBA"
        elif typ == b"IDAT":
            idat += d[pos + 8:pos + 8 + ln]
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * 4 + 1

    def px(x, y):
        assert raw[y * stride] == 0, "encoder contract: filter-0 scanlines"
        o = y * stride + 1 + x * 4
        return tuple(raw[o:o + 3])

    return w, h, px


class TestPngCuts:
    @pytest.mark.parametrize("name,size", [("icon-192.png", 192), ("icon-512.png", 512)])
    def test_dimensions_and_the_five_probe_pixels(self, name, size):
        """Center-of-cell probes at both sizes: bg, an M cell, THE accent
        cell (exact --qe-cyan), a ghost cell (white@14% over black = 36-gray),
        and an inter-cell gap (must stay bg — a fencepost error in the edge
        rounding paints the gaps)."""
        w, h, px = _decode_png(_ROOT / "static" / name)
        assert (w, h) == (size, size)
        s = size / 100
        c = lambda u: int((u + 5) * s)          # cell center
        assert px(2, 2) == (0, 0, 0)
        assert px(c(14), c(14)) == (255, 255, 255)
        assert px(c(44), c(44)) == (0, 231, 255)
        assert px(c(44), c(14)) == (36, 36, 36)  # round(255*0.14)
        assert px(int(26 * s), c(14)) == (0, 0, 0)

    def test_the_ghost_gray_is_derived_not_hardcoded(self):
        """36 must equal round(255 * ghostOpacity) — if someone retunes the
        opacity in brand.js and rebuilds, this stays green; if the PNGs were
        NOT rebuilt, the parity below catches it instead."""
        m = re.search(r"ghostOpacity:\s*([0-9.]+)", _BRAND_JS)
        assert m and round(255 * float(m.group(1))) == 36


# ── 4. every consumer points at the one identity ────────────────────────────

class TestConsumers:
    def test_v3_shell_finally_has_icons_and_a_manifest(self):
        """The React shell shipped with NO icon links at all — the tab showed
        the browser default glyph on the app's OWN chrome."""
        assert '<link rel="icon" type="image/svg+xml" href="/static/brand/logo.svg"/>' in _V3
        assert 'href="/static/icon-192.png"' in _V3
        assert '<link rel="manifest" href="/manifest.json"/>' in _V3

    def test_the_boot_overlay_renders_the_generated_asset(self):
        """An <img> of logo.svg — NOT an inline copy, which would be a second
        source of truth the next logo change silently misses."""
        i = _V3.index('id="boot"')
        boot = _V3[i:i + 700]
        assert '<img src="/static/brand/logo.svg"' in boot

    def test_base_html_gets_the_svg_favicon_too(self):
        assert '<link rel="icon" type="image/svg+xml" href="/static/brand/logo.svg" />' in _BASE

    def test_the_topnav_renders_brandmark_from_the_module(self):
        assert "<BrandMark size={16} ghost={false}" in _NAV

    def test_brand_js_ships_in_the_bundle_before_its_consumers(self):
        # scoped to the JSX_ORDER array — the bare string 'brand.js' appears
        # in build.mjs in three roles (order entry, emit path, comments), so a
        # whole-file substring check survived deleting the order entry
        # (mutation B13, first harness run).
        order = _BUILD[_BUILD.index("const JSX_ORDER = ["):_BUILD.index("];")]
        assert "'brand.js'" in order
        man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
        mods = man["modules"]
        assert "brand.js" in mods
        assert mods.index("brand.js") < mods.index("nav-and-data.jsx")
        bundle = (_ROOT / "static" / "v3" / man["app"]).read_text(encoding="utf-8")
        assert re.search(r"\bQE_BRAND\b", bundle) and re.search(r"\bBrandMark\b", bundle)

    def test_build_mjs_actually_emits_the_assets(self):
        """The generator existing is nothing if main() doesn't call it."""
        assert "const brand = await emitBrandAssets();" in _BUILD

    def test_favicon_route_and_pwa_manifest_serve_the_generated_files(self):
        src = (_ROOT / "main.py").read_text(encoding="utf-8")
        assert 'FileResponse("static/icon-192.png"' in src
        assert '"/static/icon-512.png"' in src

    def test_the_manifest_does_not_claim_maskable(self):
        """audit #1: a maskable icon is cropped to a ~80% circular safe zone,
        and this mark's four corner cells sit ~90% OUTSIDE it — launchers
        honoring the declaration would amputate the M's corners. 'any' is
        letterboxed safely; a padded maskable cut is a future addition, not a
        declaration to fake."""
        src = (_ROOT / "main.py").read_text(encoding="utf-8")
        assert "maskable" not in re.sub(r"#[^\n]*", "", src), \
            "manifest re-declares maskable over corner-clipping geometry"


# ── 5. the cache-generation rules ───────────────────────────────────────────

class TestServiceWorkerBrandRules:
    def test_cache_name_is_at_or_past_the_brand_generation(self):
        """The icons changed content under stable, precached, cache-first
        names. qre-v4 is the generation that shipped the new mark; anything
        below re-poisons installed clients with the OLD logo forever. A floor,
        not an exact pin — future bumps must stay green (release-hygiene
        lesson: exact version pins turn every later bump red)."""
        name = re.search(r"CACHE_NAME = '([^']+)'", _SW).group(1)
        assert int(name.split("-v")[1]) >= 4, name

    def test_logo_svg_stays_OUT_of_the_immutable_lane(self):
        """Deliberate: /static/brand/logo.svg keeps a stable filename, so it
        must remain browser-owned (normal HTTP revalidation) — cache-first
        would freeze every future logo swap until another CACHE_NAME bump."""
        lane = _SW[_SW.index("function isImmutableAsset"):_SW.index("addEventListener('fetch'")]
        assert "/static/brand" not in lane

    def test_the_icon_pngs_are_still_precached(self):
        """The other half of the trade: the PNGs ARE cache-first (offline PWA
        icon), which is exactly why the bump rule exists."""
        assert "'/static/icon-192.png'" in _SW
        assert "'/static/icon-512.png'" in _SW
