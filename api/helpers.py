"""
Shared helpers for all API route modules.

Pure formatting and template utilities — no mutable state.
Caching state lives in api/cache.py.

Exports: templates, _fmt, _fmt_duration, _hold_time, _ctx, _paginate_list, _table_ctx
"""
from __future__ import annotations

import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Request
from fastapi.templating import Jinja2Templates

import config
from core.state import app_state
from core.tz import get_account_tz, now_in_account_tz, format_tz_display
from core.account_registry import account_registry
from core.formatters import format_price as _fmt_price, format_size as _fmt_size


def _tz_display() -> str:
    """Current account timezone display string, e.g. 'UTC+7'."""
    try:
        return format_tz_display(app_state.active_account_id)
    except Exception:
        return "UTC"

# ── Templates ────────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BASE_DIR, "templates"))


def _fmt(val, decimals=2, suffix=""):
    try:
        f = float(val)
    except (TypeError, ValueError):
        return str(val)
    # Phase 8 audit: a NaN/Inf mark (bad WS tick) would otherwise render the
    # literal "nan"/"inf" in uPnL/MFE/MAE cells AND skip the green/red sign
    # class (nan>0 and nan<0 are both False). Render the em-dash sentinel.
    if not math.isfinite(f):
        return "—"
    return f"{f:,.{decimals}f}{suffix}"


def _fmt_duration(ms) -> str:
    """Format a millisecond duration as a compact hold-time string."""
    try:
        total_s = max(0, int(float(ms)) // 1000)
    except (TypeError, ValueError):
        return "—"
    d = total_s // 86400
    h = (total_s % 86400) // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    parts = []
    if d:
        parts.append(f"{d}d")
    if d or h:
        parts.append(f"{h:02d}h")
    if d or h or m:
        parts.append(f"{m:02d}m")
    parts.append(f"{s:02d}s")
    return " ".join(parts)


def _hold_time(entry_iso: str) -> str:
    """Compact hold time from ISO entry_timestamp to now."""
    if not entry_iso:
        return "—"
    try:
        from datetime import timezone as _tz
        entry = datetime.fromisoformat(entry_iso)
        if entry.tzinfo is None:
            entry = entry.replace(tzinfo=_tz.utc)
        delta_s = max(0, int((datetime.now(_tz.utc) - entry).total_seconds()))
        d = delta_s // 86400
        h = (delta_s % 86400) // 3600
        m = (delta_s % 3600) // 60
        s = delta_s % 60
        parts = []
        if d:
            parts.append(f"{d}d")
        if d or h:
            parts.append(f"{h:02d}h")
        parts.append(f"{m:02d}m")
        parts.append(f"{s:02d}s")
        return " ".join(parts)
    except Exception:
        return "—"


def _ms_to_local(ms: int) -> str:
    """Convert epoch-ms to local datetime string for display."""
    if not ms:
        return "—"
    try:
        dt = datetime.fromtimestamp(ms / 1000, tz=get_account_tz(app_state.active_account_id))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "—"


templates.env.globals["fmt"] = _fmt
templates.env.globals["fmt_price"] = _fmt_price
templates.env.globals["fmt_size"] = _fmt_size
templates.env.globals["fmt_duration"] = _fmt_duration
templates.env.globals["hold_time"] = _hold_time
templates.env.globals["ms_to_local"] = _ms_to_local
templates.env.globals["project_name"] = config.PROJECT_NAME
templates.env.globals["project_name_"] = config.PROJECT_NAME_
templates.env.globals["project_version_"] = config.PROJECT_VERSION_


def _ctx(request: Request, **extra) -> dict:
    """Base template context for every page render."""
    # FE-HIGH-002 (Task 111): expose the registered REST adapters to every
    # template render. The Add Account modal in base.html iterates this list
    # so non-Binance adapters appear with a "(Beta)" suffix on the label.
    from core.adapters.registry import list_rest_exchanges
    return {
        "now":               now_in_account_tz(app_state.active_account_id).strftime("%Y-%m-%d %H:%M:%S"),
        "tz_display":        _tz_display(),
        "ws_status":         app_state.ws_status,
        "params":            app_state.params,
        "is_initializing":   app_state.is_initializing,
        "active_account_id": app_state.active_account_id,
        "accounts":          account_registry.list_accounts_sync(),
        "available_exchanges": list_rest_exchanges(),
        **extra,
    }


def _paginate_list(
    data: List[Dict[str, Any]],
    page: int,
    per_page: int,
    sort_key: str,
    sort_dir: str,
    search: str = "",
    search_fields: tuple = ("symbol", "ticker"),
    filters: Optional[Dict[str, str]] = None,
) -> tuple:
    """In-memory pagination/sort/filter for list-backed tables."""
    if search:
        term = search.lower()
        data = [r for r in data if any(
            term in str(r.get(f, "")).lower() for f in search_fields
        )]
    if filters:
        for col, val in filters.items():
            if val:
                data = [r for r in data if str(r.get(col, "")).lower() == val.lower()]
    reverse = sort_dir.upper() == "DESC"

    def _key(r):
        v = r.get(sort_key, "")
        try:
            return (0, float(v))
        except (ValueError, TypeError):
            return (1, str(v).lower() if v is not None else "")

    try:
        data = sorted(data, key=_key, reverse=reverse)
    except TypeError:
        pass
    total = len(data)
    offset = (max(page, 1) - 1) * per_page
    return data[offset:offset + per_page], total


def _table_ctx(request, **kw):
    """Minimal context for table fragments — no full _ctx overhead needed."""
    return {**kw}
