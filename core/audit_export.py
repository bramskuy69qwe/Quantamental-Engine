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
