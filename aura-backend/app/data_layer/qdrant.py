"""
AURA — Qdrant vector DB layer with local persistent fallback.

Resolution order (per connect()):
  1. Real Qdrant server — when USE_REAL_QDRANT=True AND the HTTP server is
     reachable at settings.QDRANT_URL.
  2. Local persistent Qdrant — qdrant-client's built-in file-backed mode at
     settings.QDRANT_LOCAL_PATH (default ./qdrant_data). Embeddings persist
     across restarts. Same async API surface.
  3. Unavailable — every method returns [] / 0.

The local mode uses `AsyncQdrantClient(path=...)` which is the official
qdrant-client embedded storage. It is NOT a mock — it is the same engine
that ships in the docker container, just running in-process.
"""
from __future__ import annotations
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

log = logging.getLogger("aura.data.qdrant")


class RealQdrant:
    """Async Qdrant client with local persistent fallback."""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self._client = None
        self._mode = "none"   # "real" | "local" | "none"
        self.available = False
        self._collection = settings.QDRANT_COLLECTION

    @property
    def mode(self) -> str:
        return self._mode

    async def connect(self) -> None:
        if self._client is not None:
            return

        # 1. Try real Qdrant server first
        if settings.USE_REAL_QDRANT:
            try:
                from qdrant_client import AsyncQdrantClient  # type: ignore
                from qdrant_client.http import models as qm  # type: ignore

                client = AsyncQdrantClient(url=settings.QDRANT_URL, timeout=5.0)
                # Smoke test
                await client.get_collections()
                self._client = client
                self._mode = "real"
                self.available = True
                await self._ensure_collection()
                log.info("qdrant: connected to REAL server at %s", settings.QDRANT_URL)
                return
            except Exception as e:
                log.warning("qdrant: server unreachable (%s) — falling back to local file mode", e)

        # 2. Local persistent file mode (qdrant-client embedded engine)
        if settings.USE_REAL_QDRANT:
            try:
                from qdrant_client import AsyncQdrantClient  # type: ignore

                local_path = settings.QDRANT_LOCAL_PATH
                os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
                client = AsyncQdrantClient(path=local_path)
                self._client = client
                self._mode = "local"
                self.available = True
                await self._ensure_collection()
                log.info("qdrant: using LOCAL persistent mode at %s", local_path)
                return
            except Exception as e:
                log.error("qdrant: local mode init failed (%s) — vector DB unavailable", e)

        # 3. Unavailable
        self._client = None
        self._mode = "none"
        self.available = False
        log.warning("qdrant: unavailable — preference + memory embeddings will not persist")

    async def _ensure_collection(self) -> None:
        """Create the main collection if it doesn't exist + add payload indexes."""
        if self._client is None:
            return
        from qdrant_client.http import models as qm  # type: ignore
        try:
            cols = await self._client.get_collections()
            names = {c.name for c in cols.collections}
            if self._collection not in names:
                await self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=qm.VectorParams(size=self.dim, distance=qm.Distance.COSINE),
                )
                log.info("qdrant: created collection '%s' (dim=%d)", self._collection, self.dim)
            # Payload indexes for common filter fields
            try:
                for field in ("kind", "user_id"):
                    await self._client.create_payload_index(
                        collection_name=self._collection,
                        field_name=field,
                        field_schema=qm.PayloadSchemaType.KEYWORD,
                    )
            except Exception:
                pass  # already exists
        except Exception as e:
            log.warning("qdrant: collection setup failed (%s)", e)

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
            self._mode = "none"
            self.available = False

    async def upsert(self, point_id: str, vector: List[float], payload: Dict[str, Any]) -> None:
        if self._client is None:
            return
        from qdrant_client.http import models as qm  # type: ignore
        try:
            # Use a stable UUID5 from point_id so re-upserts update the same point
            import uuid
            try:
                uid = str(uuid.uuid5(uuid.NAMESPACE_URL, str(point_id)))
            except Exception:
                uid = str(point_id)
            await self._client.upsert(
                collection_name=self._collection,
                points=[qm.PointStruct(id=uid, vector=vector, payload=payload)],
            )
        except Exception as e:
            log.debug("qdrant upsert failed: %s", e)

    async def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        if self._client is None:
            return []
        from qdrant_client.http import models as qm  # type: ignore
        try:
            flt = None
            if filters:
                flt = qm.Filter(
                    must=[
                        qm.FieldCondition(key=k, match=qm.MatchValue(value=v))
                        for k, v in filters.items()
                    ]
                )
            res = await self._client.search(
                collection_name=self._collection,
                query_vector=query_vector,
                limit=top_k,
                query_filter=flt,
                with_payload=True,
            )
            return [
                (str(p.id), float(p.score), dict(p.payload or {}))
                for p in res
            ]
        except Exception as e:
            log.debug("qdrant search failed: %s", e)
            return []

    async def count(self) -> int:
        if self._client is None:
            return 0
        try:
            r = await self._client.count(collection_name=self._collection, exact=True)
            return r.count
        except Exception:
            return 0


real_qdrant = RealQdrant(dim=384)
