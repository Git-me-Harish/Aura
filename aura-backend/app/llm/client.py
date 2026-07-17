"""
AURA — real LLM client.

Primary:  Groq (OpenAI-compatible API) — free tier with Llama-3.3-70B-Versatile
          and Llama-3.1-8B-Instant. Get a key at https://console.groq.com/keys
          (free, no credit card).

Fallback: HuggingFace Inference API (free tier) — many open models available.

Last resort: a deterministic template-based generator that produces structured
            explanations without an LLM call. This keeps AURA functional even
            when no LLM provider is configured.

The client is async and reuses a single httpx client for connection pooling.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

log = logging.getLogger("aura.llm.client")


# ──────────────────────────────────────────────────────────────────────────────
# LLM message types
# ──────────────────────────────────────────────────────────────────────────────
Message = Dict[str, str]  # {"role": "system"|"user"|"assistant", "content": "..."}


# ──────────────────────────────────────────────────────────────────────────────
# Provider implementations
# ──────────────────────────────────────────────────────────────────────────────
class GroqProvider:
    """OpenAI-compatible client → Groq. Free tier, very fast."""

    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.base_url = settings.GROQ_BASE_URL
        self.model = settings.GROQ_MODEL
        self.model_fast = settings.GROQ_MODEL_FAST
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=httpx.Timeout(60.0, connect=5.0),
            )
        return self._client

    async def chat(
        self,
        messages: List[Message],
        *,
        model: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        client = await self._http()
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            r = await client.post("/chat/completions", json=payload)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"] or ""
        except Exception as e:
            log.warning("groq chat failed: %s", e)
            raise


class HuggingFaceProvider:
    """HuggingFace Inference API — free tier. Good fallback when Groq quota is hit."""

    def __init__(self):
        self.token = settings.HF_API_TOKEN
        self.model = settings.HF_MODEL
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def available(self) -> bool:
        return bool(self.token) and bool(self.model)

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api-inference.huggingface.co",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=httpx.Timeout(60.0, connect=5.0),
            )
        return self._client

    async def chat(
        self,
        messages: List[Message],
        *,
        model: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        client = await self._http()
        # Build a chat-style prompt
        prompt = "\n".join(f"[{m['role'].upper()}] {m['content']}" for m in messages)
        payload = {
            "inputs": prompt,
            "parameters": {
                "temperature": max(0.01, temperature),
                "max_new_tokens": max_tokens,
                "return_full_text": False,
            },
        }
        try:
            r = await client.post(f"/models/{model or self.model}", json=payload)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and data:
                return data[0].get("generated_text", "")
            return ""
        except Exception as e:
            log.warning("hf chat failed: %s", e)
            raise


# ──────────────────────────────────────────────────────────────────────────────
# Template fallback (no API key required)
# ──────────────────────────────────────────────────────────────────────────────
class TemplateProvider:
    """Last-resort fallback — deterministic templated responses.

    Produces well-structured explanation strings so the dashboard stays
    functional when no LLM is configured. Output is clearly labelled.
    """

    @property
    def available(self) -> bool:
        return True

    async def chat(
        self,
        messages: List[Message],
        *,
        model: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        # Find the user message
        user_msg = next((m for m in reversed(messages) if m["role"] == "user"), None)
        prompt = user_msg["content"] if user_msg else ""

        # If json_mode is requested, ALWAYS return valid JSON (even in fallback)
        if json_mode:
            # Extract item title from the prompt if present (best-effort)
            import re
            title_match = re.search(r"title:\s*(.+)", prompt)
            title = title_match.group(1).strip() if title_match else "this item"
            category_match = re.search(r"category:\s*(\S+)", prompt)
            category = category_match.group(1).strip() if category_match else "general"
            score_match = re.search(r"final_score:\s*([\d.]+)", prompt)
            score = float(score_match.group(1)) if score_match else 0.7

            return json.dumps({
                "why_recommended": (
                    f"AURA recommended '{title}' because it aligns with the user's "
                    f"long-term interest in {category}, and the current context is "
                    f"a strong match. [template-fallback — set GROQ_API_KEY for "
                    f"LLM-grounded rationale]"
                ),
                "why_not_alternatives": (
                    "Alternative items had a lower combined score from the CF, "
                    "Neural-CF, and GNN rankers. [template-fallback]"
                ),
                "confidence": round(score, 3),
                "contributing_factors": [
                    f"Final ranker score: {round(score, 2)}",
                    f"Category match: {category}",
                    "[template-fallback — set GROQ_API_KEY for richer factors]",
                ],
            })

        # Default: return a plain string
        return (
            "[template-fallback] AURA received: " + prompt[:200] +
            "\n\nSet GROQ_API_KEY in aura-backend/.env to enable real LLM reasoning."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Unified client
# ──────────────────────────────────────────────────────────────────────────────
class LLMClient:
    """Routes chat calls to the first available provider in priority order."""

    def __init__(self):
        self.providers: List[Any] = []
        self._init_providers()

    def _init_providers(self) -> None:
        provider_name = settings.LLM_PROVIDER.lower()
        # Build a priority list — requested provider first, then cascading fallbacks
        candidates: Dict[str, Any] = {
            "groq": GroqProvider(),
            "hf": HuggingFaceProvider(),
            "huggingface": HuggingFaceProvider(),
            "template": TemplateProvider(),
        }
        order = [provider_name]
        for name in ["groq", "hf", "template"]:
            if name not in order:
                order.append(name)
        seen = set()
        for name in order:
            if name in seen:
                continue
            seen.add(name)
            provider = candidates.get(name)
            if provider is None:
                continue
            self.providers.append(provider)
        active = [type(p).__name__ for p in self.providers if p.available]
        log.info("llm: providers active = %s", active)

    @property
    def active_provider(self) -> str:
        for p in self.providers:
            if p.available:
                return type(p).__name__.replace("Provider", "").lower()
        return "none"

    async def chat(
        self,
        messages: List[Message],
        *,
        model: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        last_err: Optional[Exception] = None
        for p in self.providers:
            if not p.available:
                continue
            try:
                return await p.chat(
                    messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
            except Exception as e:
                last_err = e
                log.debug("provider %s failed, trying next: %s", type(p).__name__, e)
                continue
        # If all providers failed, return a template-style response
        log.error("all LLM providers failed (last error: %s)", last_err)
        return await TemplateProvider().chat(messages, json_mode=json_mode)

    async def close(self) -> None:
        for p in self.providers:
            if hasattr(p, "_client") and p._client is not None:
                try:
                    await p._client.aclose()
                except Exception:
                    pass
                p._client = None


# Singleton
llm_client = LLMClient()


# ──────────────────────────────────────────────────────────────────────────────
# Convenience helpers
# ──────────────────────────────────────────────────────────────────────────────
async def complete(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.4,
    max_tokens: int = 1024,
    json_mode: bool = False,
) -> str:
    """Single-turn completion helper."""
    return await llm_client.chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )


async def complete_json(system_prompt: str, user_prompt: str, *, temperature: float = 0.2) -> Dict[str, Any]:
    """Single-turn completion that parses the response as JSON.

    Falls back to {} if parsing fails (and prepends a template-style marker).
    """
    raw = await complete(system_prompt, user_prompt, temperature=temperature, json_mode=True)
    try:
        return json.loads(raw)
    except Exception:
        # Try to extract a JSON object from the raw text
        import re
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        log.warning("llm: failed to parse JSON response; returning empty dict. raw=%r", raw[:200])
        return {"_raw": raw}
