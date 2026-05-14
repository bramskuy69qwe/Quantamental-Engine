"""
State-machine test harness for dd_state behavioral fixtures.

Replays synthetic equity-curve CSVs through a pluggable evaluator and
checks expected state at fixture-defined checkpoints.  Runs entirely
in-memory — no DB writes, no engine_events persistence.

Fixture CSV format
------------------
Three sections delimited by header lines:

    # equity
    timestamp,equity
    2026-01-01T00:00:00+00:00,10000.0
    ...

    # checkpoints
    timestamp,expected_state
    2026-01-15T00:00:00+00:00,warning
    ...

    # overrides
    timestamp,override_type,payload_json
    2026-01-18T00:00:00+00:00,manual_override,{"reason":"tilt recovery"}
    ...

The ``# overrides`` section is optional.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.test_clock import TestClock


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class Fixture:
    equity_series: List[Tuple[datetime, float]]
    checkpoints: List[Tuple[datetime, str]]  # (timestamp, expected_state)
    overrides: List[Tuple[datetime, str, Dict[str, Any]]]  # (ts, type, payload)


@dataclass
class RunResult:
    transitions: List[Tuple[datetime, str, str]] = field(default_factory=list)
    final_state: str = "ok"
    checkpoint_failures: List[str] = field(default_factory=list)
    override_events: List[Tuple[datetime, str, Dict[str, Any]]] = field(
        default_factory=list
    )


# ── Fixture loader ───────────────────────────────────────────────────────────


def _parse_dt(s: str) -> datetime:
    """Parse ISO-8601 timestamp, default to UTC if naive."""
    dt = datetime.fromisoformat(s.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_fixture(path: Path) -> Fixture:
    """Parse a fixture CSV into a ``Fixture`` dataclass.

    Raises ``ValueError`` with line context on malformed input.
    """
    text = path.read_text(encoding="utf-8")
    section: Optional[str] = None
    equity: List[Tuple[datetime, float]] = []
    checkpoints: List[Tuple[datetime, str]] = []
    overrides: List[Tuple[datetime, str, Dict[str, Any]]] = []

    for lineno, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("timestamp,"):
            continue  # skip blank lines and CSV headers

        if line.startswith("# "):
            section = line[2:].strip().lower()
            if section not in ("equity", "checkpoints", "overrides"):
                raise ValueError(
                    f"{path}:{lineno}: unknown section '# {section}'"
                )
            continue

        if section is None:
            raise ValueError(
                f"{path}:{lineno}: data before first section header"
            )

        parts = list(csv.reader(io.StringIO(line)))[0]

        try:
            if section == "equity":
                if len(parts) < 2:
                    raise ValueError("need timestamp,equity")
                equity.append((_parse_dt(parts[0]), float(parts[1])))

            elif section == "checkpoints":
                if len(parts) < 2:
                    raise ValueError("need timestamp,expected_state")
                checkpoints.append((_parse_dt(parts[0]), parts[1].strip()))

            elif section == "overrides":
                if len(parts) < 3:
                    raise ValueError(
                        "need timestamp,override_type,payload_json"
                    )
                payload = json.loads(parts[2])
                overrides.append((_parse_dt(parts[0]), parts[1].strip(), payload))

        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path}:{lineno}: {exc}") from exc

    if not equity:
        raise ValueError(f"{path}: no equity data found")

    return Fixture(
        equity_series=equity, checkpoints=checkpoints, overrides=overrides
    )


# ── Runner ───────────────────────────────────────────────────────────────────

# Evaluator signature: (current_state, equity, clock) -> new_state
Evaluator = Callable[[str, float, TestClock], str]


def run(fixture: Fixture, evaluator: Evaluator, clock: TestClock) -> RunResult:
    """Replay *fixture* through *evaluator*, checking checkpoints.

    The evaluator receives ``(current_state, equity_value, clock)`` and
    returns the new state string.  The clock is set to each equity tick's
    timestamp before calling the evaluator.
    """
    result = RunResult()
    state = "ok"

    # Build lookup maps for O(1) checkpoint/override matching
    checkpoint_map: Dict[datetime, str] = {ts: s for ts, s in fixture.checkpoints}
    # Overrides keyed by timestamp; multiple overrides at same ts supported
    override_map: Dict[datetime, List[Tuple[str, Dict[str, Any]]]] = {}
    for ts, otype, payload in fixture.overrides:
        override_map.setdefault(ts, []).append((otype, payload))

    for ts, equity in fixture.equity_series:
        clock.set(ts)

        # Dispatch overrides BEFORE evaluation (override changes state context)
        if ts in override_map:
            for otype, payload in override_map[ts]:
                result.override_events.append((ts, otype, payload))

        new_state = evaluator(state, equity, clock)

        if new_state != state:
            result.transitions.append((ts, state, new_state))
            state = new_state

        # Check checkpoint
        if ts in checkpoint_map:
            expected = checkpoint_map[ts]
            if state != expected:
                result.checkpoint_failures.append(
                    f"@{ts.isoformat()}: expected '{expected}', got '{state}'"
                )

    result.final_state = state
    return result
