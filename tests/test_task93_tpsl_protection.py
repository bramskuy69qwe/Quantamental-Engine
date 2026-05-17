"""
Task 93 regression tests for HIGH-020 (RESOLVED) and HIGH-019 (VERIFIED FALSE).

HIGH-020: core/exchange.py::fetch_account was missing the null-check on
app_state._data_cache that fetch_positions has. Fix mirrors the existing
pattern. Test pins the null-safety.

HIGH-019: audit's "retry queue + awaiting-protection flag" recommendation
assumed engine-side TP/SL placement. Investigation found the engine is a
passive observer — it doesn't place orders, only observes them via WS
event streams. Test pins this architectural invariant by asserting no
`place_tp_sl` / `place_tpsl` / `create_tpsl` / `_place_protection_orders`
functions exist in core/.

Related residual concern (no time-bounded check for TP/SL observability
after entry) is filed separately as HIGH-027.

Run: pytest tests/test_task93_tpsl_protection.py -v
"""
from __future__ import annotations

import os
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── HIGH-020: fetch_account null-check ───────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_account_handles_uninitialized_data_cache(caplog):
    """HIGH-020 pin: fetch_account must null-check app_state._data_cache.
    Pre-fix: AttributeError when _data_cache is None. Post-fix: warning + return."""
    import logging
    from core import exchange

    # Mock adapter so fetch_account would otherwise succeed in adapter call
    mock_adapter = MagicMock()
    mock_adapter.fetch_account = AsyncMock(return_value=MagicMock())

    caplog.set_level(logging.WARNING, logger="core.exchange")
    with patch.object(exchange, "_get_adapter", return_value=mock_adapter), \
         patch("core.exchange.app_state") as mock_state:
        mock_state._data_cache = None
        # Must not raise
        result = await exchange.fetch_account()

    assert result is None  # matches fetch_positions early-return contract
    # adapter.fetch_account should NOT have been called — guard short-circuits before adapter
    mock_adapter.fetch_account.assert_not_called()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "DataCache not yet initialized" in r.getMessage() for r in warnings
    ), "Expected warning about uninitialized DataCache"


# ── HIGH-019: engine doesn't place TP/SL — architectural invariant pin ───────

def test_engine_does_not_place_tp_sl_orders():
    """HIGH-019 VERIFIED FALSE pin (Task 93).

    The engine is a passive observer of orders placed externally (Quantower
    plugin or user-side workflow). It does not place TP/SL orders itself.
    The audit's "retry queue + awaiting-protection flag" recommendation
    assumed engine-side placement — that assumption doesn't match this
    codebase.

    This test pins the architectural invariant: no `place_tp_sl`-style
    function exists in core/. If a future contributor adds engine-side
    TP/SL placement, the pin fails with explicit guidance to re-evaluate
    HIGH-019's fix shape and HIGH-027's design (both assumed
    passive-observer architecture).
    """
    forbidden_patterns = [
        r"def\s+place_tp_sl\b",
        r"def\s+place_tpsl\b",
        r"def\s+create_tpsl\b",
        r"def\s+_place_protection_orders\b",
    ]

    # core/ lives at repo root one level up from tests/
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    core_dir = os.path.join(repo_root, "core")
    assert os.path.isdir(core_dir), f"core/ not found at expected path: {core_dir}"

    matches = []
    for root, _dirs, files in os.walk(core_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                continue
            for pattern in forbidden_patterns:
                if re.search(pattern, content):
                    matches.append(f"{path}: matched /{pattern}/")

    assert matches == [], (
        f"HIGH-019 architectural invariant violated: engine appears to now "
        f"place TP/SL orders. Matches: {matches}. Re-evaluate HIGH-019's "
        f"recommended fix and HIGH-027's design — both assumed passive-observer "
        f"architecture where the engine only observes externally-placed orders."
    )
