# AURA — Autonomous User Recommendation & Reasoning Architecture

> A multi-agent reinforcement learning recommendation platform powered by LLMs, MCP, long-term memory, and continuous learning.
>
> Shifts from a prediction engine ("What should I recommend?") to an autonomous decision-making platform ("Why, when, how confident, and how to continuously improve?").

**Version 0.3.0** — real services, real RL, real LLM, real auth, streaming orchestration, per-user personalization.

---

## What's in this zip

```
aura/                                 # project root
├── README.md                         # ← you are here (project overview + quickstart)
├── SETUP.md                          # detailed VS Code setup walkthrough
├── .env.example                      # frontend env template
├── .gitignore
├── package.json                      # Next.js 16 + NextAuth + Prisma + shadcn/ui
├── bun.lock                          # lock file (use `bun install` or `npm install`)
├── next.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.mjs
├── eslint.config.mjs
├── components.json                   # shadcn/ui config
├── Caddyfile                         # optional gateway (port 81 → 3000)
├── prisma/
│   └── schema.prisma                 # auth DB schema (User, Account)
├── public/                           # static assets
├── src/                              # ← Next.js frontend source
│   ├── app/                          # pages + API routes
│   │   ├── page.tsx                  # main dashboard
│   │   ├── layout.tsx                # SessionProvider + ThemeProvider
│   │   ├── auth/signin/page.tsx      # NextAuth sign-in
│   │   ├── auth/signup/page.tsx      # account creation
│   │   ├── settings/page.tsx         # OAuth connections
│   │   └── api/auth/[...nextauth]/route.ts
│   ├── components/aura/              # AURA-specific widgets (Header, Hero, AgentNetwork, etc.)
│   ├── components/auth/              # UserMenu, Providers
│   ├── components/ui/                # shadcn/ui primitives
│   ├── hooks/                        # use-streaming-orchestration, use-toast, use-mobile
│   └── lib/aura/                     # api.ts (WS+REST), types.ts
├── examples/websocket/               # WS client examples (TS + bash)
├── scripts/                          # python start-up helpers
│   ├── start_aura.sh                 # one-shot: Postgres → seed → backend
│   ├── start_postgres.py             # embedded pgserver + migrations
│   ├── seed_interactions.py          # seed users + interactions
│   ├── start_backend.py              # launch uvicorn (port 8000)
│   ├── start_frontend.py             # launch next dev (port 3000)
│   ├── start-aura-daemon.py          # full-stack daemon
│   ├── recsys_smoke.py               # recsys sanity check
│   ├── test_streaming_ws.py          # WS streaming test
│   └── verify_infra.py               # infra health check
└── aura-backend/                     # ← FastAPI backend
    ├── README.md                     # deep backend docs (architecture, API, config)
    ├── .env.example                  # backend env template (Groq, Postgres, etc.)
    ├── requirements.txt              # Python deps (FastAPI, asyncpg, torch, sb3, qdrant, etc.)
    ├── docker-compose.yml            # Postgres + Redis + Qdrant + ClickHouse + Kafka + MLflow
    ├── migrations/                   # SQL schema + seeds (auto-applied by docker-compose)
    │   ├── 001_init.sql              # tables: users, items, interactions, memory_records, ...
    │   ├── 002_items_seed.sql
    │   ├── 003_knowledge_seed.sql
    │   └── clickhouse_init.sql
    └── app/
        ├── main.py                   # FastAPI app + lifespan
        ├── config.py                 # Pydantic settings
        ├── api/routes.py             # REST + WebSocket routes
        ├── auth/dependencies.py      # JWT validation (NextAuth bridge)
        ├── agents/                   # 8-agent orchestrator (context → memory → preference →
        │                             #   knowledge → recommendation → safety → explanation → RL)
        ├── recommendation/           # ALS CF + Neural CF (PyTorch GMF+MLP)
        ├── data_layer/               # Postgres + Redis + Qdrant + Kafka + ClickHouse
        ├── events/                   # WS hub + event bus
        ├── llm/                      # Groq client + BGE embeddings
        ├── mcp_tools/                # Spotify + GitHub + Google Calendar (OAuth2)
        ├── models/schemas.py         # Pydantic models
        └── rl/                       # PyTorch PPO + stable-baselines3 + MLflow
```

---

## Quick start (5 minutes)

### Prerequisites

| Tool | Version | Why |
|------|---------|-----|
| **Node.js** | ≥ 20 | Next.js 16 runtime |
| **Bun** (recommended) | ≥ 1.1 | Faster install; `bun install` works too |
| **Python** | 3.11 or 3.12 | FastAPI backend |
| **Docker** (optional) | latest | Only if you want the full infra stack (Postgres + Redis + Qdrant + Kafka + ClickHouse + MLflow) |
| **Caddy** (optional) | 2.x | Only if you want the gateway on port 81 |

> **Without Docker**, AURA still runs — it uses an embedded Postgres (`pgserver`) and in-process fallbacks for Redis/Qdrant. You only need Docker for the full production-grade stack.

### 1. Unzip & open in VS Code

```bash
unzip aura.zip -d aura
cd aura
code .          # opens VS Code at the project root
```

If you don't have the `code` command on your PATH, open VS Code → File → Open Folder → select the `aura` directory.

### 2. Frontend (Next.js)

```bash
# from project root
cp .env.example .env.local
bun install                       # or:  npm install
bun run db:push                   # creates the SQLite auth DB at ./db/custom.db
bun run dev                       # starts on http://localhost:3000
```

Open http://localhost:3000 — you'll see the sign-in page. Click **"Create an account"** to register your first user, then sign in.

### 3. Backend (FastAPI)

```bash
cd aura-backend
python -m venv .venv
source .venv/bin/activate          # Windows:  .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Optional but recommended:
#   - Set GROQ_API_KEY (free at https://console.groq.com/keys)
#     → enables real LLM explanations
#   - Leave it blank → backend falls back to template explanations

# Option A — embedded Postgres (zero Docker, simplest dev path)
cd ..
python scripts/start_aura.sh

# Option B — full Docker stack (production-grade)
cd aura-backend
docker compose up -d
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Backend health check: http://localhost:8000/api/health → `{"ok": true, ...}`

### 4. Use it

- Sign in at http://localhost:3000/auth/signin
- Click **Run Orchestration** → watch 8 agents stream live over WebSocket
- Click **👍 / 🛒 / ⏭** on recommendations → actions flow to the RL pipeline
- Click **Train Policy** → real PyTorch PPO step runs (with MLflow tracking if available)
- Go to **Settings** → connect Spotify / GitHub / Google Calendar (optional OAuth)

---

## What's new in 0.3.0

| Layer | Status |
|-------|--------|
| **Recommendation rankers** | ALS CF (`implicit`) + Neural CF (PyTorch GMF+MLP) — both real, with blend weights W_CF=0.40, W_NCF=0.30, W_CONTEXT=0.20, W_RL=0.10 |
| **Frontend hero** | Interactive AuraOrb visualizing the 8-agent loop + dark/light theme toggle |
| **Accounts** | Email/password sign-up via NextAuth.js Credentials + Prisma + bcrypt. Optional GitHub/Spotify OAuth. |
| **Per-user personalization** | Every recommendation, RL experience, memory record, and preference profile is keyed on `user_id` (the NextAuth cuid). Different users → different rankings. |
| **Per-user RL** | Each user has their own PPO policy version trajectory. Training steps for one user don't clobber another's policy. |
| **Streaming orchestration** | `POST /api/orchestrate` returns immediately; per-agent progress streams over WebSocket. |
| **Real LLM** | Groq (Llama-3.3-70B) → HuggingFace → template fallback cascade. |
| **Real embeddings** | `sentence-transformers` BGE-small-en-v1.5 (384-dim, CPU). |
| **Real RL** | PyTorch + stable-baselines3 PPO + MLflow + custom Gymnasium env. |
| **Real data layer** | Postgres + Redis + Qdrant + Kafka + ClickHouse — all wired, with graceful in-process fallbacks when individual services are unreachable. |

---

## Accounts & personalization

### Sign up
1. Open http://localhost:3000/auth/signin
2. Click **"Create an account"**
3. Enter email + password → account created in Prisma SQLite DB
4. Sign in → JWT issued, sent as `Authorization: Bearer <jwt>` to FastAPI

### Different users, different recommendations
Every backend endpoint reads `user_id` from the JWT (validated via `python-jose`). The recommendation agent blends per-user CF scores, per-user Neural CF scores, per-user context, and per-user RL policy outputs. Sign in as user A → see A's recs. Sign out, sign in as user B → see B's recs.

### Per-user RL
The RL pipeline maintains a per-user experience buffer and a per-user policy version counter. When you click 👍/🛒/⏭ on a rec, the action is logged with your `user_id`. When you click **Train Policy**, PPO runs on **your** experiences only. The metrics panel shows your `policy_version`, `samples_seen`, `cumulative_reward`.

---

## Configuration

See [`aura-backend/README.md`](./aura-backend/README.md) for the full configuration reference (LLM providers, embeddings, RL, feature flags, API endpoints, WebSocket events).

Key env files:

| File | Purpose |
|------|---------|
| `.env.local` (root) | Frontend: `NEXTAUTH_SECRET`, OAuth creds, `DATABASE_URL` |
| `aura-backend/.env` | Backend: `GROQ_API_KEY`, Postgres, Redis, Qdrant, Kafka, ClickHouse, feature flags |

---

## Troubleshooting

**`bun install` fails** → try `npm install` instead. The lock file is `bun.lock`; if you switch to npm, delete `bun.lock` and let npm regenerate `package-lock.json`.

**Backend `ModuleNotFoundError: No module named 'app'`** → make sure you're running uvicorn from inside `aura-backend/`, not the project root.

**Frontend can't reach backend** → check that `aura-backend/.env` has `CORS_ORIGINS=["http://localhost:3000"]` (it does by default).

**NextAuth error "JWT secret missing"** → set `NEXTAUTH_SECRET` in `.env.local` to a 32+ char string. Use `openssl rand -hex 32`.

**No recommendations appearing** → run `python scripts/seed_interactions.py` to seed sample data, or click around the dashboard to generate interactions.

**Groq LLM not working** → set `GROQ_API_KEY` in `aura-backend/.env`. Without it, the Explanation Agent falls back to template strings.

---

## License

MIT
