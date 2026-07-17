"""
AURA shared data models — used by every agent and every API route.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────────
# User / Context
# ──────────────────────────────────────────────────────────────────────────────
class User(BaseModel):
    user_id: str
    name: str
    timezone: str = "UTC"
    preferred_language: str = "en"


class ContextSnapshot(BaseModel):
    """Produced by the Context Agent — what is happening RIGHT NOW."""
    timestamp: datetime
    time_of_day: str  # morning | afternoon | evening | night
    weekday: str
    weather: str
    temperature_c: float
    location: str
    device: str  # mobile | desktop | tablet | tv
    mood: str  # focused | relaxed | energetic | tired | neutral
    recent_searches: List[str] = []
    calendar_next: Optional[str] = None
    raw: Dict[str, Any] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Preference / Memory
# ──────────────────────────────────────────────────────────────────────────────
class PreferenceProfile(BaseModel):
    """Produced by the Preference Agent."""
    top_interests: List[str]
    favorite_categories: List[str]
    interaction_patterns: Dict[str, float]  # pattern_name -> strength 0..1
    long_term_vector: List[float] = Field(default_factory=list, description="embedding")
    updated_at: datetime


class MemoryRecord(BaseModel):
    """A single entry in long-term memory (Memory Agent)."""
    record_id: str
    user_id: str
    kind: str  # preference | interaction | conversation | purchase | embedding
    content: str
    embedding: List[float] = []
    metadata: Dict[str, Any] = {}
    timestamp: datetime


# ──────────────────────────────────────────────────────────────────────────────
# Recommendation
# ──────────────────────────────────────────────────────────────────────────────
class RecommendationItem(BaseModel):
    item_id: str
    title: str
    category: str
    description: str
    score: float  # 0..1 confidence
    source: str  # cf | neural_cf | gnn | llm_rank
    reasons: List[str] = []
    metadata: Dict[str, Any] = {}


class RecommendationSet(BaseModel):
    request_id: str
    user_id: str
    items: List[RecommendationItem]
    generated_at: datetime
    policy_version: str


# ──────────────────────────────────────────────────────────────────────────────
# Explanation
# ──────────────────────────────────────────────────────────────────────────────
class Explanation(BaseModel):
    item_id: str
    why_recommended: str
    why_not_alternatives: str
    confidence: float
    contributing_factors: List[str]


# ──────────────────────────────────────────────────────────────────────────────
# Safety
# ──────────────────────────────────────────────────────────────────────────────
class SafetyVerdict(BaseModel):
    item_id: str
    passed: bool
    bias_flag: bool = False
    unsafe_flag: bool = False
    hallucination_flag: bool = False
    privacy_flag: bool = False
    policy_flag: bool = False
    notes: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# RL
# ──────────────────────────────────────────────────────────────────────────────
class UserAction(BaseModel):
    """An event streamed through the event bus."""
    event_id: str
    user_id: str
    item_id: str
    action: str  # click | purchase | like | skip | session_end
    reward: float
    timestamp: datetime
    context: Dict[str, Any] = {}


class Experience(BaseModel):
    state: Dict[str, Any]
    action: Dict[str, Any]
    reward: float
    next_state: Dict[str, Any]
    done: bool
    timestamp: datetime


class PolicySnapshot(BaseModel):
    version: str
    mean_reward: float
    samples: int
    epsilon: float
    updated_at: datetime


# ──────────────────────────────────────────────────────────────────────────────
# Agent orchestration
# ──────────────────────────────────────────────────────────────────────────────
class AgentName(str, Enum):
    orchestrator = "orchestrator"
    preference = "preference"
    context = "context"
    memory = "memory"
    knowledge = "knowledge"
    recommendation = "recommendation"
    rl = "rl"
    explanation = "explanation"
    safety = "safety"


class AgentStatus(BaseModel):
    name: AgentName
    role: str
    status: str  # idle | thinking | ready | error
    last_run: Optional[datetime] = None
    latency_ms: Optional[int] = None
    detail: str = ""


class AgentTrace(BaseModel):
    """One step in an orchestration run."""
    agent: AgentName
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    input_summary: str
    output_summary: str
    artifacts: Dict[str, Any] = {}


class OrchestrationResult(BaseModel):
    request_id: str
    user_id: str
    started_at: datetime
    finished_at: datetime
    trace: List[AgentTrace]
    recommendations: List[RecommendationItem]
    explanations: List[Explanation]
    safety_verdicts: List[SafetyVerdict]
    policy_version: str


# ──────────────────────────────────────────────────────────────────────────────
# MCP tool layer
# ──────────────────────────────────────────────────────────────────────────────
class MCPTool(BaseModel):
    name: str
    category: str  # calendar | email | github | spotify | maps | weather | news | finance | shopping | health | slack | notion | drive | databricks
    connected: bool
    last_sync: Optional[datetime] = None
    description: str
    capabilities: List[str]


class MCPToolCall(BaseModel):
    tool: str
    method: str
    args: Dict[str, Any]
    result: Any
    duration_ms: int


# ──────────────────────────────────────────────────────────────────────────────
# Metrics
# ──────────────────────────────────────────────────────────────────────────────
class RecommendationMetrics(BaseModel):
    precision_at_k: float
    recall_at_k: float
    ndcg: float
    map_score: float
    mrr: float


class BusinessMetrics(BaseModel):
    ctr: float
    conversion_rate: float
    revenue: float
    retention: float
    avg_session_time_sec: float


class RLMetrics(BaseModel):
    cumulative_reward: float
    policy_regret: float
    reward_growth: float
    samples_seen: int
    policy_version: str


class DashboardMetrics(BaseModel):
    recommendation: RecommendationMetrics
    business: BusinessMetrics
    rl: RLMetrics
