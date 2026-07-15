"""Process-wide ``OrderManager`` singleton (v2.6 Phase 1 extraction).

Before v2.6 the single production ``OrderManager`` was constructed inside
``core.platform_bridge.PlatformBridge.__init__``. The Quantower-plugin removal
(``docs/design/v2.6_remove_quantower_plugin_plan.md``) hoists it here so the
``OrderManager`` — which holds the live in-memory ``open_orders`` /
``_position_primary_calc`` state and MUST be a single process-wide instance
(v2.6 plan landmine L1) — no longer depends on the bridge. ``platform_bridge``
now consumes this shared instance rather than building its own.

Imports only ``core.database`` + ``core.order_manager``; neither references
``platform_bridge`` at runtime (v2.6 plan §2 verified), so importing this
module can never create an import cycle with the bridge. ``OrderManager.__init__``
takes only ``db`` and constructs its ``PositionIdentity`` owner internally.

Usage::

    from core.order_manager_singleton import order_manager

NB the deliberate throwaway ``OrderManager(db)`` in ``core.link_actions`` (the
LB-F1 junction-replay) is NOT a second live instance in the L1 sense — it is a
stateless DB replay that never holds the live order/position cache. Consumers
that need the live cache read THIS ``order_manager``.
"""
from __future__ import annotations

from core.database import db
from core.order_manager import OrderManager

# THE process-wide OrderManager instance.
order_manager: OrderManager = OrderManager(db)
