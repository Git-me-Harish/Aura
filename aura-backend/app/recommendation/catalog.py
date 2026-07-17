"""
AURA — real item catalog.

Loads the items table from Postgres and caches it in-process for fast access.
Catalog refreshes on a configurable TTL (default 5 minutes). All item fields
come from the real database — there is no hard-coded item pool.

Schema: see migrations/001_init.sql (table `items`).
Seed:   see migrations/002_items_seed.sql (real descriptive rows).
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.data_layer import postgres
from app.config import settings

log = logging.getLogger("aura.rec.catalog")


class ItemCatalog:
    """In-process cache of the items table, refreshed on a TTL."""

    def __init__(self):
        self._items: List[Dict[str, Any]] = []
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._by_category: Dict[str, List[Dict[str, Any]]] = {}
        self._last_refresh: float = 0.0
        self._lock = asyncio.Lock()
        self._tags_vocab: List[str] = []
        self._tag_index: Dict[str, int] = {}

    async def refresh(self) -> int:
        """Reload from Postgres. Returns the number of items loaded."""
        async with self._lock:
            rows = await postgres.table("items").all()
            self._items = rows
            self._by_id = {r["item_id"]: r for r in rows}
            self._by_category = {}
            tag_set: set[str] = set()
            for r in rows:
                cat = r.get("category", "misc")
                self._by_category.setdefault(cat, []).append(r)
                for t in (r.get("tags") or []):
                    tag_set.add(t)
            self._tags_vocab = sorted(tag_set)
            self._tag_index = {t: i for i, t in enumerate(self._tags_vocab)}
            self._last_refresh = time.time()
            log.info("catalog: loaded %d items across %d categories (%d unique tags)",
                     len(rows), len(self._by_category), len(self._tags_vocab))
            return len(rows)

    async def all(self) -> List[Dict[str, Any]]:
        await self._ensure_fresh()
        return self._items

    async def by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_fresh()
        return self._by_id.get(item_id)

    async def by_category(self, category: str) -> List[Dict[str, Any]]:
        await self._ensure_fresh()
        return self._by_category.get(category, [])

    async def categories(self) -> List[str]:
        await self._ensure_fresh()
        return list(self._by_category.keys())

    @property
    def tags_vocab(self) -> List[str]:
        return self._tags_vocab

    @property
    def tag_index(self) -> Dict[str, int]:
        return self._tag_index

    async def _ensure_fresh(self) -> None:
        if not self._items or (time.time() - self._last_refresh) > settings.RECSYS_CATALOG_REFRESH_SEC:
            await self.refresh()


# Singleton
item_catalog = ItemCatalog()
