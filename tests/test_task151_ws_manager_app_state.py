"""
Task 151 regression tests — FE-MED-034
`_user_data_loop` UnboundLocalError on `app_state`.

Bug: `core/ws_manager.py` had `from core.state import app_state` at
module level (line 24) AND a duplicate `from core.state import
app_state` inside a nested `except CredentialDecryptionError`
branch at line 480. Python's lexical-scoping rule: any name
assigned anywhere in a function is local THROUGHOUT — so the inline
import marked `app_state` as a local variable for ALL of
`_user_data_loop`. Every reference before line 480's import ran
hit a LOAD_FAST on an unbound local → UnboundLocalError.

The FE-MED-034 audit-doc framing called this a "shutdown race".
Investigation revealed the timing is incidental — the bug fires
on every function call that reaches an unbound `app_state` read.
Visibility only surfaces during shutdown because asyncio task
cancellation flushes the "task exception was never retrieved"
buffer where the otherwise-swallowed errors finally appear.

Fix (Task 151): delete line 480's redundant inline import.
Module-level import at line 24 already binds `app_state`; the
inline re-import created the local-shadow conflict. Anchor
comment in the source explains why the import is deliberately
absent so a future refactor doesn't re-introduce it.

Run: pytest tests/test_task151_ws_manager_app_state.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ── Source-pins ─────────────────────────────────────────────────────────────

class TestUserDataLoopSourceShape:
    """Pin the source-level invariants — module-level import present;
    no inline import inside `_user_data_loop`; anchor comment so
    future maintainers don't re-introduce the shadow."""

    def _read_ws_manager(self) -> str:
        return Path("core/ws_manager.py").read_text(encoding="utf-8")

    def test_module_level_app_state_import_present(self):
        """The module-level `from core.state import app_state` at line
        ~24 must remain — it's the binding the function relies on."""
        src = self._read_ws_manager()
        # Module-level (no leading whitespace) import line
        assert "\nfrom core.state import app_state\n" in src, (
            "Module-level `from core.state import app_state` missing — "
            "removing it would make every app_state reference in this "
            "module NameError. Bug shape would change but break worse."
        )

    def test_no_inline_app_state_import_in_user_data_loop(self):
        """The inline `from core.state import app_state` inside
        `_user_data_loop` must be gone. Re-introducing it would
        restore the local-shadow bug."""
        src = self._read_ws_manager()
        # Locate the function body
        idx = src.find("async def _user_data_loop")
        assert idx > 0, "_user_data_loop function not found"
        # Find next top-level function (4-space-indented `async def`
        # at the start of a line, or end-of-file)
        end = src.find("\nasync def ", idx + 10)
        if end < 0:
            end = src.find("\ndef ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:]
        # Source must NOT contain an inline import of app_state
        # (anchor comment mentions the old line — that's documentation
        # of the bug shape, not the bug itself; scope to non-comment
        # lines).
        bad = []
        for ln, line in enumerate(body.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "from core.state import app_state" in line:
                bad.append((ln, line.strip()))
        assert not bad, (
            f"FE-MED-034 regression: inline `from core.state import "
            f"app_state` reintroduced inside _user_data_loop. The "
            f"module-level import already provides the binding; the "
            f"inline import creates a local-shadow bug. Offending: "
            f"{bad!r}"
        )

    def test_anchor_comment_references_fe_med_034(self):
        """Anchor comment must explain why the import is deliberately
        absent — without it, a future maintainer might 'add the
        missing import' and re-introduce the bug."""
        src = self._read_ws_manager()
        idx = src.find("async def _user_data_loop")
        end = src.find("\nasync def ", idx + 10)
        body = src[idx:end] if end > 0 else src[idx:]
        assert "FE-MED-034" in body and "Task 151" in body, (
            "Anchor comment for FE-MED-034 / Task 151 missing inside "
            "_user_data_loop — future maintainers may re-add the inline "
            "import."
        )


# ── Bytecode pin: `app_state` resolves as a GLOBAL, not a LOCAL ─────────────

class TestUserDataLoopBytecode:
    """Python's local-vs-global determination is what made the bug
    possible: with the inline import, `app_state` was marked local
    (LOAD_FAST opcode); without it, `app_state` resolves via
    LOAD_GLOBAL (module-level binding). Pin this directly — the
    bytecode is the ground truth, source-level checks are proxies."""

    def test_app_state_is_global_in_user_data_loop(self):
        """If `app_state` appears in the function's co_varnames (the
        locals list), it's local — meaning the bug shape is present.
        Post-fix, it should appear in co_names (globals referenced)
        or not be a varname at all."""
        from core import ws_manager

        # _user_data_loop is async; the function object is the
        # coroutine constructor.
        func = ws_manager._user_data_loop
        code = func.__code__

        assert "app_state" not in code.co_varnames, (
            f"FE-MED-034 regression: `app_state` appears in "
            f"_user_data_loop's co_varnames ({code.co_varnames!r}). "
            f"That means Python compiled it as a local — every "
            f"reference uses LOAD_FAST and will hit UnboundLocalError "
            f"before the local is assigned. The inline `from "
            f"core.state import app_state` import must have been "
            f"re-introduced somewhere in the function body."
        )
        # Defensive: should appear in co_names (globals referenced).
        # If the function genuinely doesn't use app_state any more
        # (refactor), this test stays meaningful — the assertion
        # above still holds.
        assert "app_state" in code.co_names, (
            "Expected `app_state` to appear in _user_data_loop's "
            "co_names (module-level globals referenced). If the "
            "function legitimately no longer uses app_state, update "
            "this test."
        )
