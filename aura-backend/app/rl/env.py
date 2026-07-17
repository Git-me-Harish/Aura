"""
AURA — custom Gymnasium environment for recommendation policy training.

Models the recommendation loop as a contextual-bandit-ish MDP:
  - State:  [user_embedding (32) + context_features (8) + rec_score (1) + ...]
            padded/truncated to RL_STATE_DIM (default 32).
  - Action: discrete over RL_ACTION_DIM slots (one per candidate item).
  - Reward: the actual user-action reward (click=0.2, like=0.55, purchase=1.0,
            skip=-0.15, etc.) — fed in via `set_pending_reward`.

The env is designed to be trained with PPO over a rolling buffer of recent
experiences. Because the recommendation problem is partially observable and
non-stationary, we keep episodes short (1 step = 1 recommendation decision)
and rely on the policy network to generalize across users.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

import numpy as np
import gymnasium as gym
from gymnasium import spaces

from app.config import settings

log = logging.getLogger("aura.rl.env")


class AuraRecEnv(gym.Env):
    """Recommendation policy env.

    Each `step` represents one recommendation decision. The env holds a
    rolling queue of pending experiences (state, action, reward, next_state)
    that are pushed by `RLPipeline.ingest_action` and consumed one at a time
    by `step`.
    """

    metadata = {"render_modes": ["text"]}

    def __init__(
        self,
        state_dim: int = None,
        action_dim: int = None,
        render_mode: str | None = None,
    ):
        super().__init__()
        self.state_dim = state_dim or settings.RL_STATE_DIM
        self.action_dim = action_dim or settings.RL_ACTION_DIM
        self.observation_space = spaces.Box(
            low=-1.0, high=1.0, shape=(self.state_dim,), dtype=np.float32,
        )
        self.action_space = spaces.Discrete(self.action_dim)

        # Rolling state — set externally by the pipeline
        self._current_state: np.ndarray = np.zeros(self.state_dim, dtype=np.float32)
        self._pending_reward: float = 0.0
        self._pending_next_state: Optional[np.ndarray] = None
        self._pending_done: bool = False
        self._step_count: int = 0

    
    # API used by RLPipeline to push real experiences
    def set_state(self, state_vec: List[float]) -> None:
        self._current_state = self._normalize(state_vec)

    def set_pending_transition(
        self,
        reward: float,
        next_state_vec: List[float],
        done: bool = False,
    ) -> None:
        self._pending_reward = float(reward)
        self._pending_next_state = self._normalize(next_state_vec)
        self._pending_done = bool(done)

    def _normalize(self, vec: List[float]) -> np.ndarray:
        v = np.asarray(vec, dtype=np.float32)
        if v.shape[0] >= self.state_dim:
            v = v[: self.state_dim]
        else:
            v = np.pad(v, (0, self.state_dim - v.shape[0]))
        # Clip to observation space bounds
        return np.clip(v, -1.0, 1.0).astype(np.float32)

    
    # Gymnasium API
    def reset(self, *, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None):
        super().reset(seed=seed)
        # small randomization so episodes don't all start identically
        if seed is not None:
            self.np_random = np.random.Generator(np.random.PCG64(seed))
        self._current_state = self.np_random.normal(0, 0.1, self.state_dim).astype(np.float32)
        self._current_state = np.clip(self._current_state, -1.0, 1.0)
        self._step_count = 0
        return self._current_state.copy(), {"step": 0}

    def step(self, action: int):
        # Reward is whatever the pipeline pushed for the current transition
        reward = self._pending_reward
        done = self._pending_done or self._step_count >= 1  # 1-step episodes
        # Advance to the pending next_state if provided
        if self._pending_next_state is not None:
            self._current_state = self._pending_next_state.copy()
            self._pending_next_state = None
        self._pending_reward = 0.0
        self._pending_done = False
        self._step_count += 1
        info = {"step": self._step_count, "chosen_action": int(action)}
        return self._current_state.copy(), float(reward), bool(done), False, info

    def render(self):
        if self.render_mode == "text":
            log.info("AuraRecEnv state=%s step=%d", self._current_state[:4], self._step_count)
