"""Closed-position audit export (Phase 7.4, spec §10.6 / §11.2 / §68).

Builds a self-contained, tamper-evident JSON audit bundle for one closed
position: the full causal graph (reusing the Phase-7.2 reverse-query assembler)
wrapped in a signed-timestamp envelope.

``POST /export/closed_position/{id}`` resolves the closed_positions row by its
integer PK → its ``terminal_position_id`` → :func:`assemble_position_context`
(so the bundle carries calc(s), orders, fills, amendments, junction, the closed
rows, funding, deviations, and the event timeline — §10.6's "full graph per
closed position"). The envelope adds a ``generated_at`` timestamp and a
``signature`` over canonical(header + bundle): HMAC-SHA256 when
``config.EXPORT_SIGNING_KEY`` is set (authenticity), else an unkeyed SHA-256
content digest (tamper-evidence — the localhost single-tenant default; the
threat model is silent data drift, not external forgery, per CLAUDE.md Task 163).

PDF rendering is Phase 7.5; this is JSON-only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import config
from core.context_query import (
    assemble_lifecycle_context,
    assemble_position_context,
    json_safe,
)

log = logging.getLogger("audit_export")

EXPORT_SCHEMA_VERSION = 1


def _canonical(obj: Any) -> str:
    """Deterministic JSON for signing: sorted keys, no whitespace. The bundle is
    pre-``json_safe``'d (no NaN/Infinity); ``default=str`` covers any stray
    non-serializable value so signing never raises.

    A verifier MUST re-canonicalize the PARSED ``{"header": <export minus
    signature/signature_algo>, "bundle": <bundle>}`` with these same rules and
    recompute the signature — it must NOT hash the raw response body bytes
    (Starlette serves with ``ensure_ascii=False`` while this signs the
    transport-independent canonical form; the two differ only on the wire for
    non-ASCII, and parse-then-canonicalize reconciles them)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sign(canonical_payload: str) -> Tuple[str, str]:
    """Return ``(algo, hex_signature)`` over ``canonical_payload`` —
    ``hmac-sha256`` when a signing key is configured, else unkeyed ``sha256``."""
    data = canonical_payload.encode("utf-8")
    key = config.EXPORT_SIGNING_KEY
    if key:
        return "hmac-sha256", hmac.new(key.encode("utf-8"), data, hashlib.sha256).hexdigest()
    return "sha256", hashlib.sha256(data).hexdigest()


async def build_closed_position_export(
    db: Any, closed_position_id: int,
) -> Optional[Dict[str, Any]]:
    """Assemble the signed audit envelope for one closed_positions row (by PK).
    Returns ``None`` if the row does not exist (→ 404).

    Bundle resolution: the position graph by ``terminal_position_id``; falling
    back to the lifecycle graph (if the row carries a ``lifecycle_id`` but no
    tpid — observe-only path); falling back to a closed-row-only degenerate
    bundle when neither is assemblable (so a valid id ALWAYS exports something).
    """
    row = await db.get_closed_position_by_id(closed_position_id)
    if row is None:
        return None

    tpid = row.get("terminal_position_id") or ""
    lifecycle_id = row.get("lifecycle_id") or ""
    account_id = row.get("account_id")

    bundle: Optional[Dict[str, Any]] = None
    bundle_kind: str
    if tpid:
        bundle = await assemble_position_context(db, tpid)
        bundle_kind = "position"
    if bundle is None and lifecycle_id:
        bundle = await assemble_lifecycle_context(db, lifecycle_id)
        bundle_kind = "lifecycle"
    if bundle is None:
        # Degenerate: empty-tpid / no-junction closed row (binance observe-only)
        # → the causal graph can't be assembled by key; export the closed row
        # itself so a valid id still yields a (clearly-flagged) bundle.
        bundle = {
            "closed_positions": [row],
            "note": "position graph unavailable (no terminal_position_id / "
                    "lifecycle_id — observe-only path); closed row only",
        }
        bundle_kind = "closed_row_only"

    bundle = json_safe(bundle)
    header = {
        "kind": "closed_position_audit",
        "schema_version": EXPORT_SCHEMA_VERSION,
        "closed_position_id": closed_position_id,
        "position_id": tpid or None,
        "lifecycle_id": lifecycle_id or None,
        "account_id": account_id,
        "bundle_kind": bundle_kind,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    algo, signature = _sign(_canonical({"header": header, "bundle": bundle}))
    return {
        "export": {**header, "signature_algo": algo, "signature": signature},
        "bundle": bundle,
    }


# ── PDF rendering (P7.T5) ─────────────────────────────────────────────────────

# (bundle list key, section label, the per-row fields to summarise)
_PDF_SECTIONS = (
    ("calcs",            "CALCS",          ("calc_id", "ticker", "model_name")),
    ("orders",           "ORDERS",         ("exchange_order_id", "order_type", "status", "calc_id")),
    ("fills",            "FILLS",          ("exchange_fill_id", "price", "quantity", "is_close")),
    ("amendments",       "AMENDMENTS",     ("field", "old_value", "new_value", "ts_ms")),
    ("positions_calcs",  "JUNCTION",       ("calc_id", "contributed_qty", "first_fill_ts")),
    ("funding_events",   "FUNDING",        ("amount", "ts_ms", "venue_event_id")),
    ("closed_positions", "CLOSED ROWS",    ("exit_time_ms", "realized_pnl", "net_pnl", "exit_reason")),
    ("events",           "EVENT TIMELINE", ("timestamp", "event_type")),
)
_PDF_POSITION_FIELDS = (
    "terminal_position_id", "symbol", "direction", "entry_price", "exit_price",
    "realized_pnl", "total_fees", "funding_fees", "net_pnl", "exit_reason",
)


def _export_text_lines(envelope: Dict[str, Any]) -> list:
    """Flatten the signed export envelope into a human-readable text report
    (the source for :func:`render_export_pdf`). Tolerant of the three bundle
    shapes (position / lifecycle / closed_row_only) — sections absent from a
    given bundle are simply skipped."""
    exp = envelope.get("export", {})
    bundle = envelope.get("bundle", {})
    L: list = []
    bar = "=" * 78
    L += [bar, "CLOSED-POSITION AUDIT EXPORT", bar]
    for k in ("kind", "schema_version", "closed_position_id", "position_id",
              "lifecycle_id", "account_id", "bundle_kind", "generated_at"):
        if k in exp:
            L.append(f"{k:>20}: {exp[k]}")
    L.append("")

    dev = bundle.get("deviations") or {}
    if dev:
        L.append("-- DEVIATIONS " + "-" * 60)
        L += [f"{k:>26}: {v}" for k, v in dev.items()]
        L.append("")

    pos = bundle.get("position")
    if isinstance(pos, dict):
        L.append(f"-- POSITION ({bundle.get('position_state')}) " + "-" * 50)
        L += [f"{k:>26}: {pos[k]}" for k in _PDF_POSITION_FIELDS if k in pos]
        L.append("")

    for key, label, row_keys in _PDF_SECTIONS:
        rows = bundle.get(key)
        if not isinstance(rows, list):
            continue
        L.append(f"-- {label} ({len(rows)}) " + "-" * max(0, 60 - len(label)))
        for r in rows:
            if isinstance(r, dict):
                parts = [f"{rk}={r.get(rk)}" for rk in row_keys if rk in r]
                L.append("  " + ("  ".join(parts) if parts else str(r)))
        L.append("")

    L += [bar, "SIGNED — tamper-evidence over canonical(header + bundle)"]
    L.append(f"  algo:      {exp.get('signature_algo')}")
    L.append(f"  generated: {exp.get('generated_at')}")
    L.append(f"  signature: {exp.get('signature')}")
    L.append("  verify: re-canonicalize {header, bundle} from the JSON export "
             "(POST ?format=json) and recompute")
    L.append(bar)
    return L


def render_export_pdf(envelope: Dict[str, Any]) -> bytes:
    """Render the signed export envelope to a paginated text PDF (bytes). The
    PDF carries the SAME signature as the JSON export (computed once over the
    canonical bundle) in a footer block."""
    from core.pdf_writer import text_pdf
    return text_pdf(_export_text_lines(envelope))
