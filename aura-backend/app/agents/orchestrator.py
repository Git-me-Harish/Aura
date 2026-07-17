"""
AURA — Orchestrator Agent (streaming version).

Coordinates the full recommendation loop and broadcasts per-agent progress
events over the WebSocket hub so the dashboard animates each step live:

  1. Context Agent          -> gather current context
  2. Memory Agent           -> recall relevant history        (parallel with 3)
  3. Preference Agent       -> build/refresh preference profile (parallel with 2)
  4. Knowledge Agent        -> factual grounding
  5. Recommendation Agent   -> candidate set
  6. Safety Agent           -> filter unsafe/biased
  7. Explanation Agent      -> natural-language rationale (LLM-backed, parallel over items)
  8. RL Agent               -> log experience, policy version

Each step emits:
  - emit_agent_start(...)  before the agent runs
  - emit_agent_step(...)   after the agent completes (with artifacts)
  - emit_orchestration_complete(...) at the end with the full result
"""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import List

from app.models.schemas import (
    AgentTrace, AgentName, OrchestrationResult, User,
)
from app.agents.preference import preference_agent
from app.agents.context import context_agent
from app.agents.memory import memory_agent
from app.agents.knowledge import knowledge_agent
from app.agents.recommendation import recommendation_agent
from app.agents.explanation import explanation_agent
from app.agents.safety import safety_agent
from app.rl.pipeline import rl_pipeline
from app.events.ws_hub import (
    emit_agent_start, emit_agent_step, emit_orchestration_complete,
)

log = logging.getLogger("aura.orchestrator")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Orchestrator:
    def __init__(self):
        self.last_result: OrchestrationResult | None = None
        self.runs: List[OrchestrationResult] = []
        self.trace_history: List[List[AgentTrace]] = []

    async def run(self, user: User, top_k: int = 6) -> OrchestrationResult:
        request_id = f"req_{uuid.uuid4().hex[:10]}"
        return await self.run_with_id(request_id, user, top_k=top_k)

    async def run_with_id(self, request_id: str, user: User, top_k: int = 6) -> OrchestrationResult:
        started_at = _now()
        trace: List[AgentTrace] = []

        # ── 1. Context ──────────────────────────────────────────────────
        await emit_agent_start("context", request_id, f"user={user.user_id}")
        t0 = time.perf_counter()
        ctx = await context_agent.snapshot(user)
        d1 = int((time.perf_counter() - t0) * 1000)
        ctx_artifact = ctx.model_dump(mode="json")
        trace.append(AgentTrace(
            agent=AgentName.context, started_at=started_at, finished_at=_now(),
            duration_ms=d1,
            input_summary=f"user={user.user_id}",
            output_summary=f"time_of_day={ctx.time_of_day}, weather={ctx.weather}, mood={ctx.mood}",
            artifacts={"context": ctx_artifact},
        ))
        await emit_agent_step("context", request_id, d1,
                              f"time_of_day={ctx.time_of_day}, weather={ctx.weather}, mood={ctx.mood}",
                              {"context": ctx_artifact})

        # ── 2 & 3. Memory recall (parallel with preference) ────────────
        await emit_agent_start("preference", request_id, f"user={user.user_id}")
        await emit_agent_start("memory", request_id, f"user={user.user_id}")
        t0 = time.perf_counter()
        pref_task = preference_agent.profile(user)
        mem_task = memory_agent.recall(user)
        pref, memories = await asyncio.gather(pref_task, mem_task)
        d2 = int((time.perf_counter() - t0) * 1000)
        pref_artifact = pref.model_dump(mode="json")
        mem_artifact = [m.model_dump(mode="json") for m in memories]
        trace.append(AgentTrace(
            agent=AgentName.preference, started_at=started_at, finished_at=_now(),
            duration_ms=d2,
            input_summary=f"user={user.user_id}",
            output_summary=f"top_interests={pref.top_interests[:3]}",
            artifacts={"preference": pref_artifact},
        ))
        trace.append(AgentTrace(
            agent=AgentName.memory, started_at=started_at, finished_at=_now(),
            duration_ms=0,
            input_summary=f"user={user.user_id}",
            output_summary=f"recalled {len(memories)} memory records",
            artifacts={"memories": mem_artifact},
        ))
        await emit_agent_step("preference", request_id, d2,
                              f"top_interests={pref.top_interests[:3]}",
                              {"preference": pref_artifact})
        await emit_agent_step("memory", request_id, 0,
                              f"recalled {len(memories)} memory records",
                              {"memories": mem_artifact})

        # ── 4. Knowledge grounding ─────────────────────────────────────
        q = f"{ctx.mood} {pref.top_interests[0] if pref.top_interests else 'general'}"
        await emit_agent_start("knowledge", request_id, f"q={q}")
        t0 = time.perf_counter()
        knowledge = await knowledge_agent.query(user, q=q)
        d3 = int((time.perf_counter() - t0) * 1000)
        trace.append(AgentTrace(
            agent=AgentName.knowledge, started_at=started_at, finished_at=_now(),
            duration_ms=d3,
            input_summary=f"q={q}",
            output_summary=f"kg_hits={len(knowledge.get('kg_hits', []))}, doc_hits={len(knowledge.get('doc_hits', []))}",
            artifacts={"knowledge": knowledge},
        ))
        await emit_agent_step("knowledge", request_id, d3,
                              f"kg_hits={len(knowledge.get('kg_hits', []))}, doc_hits={len(knowledge.get('doc_hits', []))}",
                              {"knowledge": knowledge})

        # ── 5. Recommendation candidates ───────────────────────────────
        await emit_agent_start("recommendation", request_id,
                               f"ctx={ctx.time_of_day}, pref={pref.favorite_categories[:2]}")
        t0 = time.perf_counter()
        candidates = await recommendation_agent.candidates(user, pref, ctx, top_k=top_k)
        d4 = int((time.perf_counter() - t0) * 1000)
        cand_artifact = [c.model_dump(mode="json") for c in candidates]
        trace.append(AgentTrace(
            agent=AgentName.recommendation, started_at=started_at, finished_at=_now(),
            duration_ms=d4,
            input_summary=f"ctx={ctx.time_of_day}, pref={pref.favorite_categories[:2]}",
            output_summary=f"{len(candidates)} candidates, top_score={candidates[0].score if candidates else 0}",
            artifacts={"candidates": cand_artifact},
        ))
        await emit_agent_step("recommendation", request_id, d4,
                              f"{len(candidates)} candidates, top_score={candidates[0].score if candidates else 0}",
                              {"candidates": cand_artifact})

        # ── 6. Safety check ────────────────────────────────────────────
        await emit_agent_start("safety", request_id, f"{len(candidates)} items")
        t0 = time.perf_counter()
        verdicts = await asyncio.gather(*[safety_agent.check(c) for c in candidates])
        d5 = int((time.perf_counter() - t0) * 1000)
        safe_items = [c for c, v in zip(candidates, verdicts) if v.passed]
        verdicts_artifact = [v.model_dump(mode="json") for v in verdicts]
        trace.append(AgentTrace(
            agent=AgentName.safety, started_at=started_at, finished_at=_now(),
            duration_ms=d5,
            input_summary=f"{len(candidates)} items",
            output_summary=f"{len(safe_items)}/{len(candidates)} passed",
            artifacts={"verdicts": verdicts_artifact},
        ))
        await emit_agent_step("safety", request_id, d5,
                              f"{len(safe_items)}/{len(candidates)} passed",
                              {"verdicts": verdicts_artifact})

        # ── 7. Explanation (LLM, parallel over safe items) ─────────────
        await emit_agent_start("explanation", request_id, f"{len(safe_items)} safe items")
        t0 = time.perf_counter()
        explanations = await asyncio.gather(*[
            explanation_agent.explain(item=c, alternatives=safe_items, pref=pref, ctx=ctx)
            for c in safe_items
        ])
        d6 = int((time.perf_counter() - t0) * 1000)
        expl_artifact = [e.model_dump(mode="json") for e in explanations]
        trace.append(AgentTrace(
            agent=AgentName.explanation, started_at=started_at, finished_at=_now(),
            duration_ms=d6,
            input_summary=f"{len(safe_items)} safe items",
            output_summary=f"{len(explanations)} explanations generated",
            artifacts={"explanations": expl_artifact},
        ))
        await emit_agent_step("explanation", request_id, d6,
                              f"{len(explanations)} explanations generated",
                              {"explanations": expl_artifact})

        # ── 8. RL log ──────────────────────────────────────────────────
        await emit_agent_start("rl", request_id, f"policy={rl_pipeline.policy_version}")
        t0 = time.perf_counter()
        policy_version = rl_pipeline.policy_version
        d7 = int((time.perf_counter() - t0) * 1000)
        rl_artifact = rl_pipeline.metrics().model_dump(mode="json")
        trace.append(AgentTrace(
            agent=AgentName.rl, started_at=started_at, finished_at=_now(),
            duration_ms=d7,
            input_summary=f"policy={policy_version}",
            output_summary=f"samples_seen={rl_pipeline.samples_seen}, cumulative_reward={rl_pipeline.cumulative_reward:.3f}",
            artifacts={"rl_metrics": rl_artifact},
        ))
        await emit_agent_step("rl", request_id, d7,
                              f"samples_seen={rl_pipeline.samples_seen}",
                              {"rl_metrics": rl_artifact})

        # ── Done ───────────────────────────────────────────────────────
        finished_at = _now()
        result = OrchestrationResult(
            request_id=request_id,
            user_id=user.user_id,
            started_at=started_at,
            finished_at=finished_at,
            trace=trace,
            recommendations=safe_items,
            explanations=explanations,
            safety_verdicts=verdicts,
            policy_version=policy_version,
        )
        self.last_result = result
        self.runs.append(result)
        self.trace_history.append(trace)
        if len(self.runs) > 50:
            self.runs = self.runs[-50:]
            self.trace_history = self.trace_history[-50:]

        # Broadcast the complete result
        await emit_orchestration_complete(request_id, result.model_dump(mode="json"))
        return result

    def status(self) -> List[dict]:
        """Return per-agent status for the dashboard."""
        if not self.last_result:
            return []
        statuses = []
        for tr in self.last_result.trace:
            statuses.append({
                "name": tr.agent.value,
                "role": AGENT_ROLES.get(tr.agent, ""),
                "status": "ready",
                "last_run": tr.finished_at.isoformat(),
                "latency_ms": tr.duration_ms,
                "detail": tr.output_summary,
            })
        return statuses


AGENT_ROLES = {
    AgentName.orchestrator:  "Coordinates the full multi-agent loop",
    AgentName.preference:    "Learns interests, habits, categories, patterns",
    AgentName.context:       "Gathers time, weather, calendar, location, mood",
    AgentName.memory:        "Long-term preferences, interactions, embeddings",
    AgentName.knowledge:     "RAG + Knowledge Graph for factual reasoning",
    AgentName.recommendation:"CF + Neural CF + GNN + LLM ranking candidates",
    AgentName.rl:            "PPO policy trainer over reward signal",
    AgentName.explanation:   "Natural-language why / why-not rationale",
    AgentName.safety:        "Bias, unsafe, hallucination, privacy, policy",
}


orchestrator = Orchestrator()
