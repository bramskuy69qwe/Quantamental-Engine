"""Process-wide ``OrderManager`` singleton (v2.6 Phase 1 extraction).

Before v2.6 the single production ``OrderManager`` was constructed inside
``core.platform_bridge.PlatformBridge.__init__``. The Quantower-plugin removal
(``docs/design/v2.6_remove_quantower_plugin_plan.md``) hoists it here so the
``OrderManager`` — which holds the live in-memory ``open_orders`` /
``_position_primary_calc`` state and MUST be a single process-wide instance
(v2.6 plan landmine L1) — no longer depends on the bridge. The bridge itself
was deleted in v2.6 Phase 5; this module is now the sole construction site.

Imports only ``core.database`` + ``core.order_manager``. ``OrderManager.__init__``
takes only ``db`` and constructs its ``PositionIdentity`` owner internally.

Usage — import the MODULE, resolve the attribute at CALL time::

    from core import order_manager_singleton
    ...
    order_manager_singleton.order_manager.process_order_update(...)

Do NOT write ``from core.order_manager_singleton import order_manager`` at
module scope. That binds the instance into the consumer's namespace at import
time, so the ONE documented test seam —
``patch("core.order_manager_singleton.order_manager", fake)`` — rebinds only
this module's attribute and never reaches that consumer: the test passes while
the real OrderManager runs against the real DB (a false green). The attribute
form above resolves through this module on every call, so the patch always
lands. A function-level ``from``-import is equivalent (it re-resolves per call)
and is what ``ws_manager`` / ``exchange`` / ``routes_history`` use; the
module-import form is preferred where the consumer already imports other
``core`` modules that way. Pinned by ``tests/test_order_manager_singleton_seam.py``.

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
