"""
AURA — real PyTorch RL pipeline (stable-baselines3 PPO + MLflow tracking).

This replaces the numpy PPO loop in `pipeline.py` with a production-grade
training pipeline:

    user action → reward generator → experience buffer
                                     ↓
                                     AuraRecEnv (custom Gymnasium env)
                                     ↓
                                     PPO policy (stable-baselines3, PyTorch)
                                     ↓
                                     MLflow logs: reward, samples, version
                                     ↓
                                     policy artifact saved to /tmp/aura-policies/

The pipeline runs PPO in a background asyncio task. Each `train_step` call
runs a fixed number of PPO update steps on the current buffer and logs to
MLflow. Policy snapshots are saved as zip files compatible with
`stable_baselines3.PPO.load`.

Graceful degradation:
  * If USE_REAL_RL=False OR torch/sb3 import fails, callers should fall back
    to the numpy mock pipeline. The hybrid `pipeline.py` handles this routing.
"""
from __future__ import annotations
import asyncio
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.config import settings
from app.models.schemas import Experience, PolicySnapshot, RLMetrics, UserAction
from app.rl.env import AuraRecEnv

log = logging.getLogger("aura.rl.torch")


# ──────────────────────────────────────────────────────────────────────────────
# Reward generator — same table as the numpy version
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
    # Small noise to simulate env stochasticity
    return round(base + np.random.uniform(-0.02, 0.02), 4)


# ──────────────────────────────────────────────────────────────────────────────
# Lazy imports — only fail if real RL is actually requested
# ──────────────────────────────────────────────────────────────────────────────
def _try_import_torch():
    try:
        import torch  # noqa: F401
        from stable_baselines3 import PPO  # noqa: F401
        return True
    except Exception as e:
        log.warning("torch/sb3 not available: %s — falling back to numpy RL", e)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Real PyTorch RL pipeline
# ──────────────────────────────────────────────────────────────────────────────
class TorchRLPipeline:
    """stable-baselines3 PPO pipeline with MLflow tracking."""

    def __init__(self):
        self.available = _try_import_torch()
        self.env = AuraRecEnv()
        self._ppo = None
        self._mlflow_started = False
        self.policy_version = "ppo-v0.0.1"
        self.cumulative_reward = 0.0
        self.samples_seen = 0
        self.reward_history: List[float] = []
        self.policy_snapshots: List[PolicySnapshot] = []
        self._lock = asyncio.Lock()
        self._train_lock = threading.Lock()

        # Local artifact dir (in prod this would be S3 / MLflow artifact store)
        self._artifact_dir = Path("/tmp/aura-policies")
        self._artifact_dir.mkdir(parents=True, exist_ok=True)

        if self.available:
            self._init_ppo()
            self._init_mlflow()

    def _init_ppo(self) -> None:
        """Initialize the PPO model."""
        if not self.available:
            return
        try:
            from stable_baselines3 import PPO
            self._ppo = PPO(
                "MlpPolicy",
                self.env,
                learning_rate=settings.RL_LR,
                gamma=settings.RL_GAMMA,
                clip_range=settings.RL_CLIP_EPS,
                batch_size=settings.RL_BATCH_SIZE,
                verbose=0,
                device="cpu",
            )
            log.info("rl: PPO policy initialized (state=%d, action=%d)",
                     settings.RL_STATE_DIM, settings.RL_ACTION_DIM)
        except Exception as e:
            log.error("rl: PPO init failed: %s", e)
            self.available = False

    def _init_mlflow(self) -> None:
        """Point MLflow at the configured tracking URI.

        Uses a quick 2-second reachability probe — if the MLflow server isn't
        up, we disable logging entirely instead of letting every training
        step block for ~30s on connection retries.
        """
        if not self.available:
            return
        try:
            import socket
            from urllib.parse import urlparse
            u = urlparse(settings.MLFLOW_TRACKING_URI)
            host = u.hostname or "localhost"
            port = u.port or (443 if u.scheme == "https" else 80)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.5)
            try:
                s.connect((host, port))
                s.close()
            except Exception:
                log.warning(
                    "rl: MLflow server not reachable at %s:%s — logging disabled "
                    "(start it via `docker compose up mlflow`)",
                    host, port,
                )
                self._mlflow_started = False
                return

            import mlflow
            mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
            mlflow.set_experiment(settings.RL_MLFLOW_EXPERIMENT)
            self._mlflow_started = True
            log.info("rl: MLflow tracking → %s (experiment=%s)",
                     settings.MLFLOW_TRACKING_URI, settings.RL_MLFLOW_EXPERIMENT)
        except Exception as e:
            log.warning("rl: MLflow init failed: %s — logging disabled", e)
            self._mlflow_started = False

    # ──────────────────────────────────────────────────────────────────────
    # Public API — mirrors the numpy pipeline
    # ──────────────────────────────────────────────────────────────────────
    def _state_vector(self, user_id: str, context: Dict[str, Any]) -> List[float]:
        """Deterministic pseudo-embedding from user_id + context."""
        seed = abs(hash(user_id)) % (2**32)
        rng = np.random.default_rng(seed)
        # Mix in a hash of the context for some variability
        ctx_hash = abs(hash(str(sorted(context.items())))) % (2**32)
        rng2 = np.random.default_rng(ctx_hash)
        base = (rng.normal(0, 0.3, settings.RL_STATE_DIM)
                + rng2.normal(0, 0.1, settings.RL_STATE_DIM))
        return [round(float(x), 4) for x in np.clip(base, -1.0, 1.0)]

    def act(self, state_vec: List[float]) -> Tuple[int, float]:
        """Sample an action from the current PPO policy."""
        if not self.available or self._ppo is None:
            # Fallback: uniform random
            action = int(np.random.randint(settings.RL_ACTION_DIM))
            return action, 1.0 / settings.RL_ACTION_DIM
        try:
            obs = np.asarray(state_vec, dtype=np.float32)
            if obs.shape[0] != settings.RL_STATE_DIM:
                obs = np.pad(obs, (0, max(0, settings.RL_STATE_DIM - obs.shape[0])))[: settings.RL_STATE_DIM]
            obs = np.clip(obs, -1.0, 1.0).astype(np.float32)
            action, _states = self._ppo.predict(obs, deterministic=False)
            # PPO gives a discrete action; we don't have direct access to logp
            # without re-running the policy, so return a proxy probability.
            return int(action), 0.5
        except Exception as e:
            log.debug("rl: predict failed (%s) — random", e)
            return int(np.random.randint(settings.RL_ACTION_DIM)), 0.5

    async def ingest_action(self, action: UserAction) -> Experience:
        """User action → reward → experience → buffer.

        Updates the env's pending transition so the next PPO training step
        can learn from this real interaction.
        """
        reward = compute_reward(action)
        state_vec = self._state_vector(action.user_id, action.context)
        next_state_vec = state_vec  # stationary env assumption
        exp = Experience(
            state={"vec": state_vec, "user_id": action.user_id, "context": action.context},
            action={"item_id": action.item_id, "action": action.action},
            reward=reward,
            next_state={"vec": next_state_vec},
            done=action.action == "session_end",
            timestamp=datetime.now(timezone.utc),
        )
        async with self._lock:
            self.cumulative_reward += reward
            self.samples_seen += 1
            self.reward_history.append(reward)
            if len(self.reward_history) > 500:
                self.reward_history = self.reward_history[-500:]

        # Push transition into the env so PPO can learn from it
        try:
            self.env.set_state(state_vec)
            self.env.set_pending_transition(reward, next_state_vec, done=exp.done)
        except Exception as e:
            log.debug("rl: env transition push failed: %s", e)

        # Auto-train every N ingested actions
        if self.samples_seen % settings.RL_TRAIN_INTERVAL_STEPS == 0:
            asyncio.create_task(self.train_step())

        return exp

    async def train_step(self) -> PolicySnapshot:
        """Run a PPO training step and log to MLflow."""
        if not self.available or self._ppo is None:
            # No-op — caller should fall back to numpy pipeline
            return PolicySnapshot(
                version=self.policy_version,
                mean_reward=0.0,
                samples=self.samples_seen,
                epsilon=0.10,
                updated_at=datetime.now(timezone.utc),
            )

        # Run training in a thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        mean_reward = await loop.run_in_executor(None, self._train_sync)

        # Bump version
        major, minor, patch = self._parse_version(self.policy_version)
        patch += 1
        if patch >= 10:
            patch = 0
            minor += 1
        self.policy_version = f"ppo-v{major}.{minor}.{patch}"

        recent = self.reward_history[-50:]
        snap = PolicySnapshot(
            version=self.policy_version,
            mean_reward=round(float(np.mean(recent)) if recent else 0.0, 4),
            samples=self.samples_seen,
            epsilon=0.10,
            updated_at=datetime.now(timezone.utc),
        )
        self.policy_snapshots.append(snap)

        # Save artifact locally
        artifact_path = self._artifact_dir / f"{self.policy_version}.zip"
        try:
            self._ppo.save(str(artifact_path))
            log.info("rl: policy saved → %s", artifact_path)
        except Exception as e:
            log.warning("rl: artifact save failed: %s", e)

        # Log to MLflow
        if self._mlflow_started:
            try:
                import mlflow
                with mlflow.start_run(run_name=self.policy_version):
                    mlflow.log_param("policy_version", self.policy_version)
                    mlflow.log_param("algorithm", "PPO")
                    mlflow.log_param("state_dim", settings.RL_STATE_DIM)
                    mlflow.log_param("action_dim", settings.RL_ACTION_DIM)
                    mlflow.log_metric("mean_reward", snap.mean_reward)
                    mlflow.log_metric("samples_seen", snap.samples_seen)
                    mlflow.log_metric("cumulative_reward", self.cumulative_reward)
                    mlflow.log_metric("epsilon", snap.epsilon)
                    if artifact_path.exists():
                        mlflow.log_artifact(str(artifact_path))
            except Exception as e:
                log.warning("rl: MLflow logging failed: %s", e)

        return snap

    def _train_sync(self) -> float:
        """Synchronous PPO train — runs in executor thread."""
        if not self.available or self._ppo is None:
            return 0.0
        with self._train_lock:
            try:
                # Run a short rollout + update. train_step_count controls
                # how many gradient steps sb3 takes internally.
                self._ppo.learn(total_timesteps=settings.RL_BATCH_SIZE, reset_num_timesteps=False)
                # Compute mean reward from last 50 samples as the training signal
                recent = self.reward_history[-50:]
                return float(np.mean(recent)) if recent else 0.0
            except Exception as e:
                log.error("rl: PPO.learn failed: %s", e)
                return 0.0

    @staticmethod
    def _parse_version(v: str) -> Tuple[int, int, int]:
        body = v.split("-v")[-1]
        parts = body.split(".")
        return int(parts[0]), int(parts[1]), int(parts[2])

    def metrics(self) -> RLMetrics:
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


# Singleton
torch_rl_pipeline = TorchRLPipeline()
