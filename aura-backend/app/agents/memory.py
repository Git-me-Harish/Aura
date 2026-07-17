"""
AURA — Memory Agent (real Qdrant + Postgres, NO mock seed).

Stores long-term preferences, past interactions, conversations, purchases, and
embedding snapshots. Memory contains ONLY records the user actually produced
— there is no _seed() function injecting fake memories on first run.

Production path:
  - Metadata in Postgres `memory_records` table
  - Embeddings in Qdrant with payload {user_id, kind, record_id, content}
  - Recall = hybrid: metadata filter by user_id, then dense retrieval by query_vec

For a brand-new user, recall() returns []. The orchestrator handles the empty
case explicitly — the Recommendation Agent's rankers cold-start at 0.5.
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.models.schemas import MemoryRecord, User
from app.data_layer import postgres, vector_db
from app.llm.embeddings import embed_text

log = logging.getLogger("aura.agent.memory")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryAgent:
    def __init__(self):
        self.records = postgres.table("memory_records")

    async def recall(
        self,
        user: User,
        query_vec: Optional[List[float]] = None,
        top_k: int = 5,
    ) -> List[MemoryRecord]:
        if query_vec:
            hits = await vector_db.search(
                query_vec, top_k=top_k, filters={"user_id": user.user_id},
            )
            return [
                MemoryRecord(**h[2])
                for h in hits
                if isinstance(h[2], dict) and "record_id" in h[2]
            ]
        rows = await self.records.where(user_id=user.user_id)
        out: List[MemoryRecord] = []
        for r in rows[:top_k]:
            try:
                out.append(MemoryRecord(**r))
            except Exception as e:
                log.debug("memory record parse failed: %s", e)
        return out

    async def store(self, user: User, kind: str, content: str) -> MemoryRecord:
        """Persist a real memory record (called from orchestrator on user feedback)."""
        # Use a real UUID — the memory_records.record_id column is UUID PRIMARY KEY.
        record_uuid = str(uuid.uuid4())
        rec = MemoryRecord(
            record_id=record_uuid,
            user_id=user.user_id, kind=kind, content=content,
            timestamp=_now(),
            embedding=embed_text(content)[:32],
        )
        try:
            # Insert with the column names that actually exist in the memory_records
            # table (record_id, user_id, kind, content, metadata, created_at).
            # `embedding` goes to Qdrant, not Postgres. `timestamp` maps to created_at.
            await self.records.insert(rec.record_id, {
                "record_id":  rec.record_id,
                "user_id":    rec.user_id,
                "kind":       rec.kind,
                "content":    rec.content,
                "metadata":   rec.metadata,
                "created_at": rec.timestamp,
            })
            await vector_db.upsert(
                rec.record_id,
                embed_text(content),
                {
                    "user_id": user.user_id, "kind": kind,
                    "record_id": rec.record_id, "content": content,
                },
            )
        except Exception as e:
            log.warning("memory store failed: %s", e)
        return rec


memory_agent = MemoryAgent()
