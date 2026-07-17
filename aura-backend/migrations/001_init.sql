-- AURA — initial schema for PostgreSQL.
-- Loaded automatically by docker-compose as /docker-entrypoint-initdb.d/001_init.sql.

-- We avoid CREATE EXTENSION here — pgcrypto / uuid-ossp are optional contrib
-- modules that aren't bundled with minimal/embedded postgres builds.
-- Instead, UUIDs are generated client-side by the application (uuid.uuid4())
-- before INSERT. DEFAULT NULL is fine because every INSERT supplies the value.

-- ──────────────────────────────────────────────────────────────────────────
-- Users (mirror of NextAuth users — keyed by NextAuth user id)
-- No demo user is seeded — every user must come from real NextAuth sign-in.
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT UNIQUE NOT NULL,
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    preferred_language TEXT NOT NULL DEFAULT 'en',
    image           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ──────────────────────────────────────────────────────────────────────────
-- Item catalog — the universe of recommendable items.
-- Seeded by 002_items_seed.sql with real, descriptive rows (no mock IDs).
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS items (
    item_id         TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    tags            TEXT[] NOT NULL DEFAULT '{}',
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
CREATE INDEX IF NOT EXISTS idx_items_tags     ON items USING GIN(tags);

-- ──────────────────────────────────────────────────────────────────────────
-- OAuth tokens (Spotify / Google Calendar / GitHub) per user
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id              TEXT PRIMARY KEY,             -- synthetic: "<user_id>:<provider>"
    user_id         TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,                -- 'spotify' | 'google' | 'github'
    access_token    TEXT NOT NULL,
    refresh_token   TEXT,
    expires_at      TIMESTAMPTZ,
    scopes          TEXT[],
    raw             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, provider)
);

-- ──────────────────────────────────────────────────────────────────────────
-- User interactions — the Preference Agent + ALS CF + Neural CF all train
-- on these. This is the ground-truth signal.
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS interactions (
    interaction_id  UUID PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    item_id         TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
    category        TEXT NOT NULL,
    action          TEXT NOT NULL,                -- click | like | purchase | skip | watch_time | session_end
    weight          REAL NOT NULL DEFAULT 0.5,
    context         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_interactions_user        ON interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_interactions_user_cat    ON interactions(user_id, category);
CREATE INDEX IF NOT EXISTS idx_interactions_item        ON interactions(item_id);
CREATE INDEX IF NOT EXISTS idx_interactions_created_at  ON interactions(created_at DESC);

-- ──────────────────────────────────────────────────────────────────────────
-- Long-term memory records (Memory Agent) — only real user-stored records.
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memory_records (
    record_id       UUID PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,                -- preference | interaction | conversation | purchase | embedding
    content         TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_user        ON memory_records(user_id);
CREATE INDEX IF NOT EXISTS idx_memory_user_kind   ON memory_records(user_id, kind);

-- ──────────────────────────────────────────────────────────────────────────
-- User preference profiles (Preference Agent snapshots)
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS preference_profiles (
    user_id             TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    top_interests       TEXT[] NOT NULL DEFAULT '{}',
    favorite_categories TEXT[] NOT NULL DEFAULT '{}',
    interaction_patterns JSONB NOT NULL DEFAULT '{}'::jsonb,
    long_term_vector    JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ──────────────────────────────────────────────────────────────────────────
-- Knowledge documents (Knowledge Agent RAG corpus) — seeded by 003_knowledge_seed.sql
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS knowledge_docs (
    doc_id          TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    text            TEXT NOT NULL,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_tags ON knowledge_docs USING GIN(tags);

-- ──────────────────────────────────────────────────────────────────────────
-- Knowledge graph entities (replaces the in-memory KG dict)
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kg_entities (
    entity          TEXT PRIMARY KEY,
    relations       JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {relation_type: [targets]}
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kg_entity ON kg_entities USING GIN(relations jsonb_path_ops);

-- ──────────────────────────────────────────────────────────────────────────
-- RL experience buffer (the RL pipeline reads from here for offline training)
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rl_experiences (
    exp_id          UUID PRIMARY KEY,
    user_id         TEXT NOT NULL,
    state           JSONB NOT NULL,
    action          JSONB NOT NULL,
    reward          REAL NOT NULL,
    next_state      JSONB NOT NULL,
    done            BOOLEAN NOT NULL DEFAULT false,
    policy_version  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rl_exp_user      ON rl_experiences(user_id);
CREATE INDEX IF NOT EXISTS idx_rl_exp_created   ON rl_experiences(created_at DESC);

-- ──────────────────────────────────────────────────────────────────────────
-- Audit log (Security Agent + auth events)
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id        UUID PRIMARY KEY,
    user_id         TEXT,
    event           TEXT NOT NULL,
    detail          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_user   ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_event  ON audit_log(event);
