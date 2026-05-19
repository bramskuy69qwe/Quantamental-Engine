"""
Task 131 regression tests — label & format polish bundle.

Four trivial findings resolved + 1 normalized to DEFERRED:
  - FE-MED-010: Dashboard "0/10.0" capacity badge — title tooltip.
  - FE-LOW-002: Account card name truncation — word-wrap + title.
  - FE-LOW-005: Provider names mix abbrev styles — Finnhub + CoinGecko
                gained parentheticals.
  - FE-LOW-009: Equity Curve "CF" / "Adj Chg" expanded to full
                "Cash Flow" / "Adjusted Change" (Task 112 convention).
  - FE-LOW-004: Status normalized to DEFERRED-PER-AUDIT-01 (no code
                work; audit-01 explicitly recommended defer-indefinitely).

Run: pytest tests/test_task131_label_polish.py -v
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import pytest


def _make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    env.globals["fmt"] = lambda v, n=2: (
        f"{v:.{n}f}" if isinstance(v, (int, float)) else str(v)
    )
    return env


# ── FE-MED-010: Dashboard capacity indicator tooltip ────────────────────────

class TestFeMed010CapacityIndicatorTooltip:

    def test_dashboard_body_has_title_tooltip(self):
        src = Path("templates/fragments/dashboard_body.html").read_text(encoding="utf-8")
        # The capacity indicator span carries the tooltip
        assert 'title="Open positions / max positions"' in src
        # Anchor for traceability
        assert "FE-MED-010" in src

    def test_dashboard_positions_has_title_tooltip(self):
        src = Path("templates/fragments/dashboard_positions.html").read_text(encoding="utf-8")
        assert 'title="Open positions / max positions"' in src
        # The data-max attr is still present (anchors the original span)
        assert 'data-max=' in src

    def test_capacity_indicator_tooltip_attr_paired_with_count(self):
        """Source-pin: the tooltip attribute lives on the same <span>
        as the `{{ open_positions | length }}/{{ max_open_positions }}`
        content. (Full render-pin would require the entire dashboard
        context which is heavy; the source-pin above already proves
        the wiring.)"""
        for path in (
            "templates/fragments/dashboard_body.html",
            "templates/fragments/dashboard_positions.html",
        ):
            src = Path(path).read_text(encoding="utf-8")
            # The capacity-indicator block contains both the tooltip
            # attr and the count expression. Find the tooltip line
            # and check the count is within ~200 chars after it.
            ti = src.find('title="Open positions / max positions"')
            assert ti > 0, f"tooltip missing in {path}"
            window = src[ti:ti + 300]
            assert "open_positions | length" in window


# ── FE-LOW-002: Account card name truncation ────────────────────────────────

class TestFeLow002AccountNameTruncation:

    def _read(self) -> str:
        return Path("templates/fragments/account_list.html").read_text(encoding="utf-8")

    def test_old_nowrap_ellipsis_pattern_gone(self):
        """Anti-revert: the prior nowrap + overflow:hidden + text-
        overflow:ellipsis combination is gone. Removing those three
        in tandem is what unlocks word-boundary wrapping."""
        src = self._read()
        old = 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
        assert old not in src

    def test_word_break_break_word_present(self):
        """The new wrap policy is `word-break:break-word` — covers
        single long words exceeding card width."""
        src = self._read()
        assert "word-break:break-word" in src

    def test_title_attribute_present_for_hover(self):
        src = self._read()
        # Tooltip shows the full account name regardless of wrap
        assert 'title="{{ acct.name }}"' in src

    def test_long_account_name_wraps_not_truncates(self):
        """End-to-end: long name renders without ellipsis. The
        rendered HTML doesn't carry text-overflow:ellipsis;"""
        env = _make_env()
        src = '{% include "fragments/account_list.html" %}'
        out = env.from_string(src).render(
            accounts=[{
                "id": 1, "name": "Account 1 (Binance Futures USD-M)",
                "exchange": "binance", "market_type": "future",
                "is_active": 1, "environment": "live",
            }],
            active_account_id=1,
        )
        # Full name present
        assert "Account 1 (Binance Futures USD-M)" in out
        # ellipsis style absent
        assert "text-overflow:ellipsis" not in out
        # Tooltip present
        assert 'title="Account 1 (Binance Futures USD-M)"' in out


# ── FE-LOW-005: Provider name parentheticals ────────────────────────────────

class TestFeLow005ProviderHints:

    def test_finnhub_has_parenthetical(self):
        from core.connections import KNOWN_PROVIDERS
        finnhub = next(p for p in KNOWN_PROVIDERS if p["provider"] == "finnhub")
        assert finnhub["label"] == "Finnhub (Equities)"

    def test_coingecko_has_parenthetical(self):
        from core.connections import KNOWN_PROVIDERS
        coingecko = next(p for p in KNOWN_PROVIDERS if p["provider"] == "coingecko")
        assert coingecko["label"] == "CoinGecko (Crypto)"

    def test_all_providers_have_parens(self):
        """Load-bearing: all 5 entries now carry a parenthetical hint —
        the audit's "all or none" consistency framing."""
        from core.connections import KNOWN_PROVIDERS
        for p in KNOWN_PROVIDERS:
            assert "(" in p["label"] and ")" in p["label"], (
                f"FE-LOW-005 regression: provider {p['provider']!r} has "
                f"no parenthetical hint in label {p['label']!r}."
            )

    def test_existing_three_providers_unchanged(self):
        """Anti-over-correction: the 3 already-parens'd providers are
        NOT rewritten. Task 131 minimal-invasive scope."""
        from core.connections import KNOWN_PROVIDERS
        by_provider = {p["provider"]: p["label"] for p in KNOWN_PROVIDERS}
        assert by_provider["binance_market_data"] == "Binance Market Data (OI/Funding)"
        assert by_provider["bwe_news"] == "BWE News (Crypto)"
        assert by_provider["fred"] == "Federal Reserve (FRED)"


# ── FE-LOW-009: CF / Adj Chg expanded to full labels ────────────────────────

class TestFeLow009LabelExpansion:

    def _read(self) -> str:
        return Path("templates/fragments/equity_ohlc.html").read_text(encoding="utf-8")

    def test_stats_line_uses_cash_flow_full_label(self):
        src = self._read()
        # Stats line (renderStats) expanded
        assert '">Cash Flow<' in src
        # Old abbreviation gone from the stats line (only "CF" left as a token)
        # — we look for the specific HTML fragment to be conservative
        assert '">CF</span>' not in src

    def test_stats_line_uses_adjusted_change_full_label(self):
        src = self._read()
        assert '">Adjusted Change<' in src
        assert '">Adj Chg</span>' not in src

    def test_tooltip_uses_consistent_full_labels(self):
        """The tooltip row() calls also use the full labels for
        consistency across stats line + tooltip."""
        src = self._read()
        # Old "Cashflow" → "Cash Flow"
        assert "row('Cashflow'" not in src
        assert "row('Cash Flow'" in src
        # Old "Adj Chg" → "Adjusted Change"
        assert "row('Adj Chg'" not in src
        assert "row('Adjusted Change'" in src


# ── FE-LOW-004: status normalization ────────────────────────────────────────

class TestFeLow004StatusNormalized:

    def test_audit_doc_marks_fe_low_004_deferred(self):
        src = Path("docs/audits/2026-05-17-v2.4-backend-audit.md").read_text(encoding="utf-8")
        # Locate the FE-LOW-004 entry
        idx = src.find("### [FE-LOW-004]")
        assert idx > 0
        # Look at the entry body (next ~600 chars)
        section = src[idx:idx + 800]
        # New status word
        assert "DEFERRED-PER-AUDIT-01" in section
        # Anti-revert: old plain "Status: OPEN" line is gone for FE-LOW-004
        # (the new status is "DEFERRED-PER-AUDIT-01", not "OPEN").
        # We can't grep for "Status: OPEN" alone because other findings use it.
        # Instead anchor that the FE-LOW-004 section specifically has DEFERRED.
        assert "Status: **DEFERRED-PER-AUDIT-01**" in section


# ── Compile pins (MED-047) ──────────────────────────────────────────────────

class TestTemplateCompiles:

    @pytest.mark.parametrize("path", [
        "fragments/dashboard_body.html",
        "fragments/dashboard_positions.html",
        "fragments/account_list.html",
        "fragments/equity_ohlc.html",
    ])
    def test_compiles(self, path):
        env = _make_env()
        tpl = env.get_template(path)
        assert tpl is not None
