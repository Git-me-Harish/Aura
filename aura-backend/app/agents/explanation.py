"""
AURA — Explanation Agent (real LLM-backed).

Answers:
  - Why was this recommended?
  - Why not another item?

Uses the real LLM client (Groq Llama-3.3-70B primary, HF fallback, template
last resort) to produce natural-language rationale. The LLM is called with
`json_mode` and the response is parsed into a structured Explanation.

Performance: explanations for safe items are produced concurrently via
asyncio.gather, so the latency is one LLM round-trip (not N).
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import List

from app.models.schemas import Explanation, RecommendationItem, ContextSnapshot, PreferenceProfile
from app.llm.client import complete_json, llm_client

log = logging.getLogger("aura.agent.explanation")


SYSTEM_PROMPT = """You are AURA's Explanation Agent.

Given a recommendation item, the user's preference profile, the current context,
and a list of alternative items that were considered, produce a concise,
factually-grounded explanation of:

  1. why_recommended — 2-3 sentences explaining why this specific item was
     chosen for this user at this moment. Reference concrete signals from
     the preference profile and context.

  2. why_not_alternatives — 1-2 sentences explaining why the next-best
     alternatives ranked lower. Be specific about which signal differed.

  3. confidence — a float in [0,1] reflecting how strongly the evidence
     supports this recommendation. Lower confidence when signals conflict.

  4. contributing_factors — a list of 3-5 short strings, each naming a
     concrete factor and its value (e.g. "Preference alignment: 0.82").

Return STRICT JSON with keys: why_recommended, why_not_alternatives,
confidence (number), contributing_factors (array of strings).
"""


class ExplanationAgent:
    async def explain(
        self,
        item: RecommendationItem,
        alternatives: List[RecommendationItem],
        pref: PreferenceProfile,
        ctx: ContextSnapshot,
    ) -> Explanation:
        # Build a compact prompt
        user_prompt = self._build_prompt(item, alternatives, pref, ctx)

        try:
            data = await complete_json(
                SYSTEM_PROMPT,
                user_prompt,
                temperature=0.3,
            )
        except Exception as e:
            log.warning("explanation LLM call failed: %s — using template", e)
            data = {}

        why = data.get("why_recommended") or self._template_why(item, pref, ctx)
        why_not = data.get("why_not_alternatives") or self._template_why_not(item, alternatives)
        try:
            confidence = float(data.get("confidence", item.score))
        except (TypeError, ValueError):
            confidence = item.score
        contributing = (
            data.get("contributing_factors")
            or self._template_factors(item)
        )

        return Explanation(
            item_id=item.item_id,
            why_recommended=why,
            why_not_alternatives=why_not,
            confidence=round(confidence, 3),
            contributing_factors=contributing,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Prompt construction
    # ──────────────────────────────────────────────────────────────────────
    def _build_prompt(
        self,
        item: RecommendationItem,
        alternatives: List[RecommendationItem],
        pref: PreferenceProfile,
        ctx: ContextSnapshot,
    ) -> str:
        alt_lines = []
        for alt in alternatives[:3]:
            if alt.item_id == item.item_id:
                continue
            alt_lines.append(
                f"- '{alt.title}' (category={alt.category}, score={alt.score}, "
                f"source={alt.source})"
            )
        alts_text = "\n".join(alt_lines) if alt_lines else "(no close alternatives)"

        factors = []
        for k in ("cf_score", "neural_cf_score", "gnn_score", "llm_rank_score", "rl_p"):
            v = item.metadata.get(k)
            if v is not None:
                factors.append(f"{k}={v}")

        return (
            f"RECOMMENDED ITEM:\n"
            f"  title: {item.title}\n"
            f"  category: {item.category}\n"
            f"  description: {item.description}\n"
            f"  final_score: {item.score}\n"
            f"  source: {item.source}\n"
            f"  ranker_signals: {', '.join(factors)}\n"
            f"  rl_policy: {item.metadata.get('rl_policy', 'n/a')}\n\n"
            f"USER PREFERENCE PROFILE:\n"
            f"  top_interests: {', '.join(pref.top_interests[:5])}\n"
            f"  favorite_categories: {', '.join(pref.favorite_categories[:5])}\n"
            f"  interaction_patterns: {json.dumps(pref.interaction_patterns)}\n\n"
            f"CURRENT CONTEXT:\n"
            f"  time_of_day: {ctx.time_of_day}\n"
            f"  weekday: {ctx.weekday}\n"
            f"  weather: {ctx.weather} ({ctx.temperature_c}°C)\n"
            f"  location: {ctx.location}\n"
            f"  mood: {ctx.mood}\n"
            f"  calendar_next: {ctx.calendar_next or 'none'}\n\n"
            f"ALTERNATIVES CONSIDERED:\n{alts_text}\n\n"
            f"Produce the JSON explanation now."
        )

    # ──────────────────────────────────────────────────────────────────────
    # Template fallbacks (only used if LLM returns nothing)
    # ──────────────────────────────────────────────────────────────────────
    def _template_why(self, item, pref, ctx) -> str:
        return (
            f"AURA recommended '{item.title}' because it aligns with your long-term "
            f"interest in {item.category}, the current context ({ctx.time_of_day}, "
            f"{ctx.weather.lower()}, mood={ctx.mood}) is a strong match, and the RL "
            f"policy ({item.metadata.get('rl_policy', 'n/a')}) assigned a positive action score."
        )

    def _template_why_not(self, item, alternatives) -> str:
        reasons = []
        for alt in alternatives[:3]:
            if alt.item_id == item.item_id:
                continue
            gap = round(item.score - alt.score, 3)
            reasons.append(
                f"'{alt.title}' ranked lower by {gap}: weaker match for category '{alt.category}'."
            )
        return " ".join(reasons) if reasons else "No close alternatives in this run."

    def _template_factors(self, item) -> List[str]:
        return [
            f"Preference alignment (CF): {round(item.metadata.get('cf_score', 0), 2)}",
            f"Neural CF score: {round(item.metadata.get('neural_cf_score', 0), 2)}",
            f"GNN score: {round(item.metadata.get('gnn_score', 0), 2)}",
            f"LLM re-rank: {round(item.metadata.get('llm_rank_score', 0), 2)}",
            f"RL action prob: {round(item.metadata.get('rl_p', 0), 2)}",
        ]


explanation_agent = ExplanationAgent()
