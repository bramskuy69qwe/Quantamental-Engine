from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("database")


class ModelsMixin:
    """potential_models domain methods."""

    async def create_potential_model(
        self, name: str, model_type: str, description: str, config: Dict[str, Any],
    ) -> int:
        """Insert a new potential_models row; return new id."""
        async with self._conn.execute(
            """INSERT INTO potential_models (name, type, description, config_json)
               VALUES (?, ?, ?, ?)""",
            (name, model_type, description, _json.dumps(config)),
        ) as cur:
            new_id = cur.lastrowid
        await self._conn.commit()
        return new_id

    async def list_potential_models(self) -> List[Dict[str, Any]]:
        """Return all potential_models rows, newest first, with config dict decoded."""
        async with self._conn.execute(
            "SELECT * FROM potential_models ORDER BY id DESC"
        ) as cur:
            rows = await cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["config"] = _json.loads(d.get("config_json") or "{}")
            result.append(d)
        return result

    async def get_potential_model(self, model_id: int) -> Optional[Dict[str, Any]]:
        """Return a single potential_models row by id, or None."""
        async with self._conn.execute(
            "SELECT * FROM potential_models WHERE id=?", (model_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["config"] = _json.loads(d.get("config_json") or "{}")
        return d

    async def update_potential_model(
        self, model_id: int, name: str, model_type: str,
        description: str, config: Dict[str, Any],
    ) -> None:
        """Overwrite name, type, description, and config for the given model id."""
        await self._conn.execute(
            """UPDATE potential_models
               SET name=?, type=?, description=?, config_json=?
               WHERE id=?""",
            (name, model_type, description, _json.dumps(config), model_id),
        )
        await self._conn.commit()

    async def delete_potential_model(self, model_id: int) -> None:
        """Delete a potential_models row by id."""
        await self._conn.execute("DELETE FROM potential_models WHERE id=?", (model_id,))
        await self._conn.commit()
