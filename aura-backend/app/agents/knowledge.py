"""
AURA — Knowledge Agent (real RAG, NO mock seed).

Hybrid retrieval:
  1. KG entity lookup against the `kg_entities` Postgres table (replaces the
     hard-coded in-memory `KG` dict).
  2. Dense retrieval over Qdrant using real BGE embeddings. Documents come
     from the `knowledge_docs` Postgres table, seeded by 003_knowledge_seed.sql
     (real, descriptive rows — no mock data).
  3. LLM synthesis grounded in retrieved context, with citations back to doc_ids.

There is no _seed() function. The seed docs + KG entities live in the
database from day one (loaded by docker-compose init), and the agent just
queries them.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Dict, List

from app.models.schemas import User
from app.data_layer import vector_db, postgres
from app.llm.embeddings import embed_text
from app.llm.client import complete

log = logging.getLogger("aura.agent.knowledge")


SYSTEM_PROMPT = """You are AURA's Knowledge Agent.

Given a user query and a set of retrieved context snippets (from the knowledge
graph and the document store), produce a concise factual answer.

Rules:
  - Only use information present in the context. Do not hallucinate.
  - If the context is insufficient, say "I don't have enough context to answer."
  - Cite sources by their doc_id in square brackets, e.g. [doc_ppo].
  - Keep the answer under 120 words.
"""


class KnowledgeAgent:
    def __init__(self):
        self.docs_table = postgres.table("knowledge_docs")
        self.kg_table = postgres.table("kg_entities")
        self._docs_indexed = False
        self._index_lock = asyncio.Lock()

    async def _ensure_docs_indexed(self) -> None:
        """One-time: index all knowledge_docs into Qdrant so dense retrieval works.

        Safe to call multiple times — uses a lock + flag. Re-indexes if the
        Qdrant collection is empty (e.g. after a wipe).
        """
        if self._docs_indexed:
            return
        async with self._index_lock:
            if self._docs_indexed:
                return
            try:
                count = await vector_db.count()
                if count > 0:
                    self._docs_indexed = True
                    return
                docs = await self.docs_table.all()
                for d in docs:
                    vec = embed_text(d["text"])
                    await vector_db.upsert(d["doc_id"], vec, {
                        "kind": "knowledge_doc",
                        "text": d["text"],
                        "doc_id": d["doc_id"],
                    })
                log.info("knowledge: indexed %d docs into Qdrant", len(docs))
            except Exception as e:
                log.warning("knowledge: doc indexing failed (%s) — dense retrieval may be empty", e)
            self._docs_indexed = True

    async def query(self, user: User, q: str, top_k: int = 3) -> Dict[str, Any]:
        await self._ensure_docs_indexed()

        # 1. KG lookup against real Postgres kg_entities table
        kg_hits: List[Dict[str, Any]] = []
        q_lower = q.lower()
        try:
            all_entities = await self.kg_table.all()
            for row in all_entities:
                entity = row.get("entity", "")
                if entity.lower() in q_lower or q_lower in entity.lower():
                    rels = row.get("relations")
                    if isinstance(rels, str):
                        try:
                            rels = json.loads(rels)
                        except Exception:
                            rels = {}
                    kg_hits.append({"entity": entity, "relations": rels or {}})
        except Exception as e:
            log.debug("knowledge: kg lookup failed: %s", e)

        # 2. Dense retrieval over Qdrant
        q_vec = embed_text(q)
        dense_hits = await vector_db.search(q_vec, top_k=top_k, filters={"kind": "knowledge_doc"})

        doc_context = "\n".join(
            f"[{h[2].get('doc_id', 'unknown')}] {h[2].get('text', '')[:300]}"
            for h in dense_hits
        ) or "(no documents retrieved)"

        kg_context = json.dumps(kg_hits[:3], indent=2) if kg_hits else "(no KG entities matched)"

        # 3. LLM synthesis
        user_prompt = (
            f"USER QUERY: {q}\n\n"
            f"KNOWLEDGE GRAPH HITS:\n{kg_context}\n\n"
            f"RETRIEVED DOCUMENTS:\n{doc_context}\n\n"
            f"Answer the user query using only the above context. Cite sources as [doc_id]."
        )
        try:
            answer = await complete(
                SYSTEM_PROMPT,
                user_prompt,
                temperature=0.2,
                max_tokens=256,
            )
        except Exception as e:
            log.warning("knowledge LLM call failed: %s", e)
            answer = "I don't have enough context to answer."

        return {
            "query": q,
            "answer": answer.strip(),
            "kg_hits": kg_hits[:3],
            "doc_hits": [
                {
                    "doc_id": h[2].get("doc_id"),
                    "snippet": h[2].get("text", "")[:200],
                    "score": round(h[1], 4),
                }
                for h in dense_hits
            ],
            "llm_provider": _provider_name(),
        }


def _provider_name() -> str:
    try:
        from app.llm.client import llm_client
        return llm_client.active_provider
    except Exception:
        return "unknown"


knowledge_agent = KnowledgeAgent()
