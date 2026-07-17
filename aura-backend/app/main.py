"""
AURA backend entrypoint.

Run:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routes import router
from app.events.bus import event_bus, register_default_consumers
from app.events.ws_hub import ws_hub
from app.data_layer import init_data_layer, shutdown_data_layer


# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)
log = logging.getLogger("aura.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    log.info("AURA %s starting — env=%s", settings.VERSION, settings.ENVIRONMENT)
    await init_data_layer()
    register_default_consumers()
    await event_bus.start()
    # Start Redis pub/sub subscriber for multi-worker WebSocket fan-out
    await ws_hub.start_pubsub_subscriber()
    from app.data_layer.postgres import real_postgres
    from app.data_layer.redis_client import real_redis
    from app.data_layer.qdrant import real_qdrant
    from app.data_layer.clickhouse import real_clickhouse
    from app.data_layer.kafka import real_kafka
    log.info(
        "AURA ready — POSTGRES=%s REDIS=%s QDRANT=%s CLICKHOUSE=%s KAFKA=%s",
        real_postgres.available, real_redis.available, real_qdrant.available,
        real_clickhouse.available, real_kafka.available,
    )
    yield
    # shutdown
    await ws_hub.stop_pubsub_subscriber()
    await event_bus.stop()
    await shutdown_data_layer()
    # close LLM httpx clients
    try:
        from app.llm.client import llm_client
        await llm_client.close()
    except Exception:
        pass
    log.info("AURA shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    description="Autonomous User Recommendation & Reasoning Architecture",
    version=settings.VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {
        "service": settings.APP_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "api": "/api",
    }
