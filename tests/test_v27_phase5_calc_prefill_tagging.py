"""
v2.7 Phase 5 — calculator pre-fill + linkage tagging.

Pins (docs/design/v2.7_model_library_plan.md, Phase 5):
- _parse_model_id lanes (5.2 route parse)
- insert_pre_trade_log persists model_id — THE silent-drop trap: the
  INSERT is an explicit column list, a missing entry drops the key
  without error (plan 5.2)
- get_model_stamp_for_calc resolution ladder: row free-text wins →
  library name via the FK → "(deleted model)" on a dangling id
- insert_closed_position choke-point enrichment (5.4): model stamp
  from the row's calc on live-shaped AND rebuilt-from-fills-shaped
  rows; caller-provided model_name never overridden; no-calc rows
  untouched
- calculator.html picker markup + ?model_id= consumption + the
  visible-toggle+hidden-input pairing (5.1, P4 audit carry-forward)

The corr-log db_write tap payload for pre_trade_log is FROZEN — the
existing test_correlation_log_state pins assert it; nothing here (or
in the diff) touches it.

Run: pytest tests/test_v27_phase5_calc_prefill_tagging.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.routes_calculator import _parse_model_id
from api.helpers import templates
from core.database import DatabaseManager

TEMPLATES = Path(__file__).parent.parent / "templates"


@pytest_asyncio.fixture
async def pdb():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
    yield database
    await database.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _seed_calc(db, calc_id, *, model_id=None, model_name=""):
    await db._conn.execute(
        "INSERT INTO pre_trade_log (timestamp, ticker, calc_id, model_id, "
        "model_name) VALUES (?, ?, ?, ?, ?)",
        ("2026-07-16T00:00:00", "BTCUSDT", calc_id, model_id, model_name),
    )
    await db._conn.commit()


def _close_row(**over):
    row = {
        "account_id": 1, "terminal_position_id": "tp-1", "symbol": "BTCUSDT",
        "direction": "long", "quantity": 1.0, "entry_price": 100.0,
        "exit_price": 110.0, "entry_time_ms": 1000, "exit_time_ms": 2000,
        "realized_pnl": 10.0, "total_fees": 0.1, "net_pnl": 9.9,
        "exit_reason": "TP", "model_name": "", "source": "live",
        "calc_id": None,
    }
    row.update(over)
    return row


async def _read_close(db, tpid):
    async with db._conn.execute(
        "SELECT model_id, model_name FROM closed_positions "
        "WHERE terminal_position_id=?", (tpid,),
    ) as cur:
        return await cur.fetchone()


# ── 5.2: route parse + the column-list trap ─────────────────────────────────

def test_parse_model_id_lanes():
    assert _parse_model_id("") is None
    assert _parse_model_id("   ") is None
    assert _parse_model_id("5") == 5
    assert _parse_model_id("0") is None
    assert _parse_model_id("-3") is None
    with pytest.raises(ValueError, match="integer"):
        _parse_model_id("abc")


@pytest.mark.asyncio
async def test_insert_pre_trade_log_persists_model_id(pdb):
    """The silent-drop trap: model_id must be in the column list, the
    placeholders AND the values dict — a miss in any drops it silently."""
    await pdb.insert_pre_trade_log({
        "ticker": "BTCUSDT", "calc_id": "c-tag", "model_id": 7,
        "model_name": "picked",
    })
    async with pdb._conn.execute(
        "SELECT model_id, model_name FROM pre_trade_log WHERE calc_id=?",
        ("c-tag",),
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 7 and row[1] == "picked"

    await pdb.insert_pre_trade_log({"ticker": "BTCUSDT", "calc_id": "c-none"})
    async with pdb._conn.execute(
        "SELECT model_id FROM pre_trade_log WHERE calc_id=?", ("c-none",),
    ) as cur:
        assert (await cur.fetchone())[0] is None


# ── get_model_stamp_for_calc resolution ladder ──────────────────────────────

@pytest.mark.asyncio
async def test_stamp_resolution_ladder(pdb):
    mid = await pdb.create_potential_model("LibName", "micro", "", {})

    await _seed_calc(pdb, "c-freetext", model_id=mid, model_name="Typed")
    stamp = await pdb.get_model_stamp_for_calc("c-freetext")
    assert stamp == {"model_id": mid, "model_name": "Typed"}  # free text wins

    await _seed_calc(pdb, "c-fk-only", model_id=mid, model_name="")
    stamp = await pdb.get_model_stamp_for_calc("c-fk-only")
    assert stamp == {"model_id": mid, "model_name": "LibName"}  # join name

    await _seed_calc(pdb, "c-text-only", model_id=None, model_name="Manual")
    stamp = await pdb.get_model_stamp_for_calc("c-text-only")
    assert stamp == {"model_id": None, "model_name": "Manual"}

    assert await pdb.get_model_stamp_for_calc("c-unknown") is None
    assert await pdb.get_model_stamp_for_calc("") is None

    await pdb.delete_potential_model(mid)
    stamp = await pdb.get_model_stamp_for_calc("c-fk-only")
    assert stamp == {"model_id": mid, "model_name": "(deleted model)"}


# ── 5.4: close-row choke-point enrichment ───────────────────────────────────

@pytest.mark.asyncio
async def test_close_row_stamped_from_tagged_calc(pdb):
    mid = await pdb.create_potential_model("Breakout", "micro", "", {})
    await _seed_calc(pdb, "c1", model_id=mid, model_name="")
    await pdb.insert_closed_position(_close_row(
        terminal_position_id="tp-live", calc_id="c1"))
    row = await _read_close(pdb, "tp-live")
    assert row[0] == mid and row[1] == "Breakout"


@pytest.mark.asyncio
async def test_close_row_caller_name_wins_model_id_still_stamped(pdb):
    mid = await pdb.create_potential_model("Lib", "micro", "", {})
    await _seed_calc(pdb, "c2", model_id=mid, model_name="")
    await pdb.insert_closed_position(_close_row(
        terminal_position_id="tp-legacy", calc_id="c2",
        model_name="ShortfallName"))
    row = await _read_close(pdb, "tp-legacy")
    assert row[0] == mid
    assert row[1] == "ShortfallName"  # legacy heuristic name preserved


@pytest.mark.asyncio
async def test_close_row_without_calc_untouched(pdb):
    await pdb.insert_closed_position(_close_row(
        terminal_position_id="tp-nocalc", calc_id=None))
    row = await _read_close(pdb, "tp-nocalc")
    assert row[0] is None and row[1] == ""


@pytest.mark.asyncio
async def test_rebuilt_from_fills_row_gets_stamped(pdb):
    """The plan-5.4 rebuild lane: position_grouping's builder leaves
    model_name='' (pure function) — the insert choke point resolves it."""
    mid = await pdb.create_potential_model("RebuiltModel", "macro", "", {})
    await _seed_calc(pdb, "c3", model_id=mid, model_name="")
    await pdb.insert_closed_position(_close_row(
        terminal_position_id="synth-1", calc_id="c3",
        source="rebuilt_from_fills", exit_reason="MANUAL_OTHER"))
    row = await _read_close(pdb, "synth-1")
    assert row[0] == mid and row[1] == "RebuiltModel"


@pytest.mark.asyncio
async def test_collision_shape_primary_calc_wins_over_window_neighbor(pdb):
    """P5 audit MED (both auditors): the T234 window-collision shape. A
    DIFFERENT calc with a free-text name exists for the same symbol; the
    close row (caller name blanked by the order_manager gate) must stamp
    the PRIMARY calc's model — never the neighbor's name."""
    mid = await pdb.create_potential_model("RightModel", "micro", "", {})
    await _seed_calc(pdb, "c-primary", model_id=mid, model_name="")
    await _seed_calc(pdb, "c-window-neighbor", model_id=None,
                     model_name="WrongName")
    await pdb.insert_closed_position(_close_row(
        terminal_position_id="tp-collision", calc_id="c-primary",
        model_name=""))  # the gate blanks the heuristic name when calc set
    row = await _read_close(pdb, "tp-collision")
    assert row[0] == mid and row[1] == "RightModel"


@pytest.mark.asyncio
async def test_stamp_dedup_aligns_with_sibling_on_mixed_tagging(pdb):
    """P5 audit NIT-6 fold: duplicate calc_id rows where the NEWEST is
    untagged+unnamed — the stamp falls back to the newest TAGGED row
    (the sibling get_model_for_calc rule) instead of returning empty."""
    mid = await pdb.create_potential_model("Tagged", "micro", "", {})
    await _seed_calc(pdb, "c-dup", model_id=mid, model_name="")
    await _seed_calc(pdb, "c-dup", model_id=None, model_name="")  # newer
    stamp = await pdb.get_model_stamp_for_calc("c-dup")
    assert stamp == {"model_id": mid, "model_name": "Tagged"}

    # Truly nothing anywhere → None, not a truthy-empty dict.
    await _seed_calc(pdb, "c-empty", model_id=None, model_name="")
    assert await pdb.get_model_stamp_for_calc("c-empty") is None


@pytest.mark.asyncio
async def test_untagged_calc_keeps_freetext_ladder(pdb):
    """A calc with only free-text model_name (no picker) still stamps
    the name onto the close row — the pre-5.4 behavior, now via the
    stamp instead of only the shortfall heuristic."""
    await _seed_calc(pdb, "c4", model_id=None, model_name="HandTyped")
    await pdb.insert_closed_position(_close_row(
        terminal_position_id="tp-hand", calc_id="c4"))
    row = await _read_close(pdb, "tp-hand")
    assert row[0] is None and row[1] == "HandTyped"


# ── 5.1: calculator template wiring ─────────────────────────────────────────

def test_calculator_template_compiles():
    templates.env.get_template("calculator.html")


def test_calculator_picker_wiring_pins():
    """Source pins ONLY — the JS never executes here (browser-level tests
    are deferred post-v3 per the HANDOFF Track-2 doctrine: today's DOM is
    throwaway). What a browser test would add: picker population from
    /api/models, live ?model_id= consumption, and the toggle+hidden
    pairing under real events."""
    src = (TEMPLATES / "calculator.html").read_text(encoding="utf-8")
    assert 'name="model_id"' in src and 'id="model-picker"' in src
    # The picker is INSIDE #calc-form — that containment IS the
    # "supersede keeps its model" mechanism (a form field re-rides every
    # recalc submit); scenario-level pinning is browser-territory.
    assert src.index('id="calc-form"') < src.index('id="model-picker"')
    # ?model_id= consumption (P4 audit carry-forward: the Load-into-
    # Calculator anchor degrades to a plain link without this).
    assert "URLSearchParams(window.location.search).get('model_id')" in src
    # Prefill must set the VISIBLE toggle AND its hidden input.
    assert "cb.checked = !!rp.apply_regime_multiplier" in src
    assert "document.getElementById('apply_regime_val').value = cb.checked" in src
    assert "/calculator/prefill/" in src
    # P5 audit folds: Clear drops the picker; saved state carries modelId.
    assert "_mp.value=''" in src
    assert "modelId:" in src


def test_model_sort_key_allowlisted_and_validates():
    """Holistic-audit F3: the Model header's sort key must be in the
    shared allowlist — validate_sort_params 400s on miss, so a missing
    entry means EVERY header click errors (route-side; template-wiring
    tests can't see it)."""
    from core.database import DatabaseManager
    from core.sql_safety import validate_sort_params
    assert "model_name" in DatabaseManager._CLOSED_POS_SORT_COLS
    assert validate_sort_params(
        "model_name", "asc", DatabaseManager._CLOSED_POS_SORT_COLS
    ) == ("model_name", "ASC")


def _sort_table_pairs():
    """Every sort_th-emitting history table paired with its allowlist
    (audit fold: the F3 class pin generalized to ALL seven tables — the
    siblings are clean today but were unpinned against the same drift)."""
    from core.database import DatabaseManager as D
    return [
        ("closed_positions_table.html", D._CLOSED_POS_SORT_COLS),
        ("fills_table.html", D._FILLS_SORT_COLS),
        ("order_history_table.html", D._ORDERS_SORT_COLS),
        ("open_orders_table.html", D._ORDERS_SORT_COLS),
        ("exchange_table.html", D._EXCHANGE_HISTORY_SORT_COLS),
        ("pre_trade_table.html", D._PRE_TRADE_SORT_COLS),
        ("trade_history_table.html", D._TRADE_HISTORY_SORT_COLS),
    ]


def test_every_sort_header_key_is_allowlisted():
    """The CLASS pin for F3: every sort_th key a history table emits
    must be in its route/DB allowlist — a new column added to a template
    without the allowlist entry fails here, not in the operator's face
    (route-side validate_sort_params 400s on every header click)."""
    import re
    for template, allowed in _sort_table_pairs():
        src = (TEMPLATES / "fragments" / "history" / template
               ).read_text(encoding="utf-8")
        keys = re.findall(r'sort_th\("[^"]+",\s*"([A-Za-z0-9_]+)"', src)
        assert keys, f"no sort_th calls found in {template} — moved?"
        missing = [k for k in keys if k not in allowed]
        assert not missing, f"{template}: sort keys not allowlisted: {missing}"


def test_closed_positions_table_renders_model_column():
    """5.3 render surface: the closed-positions table carries the Model
    column (header + cell reading model_name with an em-dash fallback)."""
    src = (TEMPLATES / "fragments" / "history"
           / "closed_positions_table.html").read_text(encoding="utf-8")
    assert '"Model",      "model_name"' in src
    assert "r.model_name or '—'" in src
    templates.env.get_template("fragments/history/closed_positions_table.html")
