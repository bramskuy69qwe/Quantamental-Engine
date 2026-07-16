"""
BacktestAdapter contract (v2.7 Phase 2).

One adapter per external app, registered via
``@register_backtest_adapter("<app_id>")`` (registry.py). Adapters are
stateless: ``parse(file_bytes, filename)`` -> NormalizedBacktestResult.

Tolerance contract (plan task 2.2): default missing FIELDS (renamed /
reordered / absent columns and labels must not crash — fall back to the
dataclass defaults); raise ``BacktestAdapterError`` ONLY when the file
is unrecognizable for this adapter (wrong format, none of the expected
data present). "Unrecognizable" is the loud path; "sparse" is not.
"""
from __future__ import annotations

from typing import Protocol, Tuple, runtime_checkable

from core.backtest_adapters.protocols import NormalizedBacktestResult


class BacktestAdapterError(ValueError):
    """File is unrecognizable for this adapter (not a sparse-fields case).

    Phase 3's upload route maps this to the 200 error-styled fragment.
    """


@runtime_checkable
class BacktestAdapter(Protocol):
    """Structural interface every backtest-import adapter satisfies."""

    app_id: str
    display_name: str
    accepted_extensions: Tuple[str, ...]

    def parse(self, file_bytes: bytes, filename: str) -> NormalizedBacktestResult:
        """Parse a raw uploaded report into the normalized shape.

        Raises BacktestAdapterError when the bytes are not a report this
        adapter recognizes.
        """
        ...
