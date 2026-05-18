"""
SQL identifier safety helpers — column/direction whitelist enforcement.

HIGH-011 / MED-003 / MED-022 (Task 101): SQL placeholders parameterize
*values*, never identifiers. ORDER BY column names, WHERE filter column
names, and ASC/DESC tokens must be whitelisted at the boundary that
accepts user input — typically the FastAPI route handler.

Use ``validate_sort_params`` at the top of each route handler that accepts
sort_by / sort_dir from the request. Raising HTTPException(400) fails fast
and visibly, instead of silently falling back to a default (the current
DB-layer behavior) which can mask abuse / mistakes.

Defense-in-depth: the DB-layer mixins also whitelist (silent fallback) so
that an internal caller bypassing the route still cannot inject. Route
validation gives the operator a visible 400 — DB validation is the safety
net.
"""
from __future__ import annotations

from typing import FrozenSet, Tuple

from fastapi import HTTPException


_ALLOWED_SORT_DIRS: FrozenSet[str] = frozenset({"ASC", "DESC"})


def validate_sort_params(
    sort_by: str,
    sort_dir: str,
    allowed_cols: FrozenSet[str] | set,
) -> Tuple[str, str]:
    """Validate route-supplied sort parameters; return the validated pair.

    Raises ``HTTPException(400)`` when ``sort_by`` is not in ``allowed_cols``
    or when ``sort_dir`` (case-insensitive) is not ASC/DESC. The 400 is
    visible to the operator; the prior DB-layer behavior (silent default
    substitution) would have masked the bad input.

    ``sort_dir`` is upper-cased on return so the DB layer's exact-match
    check against ("ASC", "DESC") succeeds without further normalization.
    """
    if sort_by not in allowed_cols:
        raise HTTPException(
            status_code=400,
            detail=f"invalid sort column: {sort_by!r}",
        )
    sort_dir_u = sort_dir.upper() if isinstance(sort_dir, str) else ""
    if sort_dir_u not in _ALLOWED_SORT_DIRS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid sort direction: {sort_dir!r}",
        )
    return sort_by, sort_dir_u
