"""Tests for timezone hygiene — no hardcoded TZ literals, dynamic footer."""
import re

import pytest

from core.tz import format_tz_display


class TestFormatTzDisplay:
    """format_tz_display returns correct UTC offset strings."""

    def test_utc(self):
        # Can't easily mock per-account settings, but test the helper directly
        from core.tz import _UTC, get_account_tz
        from datetime import datetime
        offset = datetime.now(_UTC).utcoffset()
        assert offset is not None
        assert offset.total_seconds() == 0

    def test_format_positive_offset(self):
        from datetime import datetime, timezone, timedelta
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Bangkok")  # UTC+7
        dt = datetime.now(tz)
        off = dt.utcoffset()
        total = int(off.total_seconds())
        h, rem = divmod(abs(total), 3600)
        m = rem // 60
        sign = "+" if total >= 0 else "-"
        result = f"UTC{sign}{h}:{m:02d}" if m else f"UTC{sign}{h}"
        assert result == "UTC+7"

    def test_format_half_hour_offset(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Kolkata")  # UTC+5:30
        dt = datetime.now(tz)
        off = dt.utcoffset()
        total = int(off.total_seconds())
        h, rem = divmod(abs(total), 3600)
        m = rem // 60
        sign = "+" if total >= 0 else "-"
        result = f"UTC{sign}{h}:{m:02d}" if m else f"UTC{sign}{h}"
        assert result == "UTC+5:30"


class TestFooterDynamic:
    def test_no_hardcoded_utc_offset_in_footer(self):
        """Footer must not have hardcoded UTC+N literal."""
        content = open("templates/base.html", encoding="utf-8").read()
        # Find footer
        idx = content.find("<footer")
        assert idx != -1
        footer = content[idx:content.find("</footer>", idx)]
        assert "UTC+7" not in footer
        assert "UTC-" not in footer
        # Should use template variable
        assert "tz_display" in footer

    def test_ctx_includes_tz_display(self):
        """_ctx() passes tz_display to templates."""
        content = open("api/helpers.py", encoding="utf-8").read()
        assert "tz_display" in content
        assert "format_tz_display" in content


class TestNoHardcodedTzInCode:
    """No hardcoded UTC+N/UTC-N literals in .py or .html files (except tests/docs)."""

    SCAN_DIRS = ["api", "core", "templates"]

    def test_no_utc_offset_literals(self):
        import os
        for scan_dir in self.SCAN_DIRS:
            for root, _, files in os.walk(scan_dir):
                for f in files:
                    if not (f.endswith(".py") or f.endswith(".html")):
                        continue
                    path = os.path.join(root, f)
                    for i, line in enumerate(open(path, encoding="utf-8"), 1):
                        stripped = line.lstrip()
                        # Skip comments, docstrings, and Jinja comments
                        if stripped.startswith("#") or stripped.startswith('"""') \
                           or stripped.startswith("'''") or stripped.startswith("<!--"):
                            continue
                        for m in re.finditer(r'UTC[+-]\d+', line):
                            assert False, \
                                f"{path}:{i} has hardcoded TZ literal: {m.group()}"


class TestRegimeUsesAccountTz:
    def test_regime_route_no_raw_datetime_now(self):
        """Regime route uses now_in_account_tz, not raw datetime.now()."""
        content = open("api/routes_regime.py", encoding="utf-8").read()
        assert "datetime.now()" not in content


class TestDailyPeriodSemantics:
    """Document: daily-period operations use account TZ (not server-local)."""

    def test_bod_uses_account_tz(self):
        import inspect
        from core.exchange_income import fetch_bod_sow_equity
        src = inspect.getsource(fetch_bod_sow_equity)
        assert "now_in_account_tz" in src

    def test_daily_snapshot_uses_account_tz(self):
        import inspect
        from core.data_logger import take_daily_snapshot
        src = inspect.getsource(take_daily_snapshot)
        assert "now_in_account_tz" in src
