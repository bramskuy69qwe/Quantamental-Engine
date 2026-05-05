"""
Credential audit logger — writes lifecycle events to data/logs/audit.jsonl.

Never logs plaintext credentials. Only logs: timestamp, action, entity.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("audit")

_AUDIT_PATH = Path("data/logs/audit.jsonl")


def _ensure_dir() -> None:
    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)


def log_event(action: str, entity_type: str, entity_name: str, detail: str = "") -> None:
    """Append a single audit event to audit.jsonl.

    Args:
        action: "add", "update", "delete", "activate"
        entity_type: "account" or "connection"
        entity_name: account name or provider name (never a secret)
        detail: optional context (e.g. "credentials_changed")
    """
    _ensure_dir()
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": action,
        "entity_type": entity_type,
        "entity_name": entity_name,
    }
    if detail:
        entry["detail"] = detail
    try:
        with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        log.warning("Failed to write audit log: %s", e)
