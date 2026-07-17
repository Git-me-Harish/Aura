"""
AURA — Backend configuration.

Reads from environment (.env) with sensible dev defaults. Every "real service"
flag controls whether AURA connects to the real external service. There is NO
in-process mock fallback any more — if a service is flagged off, the affected
subsystem logs an error and skips the operation rather than producing fake data.
"""
from __future__ import annotations
import json
import logging
import os
import socket
from typing import List
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_cors(v) -> List[str]:
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return [s.strip() for s in v.split(",") if s.strip()]
    return []


def _fix_postgres_dsn_for_windows(dsn: str) -> str:
    if os.name != "nt" or not dsn:
        return dsn
    parsed = urlparse(dsn)
    if parsed.scheme in ("postgresql", "postgres") and parsed.hostname is None:
        # Windows cannot use Unix domain socket DSNs like postgres://aura:aura@/aura?host=/...
        query = parsed.query or ""
        if "host=/" in query:
            user = parsed.username or "aura"
            password = parsed.password or "aura"
            database = parsed.path.lstrip("/") or "aura"
            logging.warning(
                "config: detected Unix socket Postgres DSN on Windows; falling back to localhost:5432"
            )
            return f"postgresql://{user}:{password}@localhost:5432/{database}"
    return dsn
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return [s.strip() for s in v.split(",") if s.strip()]
    return []


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    # ── App ──
    APP_NAME: str = "AURA"
    VERSION: str = "0.3.0"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ENVIRONMENT: str = "dev"

    # ── Real services: relational + cache + vector + MLOps ──
    POSTGRES_DSN: str = "postgresql://aura:aura@localhost:5432/aura"
    REDIS_URL: str = "redis://localhost:6379/0"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "aura_embeddings"
    QDRANT_LOCAL_PATH: str = "/home/z/my-project/aura-backend/qdrant_data"  # local file-mode fallback when server is unreachable
    MLFLOW_TRACKING_URI: str = "http://localhost:5000"

    # ── Real services: event streaming ──
    CLICKHOUSE_URL: str = "http://localhost:8123"
    CLICKHOUSE_USER: str = "aura"
    CLICKHOUSE_PASSWORD: str = "aura"
    CLICKHOUSE_DATABASE: str = "aura"
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC_USER_ACTIONS: str = "aura.user_actions"
    KAFKA_TOPIC_WS_EVENTS: str = "aura.ws_events"
    KAFKA_CONSUMER_GROUP: str = "aura-backend"
    KAFKA_TOPIC_REPLICATION: int = 1
    KAFKA_TOPIC_PARTITIONS: int = 4

    # ── LLM ──
    LLM_PROVIDER: str = "groq"           # groq | openai | together | hf | template
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_MODEL_FAST: str = "llama-3.1-8b-instant"
    HF_API_TOKEN: str = ""
    HF_MODEL: str = "meta-llama/Llama-3.2-3B-Instruct"

    # ── Embeddings ──
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIM: int = 384

    # ── RL ──
    RL_ALGORITHM: str = "ppo"
    RL_STATE_DIM: int = 32
    RL_ACTION_DIM: int = 32
    RL_GAMMA: float = 0.99
    RL_LR: float = 3e-4
    RL_CLIP_EPS: float = 0.2
    RL_BATCH_SIZE: int = 64
    RL_BUFFER_SIZE: int = 10000
    RL_TRAIN_INTERVAL_STEPS: int = 10
    RL_MLFLOW_EXPERIMENT: str = "aura-rl-ppo"

    # ── Recommendation rankers ──
    RECSYS_NEURAL_CF_DIM: int = 64        # embedding dim for Neural CF
    RECSYS_NEURAL_CF_LAYERS: str = "[128, 64]"   # MLP hidden layers
    RECSYS_CF_FACTORS: int = 32           # ALS latent factors
    RECSYS_CF_EPOCHS: int = 15            # ALS iterations
    RECSYS_CATALOG_REFRESH_SEC: int = 300  # how often to refresh the item catalog cache

    # ── Auth ──
    NEXTAUTH_SECRET: str = "change-me-to-a-long-random-string"
    NEXTAUTH_URL: str = "http://localhost:3000"
    JWT_ALG: str = "HS256"
    JWT_ISSUER: str = "aura-nextauth"

    # ── MCP OAuth providers ──
    SPOTIFY_CLIENT_ID: str = ""
    SPOTIFY_CLIENT_SECRET: str = ""
    SPOTIFY_REDIRECT_URI: str = "http://localhost:3000/api/auth/callback/spotify"
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/oauth/callback/google"
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""

    # ── OpenWeather (used by real weather MCP handler) ──
    OPENWEATHER_API_KEY: str = ""
    OPENWEATHER_DEFAULT_CITY: str = "Bengaluru"

    # ── NewsAPI (used by real news MCP handler) ──
    NEWSAPI_KEY: str = ""

    # ── CORS ──
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:81",
        "http://127.0.0.1:81",
    ]

    # ── Feature flags (graceful skip — never substitute fake data) ──
    USE_REAL_POSTGRES: bool = True
    USE_REAL_REDIS: bool = True
    USE_REAL_QDRANT: bool = True
    USE_REAL_CLICKHOUSE: bool = True
    USE_REAL_KAFKA: bool = True
    USE_REAL_LLM: bool = True
    USE_REAL_RL: bool = True
    USE_REAL_MCP: bool = True
    USE_REAL_RECSYS: bool = True   # ALS CF + Neural CF rankers
    USE_REAL_EMBEDDINGS: bool = True


settings = Settings()
settings.POSTGRES_DSN = _fix_postgres_dsn_for_windows(settings.POSTGRES_DSN)

# Re-parse CORS in case env override came in as a JSON string
settings.CORS_ORIGINS = _parse_cors(settings.CORS_ORIGINS)
