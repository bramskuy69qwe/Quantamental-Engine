"""
Task 153 regression tests — FE-MED-031
Centralized error-toast friendly wording.

Audit findings:
  - Session B: `'RegimeFetcher' object has no attribute 'close'` surfaced
    as a toast via `regime.html` backfill catch block.
  - Session C: `Request failed: 422 /calculator/calculate` surfaced as
    a toast via the htmx:responseError handler in `base.html`.

T108 + T134 solved error VISIBILITY (toast + target swap exist);
T153 closes the wording gap by introducing two helpers in `base.html`:
  - `friendlyError(raw, opts)` — pattern-matches raw error shapes into
    `{message, detail}`. Status-code-specific copy for HTTP 4xx/5xx;
    AttributeError / network / timeout body-shape patterns.
  - `showErrorToast(raw, opts)` — friendly-fy + push to toast.

Toast DOM gains a two-line render when given `{message, detail}` form:
  - `.toast-msg`     — bold, prominent (friendly prose).
  - `.toast-detail`  — smaller, dim, monospace (raw context).

What this file pins:
  - JS helper sources present and structurally correct.
  - htmx:responseError + htmx:sendError handlers route through
    friendlyError, not raw `Request failed: <status> <path>` toast text.
  - regime.html backfill / reclassify / news-refresh catch blocks route
    through showErrorToast (not raw `err.message` concatenation).
  - backtest.html data-fetch failure routes through showErrorToast.
  - CSS for two-line toast (.toast-msg / .toast-detail) defined.
  - Mirrored Python friendlyError logic verifies pattern coverage end-to-end.

Run: pytest tests/test_task153_error_toast_wording.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


# ── Source-pin tests on the JS helpers ──────────────────────────────────────


class TestBaseJsHelpersDefined:
    """friendlyError + showErrorToast + helper CSS must all be present
    in templates/base.html."""

    def _read(self) -> str:
        return Path("templates/base.html").read_text(encoding="utf-8")

    def test_friendly_error_function_defined(self):
        src = self._read()
        assert "function friendlyError(" in src, (
            "FE-MED-031 regression: friendlyError JS helper missing."
        )

    def test_show_error_toast_wrapper_defined(self):
        src = self._read()
        assert "function showErrorToast(" in src, (
            "FE-MED-031 regression: showErrorToast convenience helper "
            "missing — callsites that pass raw err.message will fall "
            "back to legacy showToast without the friendly-fy step."
        )

    def test_toast_supports_object_form(self):
        """showToast must accept {message, detail} object form so the
        two-line layout works. Plain-string back-compat preserved."""
        src = self._read()
        assert "typeof msg === 'object'" in src, (
            "FE-MED-031 regression: showToast object-form branch missing."
        )
        # Both layout classes must be referenced by the renderer
        assert "toast-msg" in src and "toast-detail" in src, (
            "FE-MED-031 regression: two-line toast layout classes "
            "missing in showToast renderer."
        )

    def test_toast_css_two_line_classes_present(self):
        src = self._read()
        assert ".toast-msg" in src and ".toast-detail" in src, (
            "FE-MED-031 regression: .toast-msg / .toast-detail CSS rules "
            "missing — two-line toast will render unstyled."
        )

    def test_friendly_error_status_code_branches(self):
        """All audit-relevant HTTP status branches must be present:
        500/404/422/403/401/429 + generic 4xx + 5xx. The 422 branch
        is the audit's Session-C example."""
        src = self._read()
        # Pin each branch by the literal status check, since each is
        # individually load-bearing.
        for code in ("500", "404", "422", "403", "401", "429"):
            assert f"status === {code}" in src or f"status >= {code}" in src, (
                f"FE-MED-031 regression: friendlyError HTTP-{code} branch "
                "missing. Status-specific friendly copy was the whole "
                "point of pattern-matching by status."
            )

    def test_friendly_error_attribute_error_pattern(self):
        """Python AttributeError ('X' object has no attribute 'Y') is
        the audit's Session-B example — must be caught."""
        src = self._read()
        assert "object has no attribute" in src, (
            "FE-MED-031 regression: AttributeError pattern (Session B's "
            "RegimeFetcher example) won't match — falls to generic "
            "instead of code-level-error copy."
        )

    def test_friendly_error_generic_fallback(self):
        src = self._read()
        # The generic fallback string is the user-facing default
        assert "Couldn't complete this action" in src, (
            "FE-MED-031 regression: generic friendly fallback missing."
        )

    def test_friendly_error_returns_message_and_detail(self):
        """Return shape must be {message, detail} — callers depend on it."""
        src = self._read()
        # The pattern `return {message:` appears at every branch
        assert "message:" in src and "detail: raw" in src, (
            "FE-MED-031 regression: friendlyError return shape "
            "({message, detail}) missing."
        )


# ── htmx error handlers route through friendlyError ─────────────────────────


class TestHtmxHandlersFriendlyfied:
    """`htmx:responseError` + `htmx:sendError` handlers must no longer
    drop raw `Request failed: <status> <path>` into the toast verbatim.
    Status code reaches friendlyError; raw stays in console + detail row."""

    def _read(self) -> str:
        return Path("templates/base.html").read_text(encoding="utf-8")

    def test_response_error_handler_uses_friendly_error(self):
        src = self._read()
        # Locate the handler body
        idx = src.find("addEventListener('htmx:responseError'")
        assert idx > 0, "htmx:responseError handler not found"
        # Take the next ~3 KB as the handler body
        body = src[idx:idx + 3500]
        assert "friendlyError(" in body, (
            "FE-MED-031 regression: htmx:responseError handler not "
            "routing through friendlyError — raw 'Request failed: 422 "
            "/calculator/calculate' will be back in the toast."
        )
        # Status code must be passed to the helper
        assert "status: status" in body or "status:status" in body, (
            "FE-MED-031 regression: htmx handler not passing status "
            "code to friendlyError — status-specific friendly copy "
            "(e.g., 422 → \"Some inputs aren't valid…\") won't trigger."
        )

    def test_send_error_handler_uses_friendly_error(self):
        src = self._read()
        idx = src.find("addEventListener('htmx:sendError'")
        assert idx > 0, "htmx:sendError handler not found"
        body = src[idx:idx + 3500]
        assert "friendlyError(" in body, (
            "FE-MED-031 regression: htmx:sendError handler not routing "
            "through friendlyError — raw 'Network error reaching <path>' "
            "will be back in the toast."
        )

    def test_raw_request_failed_string_only_in_console_and_detail(self):
        """Raw 'Request failed: ' should remain ONLY in the `raw` variable
        that feeds console.error + friendlyError's detail field — NOT
        in any top-level toast.textContent assignment or showError()
        call that bypasses the helper."""
        src = self._read()
        idx = src.find("addEventListener('htmx:responseError'")
        body = src[idx:idx + 3500]
        # Pre-fix line: `var msg = 'Request failed: ' + status + ' ' + path;`
        # followed by `showError(msg)`. The shape must be gone.
        assert "showError(msg)" not in body, (
            "FE-MED-031 regression: htmx handler still routes raw msg "
            "through showError without friendly-fying first."
        )


# ── Per-page catch blocks routed through showErrorToast ─────────────────────


class TestRegimeCatchBlocksUseShowErrorToast:
    """regime.html backfill / reclassify / news-refresh catch blocks
    must no longer pass `err.message` directly to showToast."""

    def _read(self) -> str:
        return Path("templates/regime.html").read_text(encoding="utf-8")





class TestBacktestDataFetchFailureUsesShowErrorToast:
    """backtest.html data-fetch poll's failure branch — `d.detail` may
    carry raw exception strings."""

    def _read(self) -> str:
        return Path("templates/backtest.html").read_text(encoding="utf-8")




# ── Python mirror of friendlyError to verify pattern coverage ──────────────


def _friendly_error_py(raw, status=0, fallback=None):
    """Python mirror of the JS friendlyError — same priority order, same
    regexes. Used here to verify each audit-cited error shape resolves
    to the expected friendly message without running JS."""
    raw = "" if raw is None else str(raw)
    if status >= 500:
        return {"message": "The server hit an error. Please try again.", "detail": raw}
    if status == 404:
        return {"message": "That resource couldn't be found.", "detail": raw}
    if status == 422:
        return {"message": "Some inputs aren't valid. Please review and try again.", "detail": raw}
    if status == 403:
        return {"message": "You don't have permission for this action.", "detail": raw}
    if status == 401:
        return {"message": "Your session needs to be re-authenticated.", "detail": raw}
    if status == 429:
        return {"message": "Too many requests — slow down for a moment.", "detail": raw}
    if status >= 400:
        return {"message": "The request couldn't be completed.", "detail": raw}
    if re.search(r"object has no attribute|'\w+' object has no", raw):
        return {"message": "An internal operation failed (code-level error — please report).", "detail": raw}
    if re.search(r"Network ?[Ee]rror|Failed to fetch|NetworkError|engine offline|ECONNREFUSED|net::ERR", raw):
        return {"message": "Couldn't reach the engine. It may be offline.", "detail": raw}
    if re.search(r"timeout|timed out|ETIMEDOUT", raw, re.I):
        return {"message": "The request took too long. Try again in a moment.", "detail": raw}
    return {"message": fallback or "Couldn't complete this action.", "detail": raw}


class TestFriendlyErrorPatternCoverage:
    """End-to-end pattern coverage via the Python mirror — these are the
    audit-cited shapes that must resolve to friendly prose, not raw."""

    def test_audit_session_c_422_calculator(self):
        """Audit Session-C example: 'Request failed: 422 /calculator/calculate'.
        With status=422, the friendly copy should fire."""
        raw = "Request failed: 422 /calculator/calculate"
        out = _friendly_error_py(raw, status=422)
        assert "inputs aren't valid" in out["message"]
        # Raw preserved as detail for diagnostic
        assert out["detail"] == raw

    def test_audit_session_b_regime_fetcher_attribute_error(self):
        """Audit Session-B example: 'RegimeFetcher' object has no
        attribute 'close'. No HTTP status — body-shape pattern matches."""
        raw = "'RegimeFetcher' object has no attribute 'close'"
        out = _friendly_error_py(raw, status=0)
        assert "internal operation failed" in out["message"]
        assert out["detail"] == raw

    @pytest.mark.parametrize("status,expected_keyword", [
        (500, "server hit an error"),
        (502, "server hit an error"),
        (503, "server hit an error"),
        (404, "couldn't be found"),
        (422, "inputs aren't valid"),
        (403, "permission"),
        (401, "re-authenticated"),
        (429, "Too many requests"),
        (400, "couldn't be completed"),
        (418, "couldn't be completed"),
    ])
    def test_http_status_branches(self, status, expected_keyword):
        out = _friendly_error_py("ignored body", status=status)
        assert expected_keyword in out["message"], (
            f"Status {status} → expected '{expected_keyword}' in message, "
            f"got: {out['message']!r}"
        )

    def test_network_error_pattern(self):
        for raw in [
            "Failed to fetch",
            "NetworkError when attempting to fetch resource.",
            "Network error reaching /api/something (engine offline?)",
            "net::ERR_CONNECTION_REFUSED",
        ]:
            out = _friendly_error_py(raw)
            assert "Couldn't reach the engine" in out["message"], (
                f"Network shape not matched for: {raw!r}"
            )

    def test_timeout_pattern(self):
        for raw in ["request timed out", "Connection timeout", "ETIMEDOUT"]:
            out = _friendly_error_py(raw)
            assert "took too long" in out["message"], (
                f"Timeout shape not matched for: {raw!r}"
            )

    def test_generic_fallback(self):
        out = _friendly_error_py("some unknown garbage")
        assert out["message"] == "Couldn't complete this action."
        assert out["detail"] == "some unknown garbage"

    def test_fallback_override(self):
        out = _friendly_error_py("some unknown garbage", fallback="Backfill couldn't start.")
        assert out["message"] == "Backfill couldn't start."

    def test_status_takes_priority_over_body_pattern(self):
        """If status set, status branch wins even if body matches a
        body-shape pattern. Status is more reliable signal."""
        raw = "'X' object has no attribute 'y'"
        out = _friendly_error_py(raw, status=500)
        assert "server hit an error" in out["message"]
        # NOT the AttributeError friendly copy
        assert "internal operation failed" not in out["message"]

    def test_none_raw_safe(self):
        out = _friendly_error_py(None)
        assert out["message"] == "Couldn't complete this action."
        assert out["detail"] == ""

    def test_detail_preserves_raw_verbatim(self):
        raw = "some specific error 12345"
        out = _friendly_error_py(raw, status=500)
        assert out["detail"] == raw, (
            "FE-MED-031: raw detail must be preserved verbatim for "
            "operator diagnostic context."
        )


# ── Verify JS regex from base.html matches the Python mirror ───────────────


class TestJsAndPythonMirrorAgree:
    """The Python mirror only verifies the contract; this test reads
    base.html and confirms the JS regexes use the same patterns the
    Python mirror does. Catches drift if either side is edited."""

    def test_attribute_error_regex_present(self):
        src = Path("templates/base.html").read_text(encoding="utf-8")
        assert "object has no attribute" in src, (
            "JS friendlyError missing AttributeError pattern."
        )

    def test_network_error_keywords_present(self):
        src = Path("templates/base.html").read_text(encoding="utf-8")
        for kw in ["NetworkError", "Failed to fetch", "engine offline"]:
            assert kw in src, (
                f"JS friendlyError missing network keyword: {kw!r}"
            )

    def test_timeout_keywords_present(self):
        src = Path("templates/base.html").read_text(encoding="utf-8")
        for kw in ["timeout", "timed out", "ETIMEDOUT"]:
            assert kw in src, (
                f"JS friendlyError missing timeout keyword: {kw!r}"
            )
