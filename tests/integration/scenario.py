"""
Scenario-based integration test types.

Scenarios describe a sequence of synthetic exchange events replayed
through the real order_manager ingest paths against an ephemeral DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass
class ScenarioEvent:
    t_ms: int
    type: Literal[
        "calc_created", "order_persisted", "fill_received",
        "order_modified", "order_canceled",
    ]
    payload: Dict[str, Any]


@dataclass
class ExpectedFill:
    fill_id: str
    calc_id: Optional[str] = None   # "*" matches any non-NULL
    fill_type: str = ""
    slippage_actual: Optional[float] = None
    slippage_tolerance: float = 1e-6


@dataclass
class ExpectedOrder:
    exchange_order_id: str
    calc_id: Optional[str] = None   # "*" matches any non-NULL
    tp_trigger_price: Optional[float] = None
    sl_trigger_price: Optional[float] = None


@dataclass
class ExpectedEvent:
    type: str
    payload_includes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExpectedState:
    fills: List[ExpectedFill] = field(default_factory=list)
    orders: List[ExpectedOrder] = field(default_factory=list)
    trade_events: List[ExpectedEvent] = field(default_factory=list)


@dataclass
class Scenario:
    name: str
    description: str
    events: List[ScenarioEvent]
    expected: ExpectedState
