"""
Regression tests for core/exec_link.py CRIT-004 behavior.

These tests pin the 1/1 honest semantics introduced in Task 87. Comprehensive
coverage of the module is Phase 11 (Task 120) scope; this file only contains
the CRIT-004 regression pins.

Run: pytest tests/test_exec_link.py -v
"""
from __future__ import annotations

from core.exec_link import compute_exec_match, get_exec_link_status


# ── compute_exec_match — 1/1 semantics ───────────────────────────────────────

def test_match_count_is_1_when_entry_matches_limit_order():
    """CRIT-004: 1/1 honest semantics — entry match → count=1, auto_link=True."""
    fill = {"price": 100.0, "calc_id": "abc"}
    pretrade = {"effective_entry": 100.0, "tp_price": 110.0, "sl_price": 95.0}
    r = compute_exec_match(fill, pretrade, order_type="LIMIT")
    assert r.entry_match is True
    assert r.match_count == 1, \
        "Under 1/1 semantics, count should be 1 when entry matches, not 3."
    assert r.auto_link is True


def test_match_count_is_0_when_entry_fails_limit_order():
    """CRIT-004: 1/1 honest semantics — entry fail → count=0, auto_link=False."""
    fill = {"price": 105.0, "calc_id": "abc"}  # outside tolerance
    pretrade = {"effective_entry": 100.0, "tp_price": 110.0, "sl_price": 95.0}
    r = compute_exec_match(fill, pretrade, order_type="LIMIT")
    assert r.entry_match is False
    assert r.match_count == 0
    assert r.auto_link is False


def test_market_order_always_links_1of1():
    """CRIT-004: market orders bypass entry comparison; count=1, auto_link=True."""
    fill = {"price": 100.0, "calc_id": "abc"}
    pretrade = {"effective_entry": 999.0, "tp_price": 110.0, "sl_price": 95.0}
    r = compute_exec_match(fill, pretrade, order_type="MARKET")
    assert r.entry_match is True
    assert r.match_count == 1
    assert r.auto_link is True


def test_tp_sl_remain_informational_stubs_post_CRIT_004():
    """CRIT-004 stub-pinning regression.

    The typo (tp_match / sl_match self-comparing pretrade values) is INTENTIONALLY
    preserved as a known stub — fixing it without the Phase 9 caller-threading
    work would still produce wrong results. This test makes a future contributor's
    accidental half-fix loudly fail.

    When Phase 9 lands and TP/SL match real placed orders, this test MUST be
    replaced with proper plan-vs-actual assertions. Do not edit this test to
    make a half-fix pass.
    """
    fill = {"price": 100.0, "calc_id": "abc"}

    # Plausible TP/SL: tp_match and sl_match are True (would also be True under real fix).
    pretrade_plausible = {"effective_entry": 100.0, "tp_price": 110.0, "sl_price": 95.0}
    r = compute_exec_match(fill, pretrade_plausible, order_type="LIMIT")
    assert r.tp_match is True
    assert r.sl_match is True

    # Wildly different TP/SL: still True under the stub (compares pretrade against itself).
    # Under a real plan-vs-actual fix, these would be False — which is the failure
    # that should force Phase 9 implementation, not a quick typo edit.
    pretrade_divergent = {"effective_entry": 100.0, "tp_price": 999.0, "sl_price": 0.01}
    r2 = compute_exec_match(fill, pretrade_divergent, order_type="LIMIT")
    assert r2.tp_match is True, \
        "Stub broken? See module docstring + CRIT-004 audit entry."
    assert r2.sl_match is True, \
        "Stub broken? See module docstring + CRIT-004 audit entry."

    # And critically: tp_match/sl_match must NOT affect match_count under 1/1 semantics,
    # even though they're True.
    assert r2.match_count == 1  # entry matched, regardless of TP/SL contributions
    assert r2.auto_link is True


# ── get_exec_link_status — 1/1 semantics ─────────────────────────────────────

def test_get_exec_link_status_confirmed_fill_returns_1_not_3():
    """CRIT-004: get_exec_link_status returns (linked, 1) on confirmed, not (linked, 3)."""
    fill = {"price": 100.0, "calc_id": "abc", "exec_link_confirmed": True}
    status, count = get_exec_link_status(fill, pretrade=None, order_type="LIMIT")
    assert status == "linked"
    assert count == 1, "Confirmed path should return count=1 under 1/1 semantics, not 3."


def test_get_exec_link_status_no_calc_id_unlinked():
    """Sanity: no calc_id → unlinked."""
    fill = {"price": 100.0}
    status, count = get_exec_link_status(fill, pretrade=None, order_type="LIMIT")
    assert status == "unlinked"
    assert count == 0


def test_get_exec_link_status_entry_match_returns_linked():
    """1/1: entry match through compute path → 'linked', count=1."""
    fill = {"price": 100.0, "calc_id": "abc"}
    pretrade = {"effective_entry": 100.0, "tp_price": 110.0, "sl_price": 95.0}
    status, count = get_exec_link_status(fill, pretrade, order_type="LIMIT")
    assert status == "linked"
    assert count == 1


def test_get_exec_link_status_entry_fail_returns_unlinked():
    """1/1: entry fail → 'unlinked' (partial branch is unreachable under 1/1)."""
    fill = {"price": 200.0, "calc_id": "abc"}
    pretrade = {"effective_entry": 100.0, "tp_price": 110.0, "sl_price": 95.0}
    status, count = get_exec_link_status(fill, pretrade, order_type="LIMIT")
    assert status == "unlinked"
    assert count == 0
