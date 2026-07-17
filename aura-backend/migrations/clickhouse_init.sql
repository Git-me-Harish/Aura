-- AURA — ClickHouse schema.
-- Loaded automatically by docker-compose as /docker-entrypoint-initdb.d/clickhouse_init.sql.

CREATE DATABASE IF NOT EXISTS aura;

USE aura;

-- ──────────────────────────────────────────────────────────────────────────
-- User actions stream (produced to Kafka, persisted here by the bus)
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_actions (
    event_id        String,
    user_id         String,
    item_id         String,
    action          String,
    reward          Float32,
    timestamp       DateTime64(3, 'UTC'),
    context         String,                 -- JSON
    topic           String,                 -- Kafka topic the event came from
    partition_id    UInt32,
    offset          UInt64,
    ingested_at     DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (user_id, timestamp)
SETTINGS index_granularity = 8192;

-- ──────────────────────────────────────────────────────────────────────────
-- RL experiences
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rl_experiences (
    exp_id          String,
    user_id         String,
    state_json      String,                 -- JSON
    action_json     String,
    reward          Float32,
    next_state_json String,
    done            UInt8,
    policy_version  String,
    timestamp       DateTime64(3, 'UTC'),
    ingested_at     DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (user_id, timestamp);

-- ──────────────────────────────────────────────────────────────────────────
-- Policy updates (one row per training step)
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS policy_updates (
    version         String,
    mean_reward     Float32,
    samples         UInt64,
    epsilon         Float32,
    updated_at      DateTime64(3, 'UTC'),
    ingested_at     DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(updated_at)
ORDER BY (updated_at);

-- ──────────────────────────────────────────────────────────────────────────
-- Orchestration traces (one row per agent_step event)
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orchestration_traces (
    request_id      String,
    user_id         String,
    agent           String,
    event_type      String,                 -- agent_start | agent_step | orchestration_complete
    duration_ms     UInt32 DEFAULT 0,
    output_summary  String DEFAULT '',
    artifacts_json  String DEFAULT '',
    ts              DateTime64(3, 'UTC'),
    ingested_at     DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(ts)
ORDER BY (request_id, agent, ts);

-- ──────────────────────────────────────────────────────────────────────────
-- MCP tool calls (audit + latency tracking)
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mcp_calls (
    user_id         String,
    tool            String,
    method          String,
    args_json       String,
    duration_ms     UInt32,
    success         UInt8,
    ts              DateTime64(3, 'UTC'),
    ingested_at     DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(ts)
ORDER BY (tool, ts);

-- ──────────────────────────────────────────────────────────────────────────
-- Recommendation feedback (closed-loop for offline evaluation)
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS recommendation_feedback (
    request_id      String,
    user_id         String,
    item_id         String,
    shown_rank      UInt32,
    final_score     Float32,
    source          String,
    policy_version  String,
    clicked         UInt8 DEFAULT 0,
    liked           UInt8 DEFAULT 0,
    purchased       UInt8 DEFAULT 0,
    skipped         UInt8 DEFAULT 0,
    ts              DateTime64(3, 'UTC'),
    ingested_at     DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(ts)
ORDER BY (user_id, ts);
