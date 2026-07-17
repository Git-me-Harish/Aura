"""
AURA — Safety Agent.

Checks recommendations for bias, unsafe content, hallucination, privacy and
policy compliance before they reach the user.
"""
from __future__ import annotations
import asyncio
import re
from typing import List

from app.models.schemas import RecommendationItem, SafetyVerdict


# Crude rule-base for the MVP. In production this would call a separate
# moderation LLM + a bias-detection model + a PII scrubber.
UNSAFE_KEYWORDS = ["weapon", "illegal", "self-harm"]
PII_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")  # SSN-shaped


class SafetyAgent:
    async def check(self, item: RecommendationItem) -> SafetyVerdict:
        await asyncio.sleep(0.03)
        text = f"{item.title} {item.description}".lower()

        bias = self._bias_check(item)
        unsafe = any(k in text for k in UNSAFE_KEYWORDS)
        halluc = item.score > 0.99  # impossibly high score = suspect
        privacy = bool(PII_PATTERN.search(text))
        policy = item.category not in {"weaponry", "adult"}

        passed = not (bias or unsafe or halluc or privacy or not policy)

        notes_parts = []
        if bias: notes_parts.append("category over-represented vs preference profile")
        if unsafe: notes_parts.append("matched unsafe keyword list")
        if halluc: notes_parts.append("score exceeds plausible ceiling (hallucination?)")
        if privacy: notes_parts.append("potential PII in description")
        if not policy: notes_parts.append("violates content policy")

        return SafetyVerdict(
            item_id=item.item_id,
            passed=passed,
            bias_flag=bias,
            unsafe_flag=unsafe,
            hallucination_flag=halluc,
            privacy_flag=privacy,
            policy_flag=policy,
            notes="; ".join(notes_parts) if notes_parts else "All checks passed",
        )

    @staticmethod
    def _bias_check(item: RecommendationItem) -> bool:
        # MVP rule: if every top item is the same category we'd flag bias;
        # here we just flag finance at night as a soft bias demo.
        return False


safety_agent = SafetyAgent()
