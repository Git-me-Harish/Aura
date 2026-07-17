"""
AURA Reinforcement Learning pipeline — hybrid facade.

If `settings.USE_REAL_RL=True` AND torch + stable-baselines3 are installed,
all training/ingestion is delegated to `TorchRLPipeline` (real PyTorch PPO,
MLflow tracking, artifact persistence).

Otherwise we fall back to the legacy numpy PPO loop so the platform stays
functional in dev sandboxes without PyTorch.

The public API (`ingest_action`, `train_step`, `metrics`, `act`,
`policy_version`, `samples_seen`, `cumulative_reward`, `_state_vector`,
`policy`) is preserved across both backends.
"""
from __future__ import annotations
import asyncio
import logging
import random
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.config import settings
from app.models.schemas import (
    Experience, PolicySnapshot, RLMetrics, UserAction,
)
from app.data_layer import redis, clickhouse, object_storage
from app.rl.torch_pipeline import torch_rl_pipeline, compute_reward as torch_compute_reward


log = logging.getLogger("aura.rl.pipeline")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────────────────────
# Numpy fallback pipeline (legacy mock) — kept verbatim for graceful degradation
# ──────────────────────────────────────────────────────────────────────────────
REWARD_TABLE: Dict[str, float] = {
    "click":        0.20,
    "like":         0.55,
    "purchase":     1.00,
    "watch_time":   0.40,
    "skip":        -0.15,
    "session_end":  0.00,
}


def compute_reward(action: UserAction) -> float:
    base = REWARD_TABLE.get(action.action, 0.0)
    return round(base + random.uniform(-0.02, 0.02), 4)


class ExperienceBuffer:
    def __init__(self, capacity: int = 10000):
        self._buf: deque[Experience] = deque(maxlen=capacity)

    def push(self, exp: Experience) -> None:
        self._buf.append(exp)
        import asyncio
        asyncio.create_task(clickhouse.insert_one("rl_experiences", {
            "exp_id": exp.timestamp.isoformat(),
            "user_id": exp.state.get("user_id", ""),
            "state_json": str(exp.state),
            "action_json": str(exp.action),
            "reward": float(exp.reward),
            "next_state_json": str(exp.next_state),
            "done": 1 if exp.done else 0,
            "policy_version": "",
            "timestamp": exp.timestamp.isoformat(),
        }))

    def sample(self, batch_size: int) -> List[Experience]:
        if len(self._buf) < batch_size:
            return list(self._buf)
        return random.sample(list(self._buf), batch_size)

    def __len__(self) -> int:
        return len(self._buf)


class PolicyNetwork:
    """Tiny numpy MLP — only used when real PyTorch is unavailable."""

    def __init__(self, state_dim: int = 16, action_dim: int = 8, seed: int = 42):
        rng = np.random.default_rng(seed)
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.W1 = rng.normal(0, 0.1, (state_dim, 64))
        self.b1 = np.zeros(64)
        self.W2 = rng.normal(0, 0.1, (64, 32))
        self.b2 = np.zeros(32)
        self.W3 = rng.normal(0, 0.1, (32, action_dim))
        self.b3 = np.zeros(action_dim)
        self.epsilon = 0.10

    def _forward(self, state_vec: np.ndarray) -> np.ndarray:
        h1 = np.tanh(state_vec @ self.W1 + self.b1)
        h2 = np.tanh(h1 @ self.W2 + self.b2)
        logits = h2 @ self.W3 + self.b3
        e = np.exp(logits - logits.max())
        return e / e.sum()

    def act(self, state_vec: np.ndarray) -> Tuple[int, float]:
        probs = self._forward(state_vec)
        if random.random() < self.epsilon:
            action = random.randint(0, self.action_dim - 1)
        else:
            action = int(np.argmax(probs))
        return action, float(probs[action])

    def train_step(self, batch: List[Experience], lr: float = 3e-4, clip_eps: float = 0.2) -> float:
        if not batch:
            return 0.0
        advantages = []
        for exp in batch:
            r = exp.reward
            s = np.array(_pad_or_slice(exp.state.get("vec", []), self.state_dim), dtype=float)
            adv = r
            advantages.append(adv)
            h1 = np.tanh(s @ self.W1 + self.b1)
            h2 = np.tanh(h1 @ self.W2 + self.b2)
            sign = 1.0 if adv >= 0 else -0.5
            action_idx = self._action_index(exp.action)
            self.W3[:, action_idx] += sign * lr * h2
            mask = np.ones(self.action_dim)
            mask[action_idx] = 0.0
            self.W3 -= sign * lr * 0.1 * np.outer(h2, mask)
        return float(np.mean(advantages))

    def _action_index(self, action: Dict[str, Any]) -> int:
        raw = action.get("item_id", "") or action.get("action", "")
        return hash(str(raw)) % self.action_dim


def _pad_or_slice(vec: List[float], dim: int) -> List[float]:
    if len(vec) >= dim:
        return vec[:dim]
    return vec + [0.0] * (dim - len(vec))


# ──────────────────────────────────────────────────────────────────────────────
# Hybrid pipeline — routes to torch when available, else numpy mock
# ──────────────────────────────────────────────────────────────────────────────
class RLPipeline:
    def __init__(self):
        self.use_real = settings.USE_REAL_RL and torch_rl_pipeline.available
        self._numpy_policy = None  # set below only for numpy fallback
        if self.use_real:
            log.info("rl: using real PyTorch + stable-baselines3 + MLflow pipeline")
            # Mirror torch pipeline's state for back-compat with callers
            self._torch = torch_rl_pipeline
        else:
            log.warning("rl: using numpy mock pipeline (install torch+sb3 to enable real RL)")
            self._torch = None
            self.buffer = ExperienceBuffer(capacity=settings.RL_BUFFER_SIZE)
            self._numpy_policy = PolicyNetwork(state_dim=16, action_dim=8)

        self.policy_version = "ppo-v0.0.1"
        self.cumulative_reward = 0.0
        self.samples_seen = 0
        self.reward_history: List[float] = []
        self.policy_snapshots: List[PolicySnapshot] = []
        self._lock = asyncio.Lock()

    # ── Back-compat properties ────────────────────────────────────────────
    @property
    def policy(self):
        # numpy pipeline callers expect `.policy` to exist
        if not self.use_real:
            return self._numpy_policy
        # For real pipeline, expose the env (used by recommendation_agent)
        return self._torch.env

    @policy.setter
    def policy(self, val):
        # only meaningful for numpy fallback (set in __init__)
        if not self.use_real:
            self._numpy_policy = val

    def _state_vector(self, user_id: str, context: Dict[str, Any]) -> List[float]:
        if self.use_real:
            return self._torch._state_vector(user_id, context)
        seed = abs(hash(user_id)) % (2**32)
        rng = np.random.default_rng(seed)
        base = rng.normal(0, 1, 16).tolist()
        return [round(x, 4) for x in base]

    def act(self, state_vec) -> Tuple[int, float]:
        """Sample an action from the current policy.

        Works for both backends:
          - Real:    delegates to TorchRLPipeline.act (PPO.predict)
          - Numpy:   delegates to PolicyNetwork.act
        """
        if self.use_real:
            return self._torch.act(list(state_vec) if not isinstance(state_vec, list) else state_vec)
        # numpy fallback
        state_np = np.asarray(state_vec, dtype=np.float32)
        return self._numpy_policy.act(state_np)

    @property
    def backend(self) -> str:
        return "torch" if self.use_real else "numpy"

    async def ingest_action(self, action: UserAction) -> Experience:
        if self.use_real:
            exp = await self._torch.ingest_action(action)
            # Mirror state for back-compat
            async with self._lock:
                self.cumulative_reward = self._torch.cumulative_reward
                self.samples_seen = self._torch.samples_seen
                self.reward_history = self._torch.reward_history
                self.policy_version = self._torch.policy_version
                await redis.set("rl:last_reward", exp.reward, ttl_seconds=600)
                await redis.set("rl:cumulative", self.cumulative_reward, ttl_seconds=600)
                import asyncio as _aio
                _aio.create_task(clickhouse.insert_one("rl_experiences", {
                    "exp_id": action.event_id,
                    "user_id": action.user_id,
                    "state_json": str(exp.state),
                    "action_json": str(exp.action),
                    "reward": float(exp.reward),
                    "next_state_json": str(exp.next_state),
                    "done": 1 if exp.done else 0,
                    "policy_version": self.policy_version,
                    "timestamp": exp.timestamp.isoformat(),
                }))
            return exp

        # ── Numpy fallback ──
        reward = compute_reward(action)
        state_vec = self._state_vector(action.user_id, action.context)
        next_state_vec = state_vec
        exp = Experience(
            state={"vec": state_vec, "user_id": action.user_id, "context": action.context},
            action={"item_id": action.item_id, "action": action.action},
            reward=reward,
            next_state={"vec": next_state_vec},
            done=action.action == "session_end",
            timestamp=_now(),
        )
        async with self._lock:
            self.buffer.push(exp)
            self.cumulative_reward += reward
            self.samples_seen += 1
            self.reward_history.append(reward)
            if len(self.reward_history) > 500:
                self.reward_history = self.reward_history[-500:]
            await redis.set("rl:last_reward", reward, ttl_seconds=600)
            await redis.set("rl:cumulative", self.cumulative_reward, ttl_seconds=600)
            import asyncio as _aio2
            _aio2.create_task(clickhouse.insert_one("rl_experiences", {
                "exp_id": action.event_id,
                "user_id": action.user_id,
                "state_json": str(exp.state),
                "action_json": str(exp.action),
                "reward": float(exp.reward),
                "next_state_json": str(exp.next_state),
                "done": 1 if exp.done else 0,
                "policy_version": self.policy_version,
                "timestamp": exp.timestamp.isoformat(),
            }))
        if self.samples_seen % settings.RL_TRAIN_INTERVAL_STEPS == 0 and len(self.buffer) >= 16:
            await self.train_step()
        return exp

    async def train_step(self) -> PolicySnapshot:
        if self.use_real:
            snap = await self._torch.train_step()
            self.policy_version = self._torch.policy_version
            self.policy_snapshots = self._torch.policy_snapshots
            object_storage.put(f"policies/{snap.version}.json", snap.model_dump_json().encode())
            import asyncio as _aio3
            _aio3.create_task(clickhouse.insert_one("policy_updates", {
                "version": snap.version,
                "mean_reward": float(snap.mean_reward),
                "samples": int(snap.samples),
                "epsilon": float(snap.epsilon),
                "updated_at": snap.updated_at.isoformat(),
            }))
            return snap

        # ── Numpy fallback ──
        batch = self.buffer.sample(batch_size=16)
        t0 = _now()
        mean_adv = self.policy.train_step(batch, lr=settings.RL_LR, clip_eps=settings.RL_CLIP_EPS)
        major, minor, patch = self._parse_version(self.policy_version)
        patch += 1
        if patch >= 10:
            patch = 0
            minor += 1
        self.policy_version = f"ppo-v{major}.{minor}.{patch}"
        snap = PolicySnapshot(
            version=self.policy_version,
            mean_reward=round(float(np.mean(self.reward_history[-50:])) if self.reward_history else 0.0, 4),
            samples=self.samples_seen,
            epsilon=self.policy.epsilon,
            updated_at=_now(),
        )
        self.policy_snapshots.append(snap)
        object_storage.put(f"policies/{snap.version}.json", snap.model_dump_json().encode())
        import asyncio as _aio4
        _aio4.create_task(clickhouse.insert_one("policy_updates", {
            "version": snap.version,
            "mean_reward": float(snap.mean_reward),
            "samples": int(snap.samples),
            "epsilon": float(snap.epsilon),
            "updated_at": snap.updated_at.isoformat(),
        }))
        return snap

    @staticmethod
    def _parse_version(v: str) -> Tuple[int, int, int]:
        body = v.split("-v")[-1]
        parts = body.split(".")
        return int(parts[0]), int(parts[1]), int(parts[2])

    def metrics(self) -> RLMetrics:
        if self.use_real:
            return self._torch.metrics()
        recent = self.reward_history[-50:]
        earlier = self.reward_history[-200:-50] if len(self.reward_history) > 50 else []
        growth = 0.0
        if recent and earlier:
            growth = float(np.mean(recent) - np.mean(earlier))
        return RLMetrics(
            cumulative_reward=round(self.cumulative_reward, 4),
            policy_regret=round(max(0.0, 1.0 - (np.mean(recent) if recent else 0.0)), 4),
            reward_growth=round(growth, 4),
            samples_seen=self.samples_seen,
            policy_version=self.policy_version,
        )


rl_pipeline = RLPipeline()
