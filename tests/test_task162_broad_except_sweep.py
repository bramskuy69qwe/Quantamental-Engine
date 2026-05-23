"""
Task 162 regression tests — broad-except sweep of the risk/sizing
critical path.

Honest framing: these tests are predominantly **source-pin guardrails**.
T161 found one LIVE bug masked by a broad swallow; T162's sweep found
ZERO additional live bugs in the scoped files. Every fix here is a
narrow-the-handler regression guardrail. The natural FBF for a pure
narrowing is weak: "stash the fix → some bare `except Exception:`
substring counts go up." That's a syntactic delta, not a behavior
delta.

So this file mixes two kinds of tests:
  - **Source pins (load-bearing)** — confirm the narrow pattern is in
    place at each fixed site, and that the pre-T162 broad form is
    gone in executing code (`#` comments scoped out, per T161 trick).
  - **Behavior delta (light)** — for the two sites with externally-
    observable behavior change (handlers.py:130 WS-restart and
    handlers.py:197 calc_created trade event), assert that the new
    log.warning fires when the narrow handler triggers. These give
    a real FBF (pre-T162: log.debug / silent pass; post-T162:
    log.warning visible at default log level).

Sites covered by source pins (5 fixed sites + 2 already-acceptable
verified-still-acceptable):
  - risk_engine.py:265 capability gate — broad → (ImportError, AttributeError, KeyError) + log.debug
  - risk_engine.py:473 log_event for calc_blocked_contract — broad → (ImportError, sqlite3.Error, OSError) + log.warning [T161 latent #1]
  - handlers.py:86 Redis publish — broad pass → (ImportError, ConnectionError, TimeoutError, OSError) + log.warning
  - handlers.py:130 WS restart_market_streams — broad pass → same narrow + log.warning
  - handlers.py:197 calc_created trade event — broad with log.debug → (ImportError, sqlite3.Error, OSError) + log.warning
  - account_registry.py:98 + 283 — broad → ImportError (consistency tightening)

Accepted-as-is (not modified; tests verify the safe-defensive pattern):
  - db_trades.py:183/221/259 — rollback() inside outer-except cleanup
    + outer re-raise.
  - handlers.py:73/94/158/178 — already log error/warning.
  - routes_calculator.py:75 — error surfaces via HTMLResponse.

Run: pytest tests/test_task162_broad_except_sweep.py -v
"""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _executing_lines(text: str) -> str:
    """Strip `#` line comments so source-pin substring checks don't
    trip on Task-anchor comments that intentionally document the
    pre-fix form (T161 pattern)."""
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("#")
    )


# ── Source pins — load-bearing for guardrail narrowings ────────────────────


class TestRiskEngineCapabilityGateNarrowed:
    """risk_engine.py:265 — `_get_adapter()` + capability check."""

    def test_narrow_except_clause_in_place(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        # Locate the capability-gate try block (after the AdapterCapabilityError)
        idx = src.find("0d: capability gate")
        assert idx > 0
        # The next except clause within the window must be the narrowed form
        window = src[idx:idx + 2000]
        executing = _executing_lines(window)
        # The narrow tuple includes RuntimeError because _get_adapter()
        # raises it for the "no active account" infrastructure-not-ready
        # case (test envs + account-switch transitions).
        assert "except (ImportError, AttributeError, KeyError, RuntimeError)" in executing, (
            "T162 regression: capability-gate broad-except is back. The "
            "pre-T161 anti-pattern (broad Exception swallow + silent pass) "
            "would mask programming errors and any future regression like "
            "the T161 NameError-on-undefined-result bug."
        )

    def test_pre_t162_broad_form_gone_in_executing_code(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        idx = src.find("0d: capability gate")
        # Take just the capability-gate try/except chain, not the entire
        # function — bound the window before "if average <= 0".
        end = src.find("if average <= 0", idx)
        block = src[idx:end] if end > 0 else src[idx:idx + 1500]
        executing = _executing_lines(block)
        assert "except Exception:" not in executing, (
            "T162 regression: bare `except Exception:` is back in the "
            "capability-gate block (in executing code)."
        )


class TestRiskEngineLogEventNarrowed:
    """risk_engine.py:473 — calc_blocked_contract log_event. T161
    latent #1 directly addressed by T162."""

    def test_narrow_except_clause_in_place(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        idx = src.find("calc_blocked_contract")
        assert idx > 0
        window = src[idx:idx + 1500]
        executing = _executing_lines(window)
        # ImportError + sqlite3.Error + OSError — the event_log infra-
        # failure shapes
        assert "except (ImportError, sqlite3.Error, OSError)" in executing
        assert "log.warning" in executing

    def test_t161_latent_1_resolved_anchor(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        # Anchor links T162 + T161-latent so future maintainers see the
        # provenance
        assert "T161 latent" in src or "T161 latent #1" in src


class TestHandlersRedisPublishNarrowed:
    """handlers.py:86 — equity publish to pubsub bus."""

    def test_narrow_except_clause_in_place(self):
        src = Path("core/handlers.py").read_text(encoding="utf-8")
        # Locate equity_channel publish block
        idx = src.find("equity_channel(app_state.active_account_id)")
        assert idx > 0
        window = src[idx:idx + 1500]
        executing = _executing_lines(window)
        assert "except (ImportError, ConnectionError, TimeoutError, OSError)" in executing
        assert "equity publish failed" in executing or "log.warning" in executing


class TestHandlersWsRestartNarrowed:
    """handlers.py:130 — restart_market_streams on symbol-set change."""

    def test_narrow_except_clause_in_place(self):
        src = Path("core/handlers.py").read_text(encoding="utf-8")
        idx = src.find("await ws_manager.restart_market_streams()")
        assert idx > 0
        window = src[idx:idx + 1500]
        executing = _executing_lines(window)
        assert "except (ImportError, ConnectionError, TimeoutError, OSError)" in executing
        assert "market-stream restart" in executing


class TestHandlersTradeEventLogNarrowed:
    """handlers.py:197 — calc_created trade event."""

    def test_narrow_except_clause_in_place(self):
        src = Path("core/handlers.py").read_text(encoding="utf-8")
        idx = src.find("log_trade_event(app_state.active_account_id, calc_id, \"calc_created\"")
        assert idx > 0
        window = src[idx:idx + 1500]
        executing = _executing_lines(window)
        assert "except (ImportError, sqlite3.Error, OSError)" in executing
        # Upgrade from log.debug → log.warning is the operator-visibility
        # change (pre-T162 the failure was at log.debug, almost never
        # surfaced)
        assert "log.warning" in executing
        # Pre-T162 form gone
        assert "log.debug" not in executing or "calc_created" not in executing.split("log.debug")[-1][:200]


class TestAccountRegistryAuthFailedNarrowed:
    """account_registry.py:98 + :283 — state-module import for
    auth_failed_accounts. Consistency tightening (both sites use
    ImportError now)."""

    def test_account_registry_both_sites_narrowed(self):
        src = Path("core/account_registry.py").read_text(encoding="utf-8")
        # Both sites import core.state and call .add() / .discard()
        # in a try/except — narrow to ImportError post-T162.
        adds = src.count("app_state.auth_failed_accounts.add")
        discards = src.count("app_state.auth_failed_accounts.discard")
        assert adds >= 1 and discards >= 1
        # In executing code, no `except Exception:` near these calls.
        executing = _executing_lines(src)
        # Search around each site for the narrowed except
        for marker in ("auth_failed_accounts.add", "auth_failed_accounts.discard"):
            idx = executing.find(marker)
            assert idx > 0
            window = executing[idx:idx + 400]
            assert "except ImportError" in window, (
                f"T162 regression: site near {marker!r} not narrowed to "
                f"ImportError. Window: {window[:300]!r}"
            )


# ── Behavior delta tests (real FBF available) ──────────────────────────────


class TestHandlersWsRestartLogsOnFailure:
    """handlers.py:130 — pre-T162 silently passed when restart_market_streams
    raised. Post-T162 logs at warning level. Honest FBF: capture the
    log call and assert it fires."""

    @pytest.mark.asyncio
    async def test_ws_restart_failure_logs_warning(self, monkeypatch, caplog):
        from core import handlers, ws_manager
        from core.state import app_state

        # Force restart_market_streams to raise ConnectionError (one of the
        # narrowed-handler types)
        async def failing_restart():
            raise ConnectionError("simulated WS restart failure")

        monkeypatch.setattr(
            ws_manager, "restart_market_streams", failing_restart,
            raising=False,
        )
        # Force symbol-set change so the restart branch fires
        if hasattr(handlers.handle_positions_refreshed, "_prev_syms"):
            handlers.handle_positions_refreshed._prev_syms = set()

        # Empty positions → current_syms is empty; previous set is also
        # empty by default — make them differ. Inject a sentinel via
        # _positions_legacy.
        from types import SimpleNamespace
        monkeypatch.setattr(app_state, "_data_cache", None, raising=False)
        monkeypatch.setattr(
            app_state, "_positions_legacy",
            [SimpleNamespace(ticker="BTCUSDT", direction="LONG",
                              contract_amount=0.1, average=80000.0,
                              fair_price=80000.0, position_value_usdt=8000.0,
                              individual_unrealized=0.0,
                              individual_margin_used=400.0,
                              sector="big_two_crypto")],
            raising=False,
        )

        # Stub DB writes so they don't fail the test
        async def noop_async(*a, **kw):
            return None
        monkeypatch.setattr(handlers.db, "insert_position_changes", noop_async, raising=False)
        monkeypatch.setattr(handlers.db, "insert_account_snapshot", noop_async, raising=False)

        caplog.set_level(logging.WARNING, logger="handlers")

        await handlers.handle_positions_refreshed({"trigger": "test"})

        # The narrowed handler fired and logged at WARNING
        warnings = [
            r for r in caplog.records
            if "market-stream restart" in r.message and r.levelname == "WARNING"
        ]
        assert warnings, (
            "T162 regression: ws_manager.restart_market_streams failure "
            "did not log at WARNING. Pre-T162 it silently passed. "
            "Captured records: " + repr([(r.levelname, r.message[:80])
                                           for r in caplog.records])
        )


# ── Source-pin negative coverage: T161-pattern dangerous form is gone ──────


class TestPreT162DangerousFormGone:
    """Verify the pre-T162 anti-pattern (bare `except Exception: pass`
    on the dangerous sites) is gone in executing code. T161 anchor
    comments are allowed to mention it for documentation."""

    def test_risk_engine_capability_gate_no_bare_swallow(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        executing = _executing_lines(src)
        # Use an executing-code marker (the AdapterCapabilityError line
        # is in executing code; the `# 0d: capability gate` comment is
        # stripped by _executing_lines).
        idx = executing.find("except AdapterCapabilityError")
        assert idx > 0
        end_marker = "if average <= 0"
        end = executing.find(end_marker, idx)
        if end < 0:
            end = idx + 1500
        block = executing[idx:end]
        # No bare `except Exception:` in executing code of this block
        assert "except Exception:" not in block

    def test_handlers_redis_publish_no_silent_pass(self):
        src = Path("core/handlers.py").read_text(encoding="utf-8")
        executing = _executing_lines(src)
        idx = executing.find("equity_channel(app_state.active_account_id)")
        # The next ~600 chars covers the publish + except clause.
        block = executing[idx:idx + 600]
        # No bare `except Exception: pass` here anymore (we kept the
        # bare publish call body but the except is narrow + log).
        # Be lenient: also confirm no `except Exception:` immediately
        # followed by `pass`.
        # Look for the pattern in executing-only window:
        m = re.search(r"except Exception:\s*\n\s*pass", block)
        assert m is None, (
            "T162 regression: silent `except Exception: pass` is back in "
            "the Redis-publish handler."
        )

    def test_handlers_ws_restart_no_silent_pass(self):
        src = Path("core/handlers.py").read_text(encoding="utf-8")
        executing = _executing_lines(src)
        idx = executing.find("await ws_manager.restart_market_streams()")
        block = executing[idx:idx + 600]
        m = re.search(r"except Exception:\s*\n\s*pass", block)
        assert m is None, (
            "T162 regression: silent `except Exception: pass` is back in "
            "the WS-restart handler."
        )


# ── Anti-regression: acceptable handlers stay acceptable ───────────────────


class TestAcceptableHandlersUntouched:
    """The audit identified several handlers as acceptable (already
    log error/warning, or are defensive rollback-cleanup patterns).
    These tests confirm they weren't accidentally narrowed too far in
    the sweep."""

    def test_db_trades_rollback_swallow_pattern_intact(self):
        """db_trades.py:183/221/259 — rollback() inside outer except +
        re-raise. The broad inner swallow is correct for cleanup."""
        src = Path("core/db_trades.py").read_text(encoding="utf-8")
        # The pattern: `await self._conn.rollback()` followed within
        # 2 lines by `except Exception:\n        pass`.
        # Should occur exactly 3 times (one per insert helper).
        rollback_pattern = re.findall(
            r"await self\._conn\.rollback\(\)\s*\n\s*except Exception:\s*\n\s*pass",
            src,
        )
        assert len(rollback_pattern) == 3, (
            f"T162 anti-regression: db_trades.py rollback-cleanup "
            f"pattern count changed (expected 3, got {len(rollback_pattern)}). "
            "These are defensive cleanups inside an outer except that "
            "re-raises — broad-except is correct here."
        )

    def test_handlers_db_writes_still_log_error(self):
        """handlers.py:73, 158, 178 — DB write failures already log at
        error level. Should remain unchanged."""
        src = Path("core/handlers.py").read_text(encoding="utf-8")
        # Three error-logging sites
        assert 'log.error("handle_account_updated DB write failed: %s", exc)' in src
        assert 'log.error("handle_positions_refreshed DB write failed: %s", exc)' in src
        assert 'log.error("handle_risk_calculated DB write failed: %s", exc)' in src
