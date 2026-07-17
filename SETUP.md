# AURA — VS Code Setup Walkthrough

This guide walks you through opening the AURA zip in VS Code on your local machine and getting the full stack running. Follow it top-to-bottom; each section assumes the previous one is done.

---

## 1. Prerequisites

Install these once on your machine:

| Tool | Min version | Install link | Why |
|------|-------------|--------------|-----|
| **Node.js** | 20 LTS | https://nodejs.org/ | Next.js 16 runtime |
| **Bun** (recommended) | 1.1 | https://bun.sh/ | Faster package install; optional — `npm` works too |
| **Python** | 3.11 or 3.12 | https://www.python.org/downloads/ | FastAPI backend |
| **Docker Desktop** (optional) | latest | https://www.docker.com/products/docker-desktop/ | Only for the full infra stack (Postgres + Redis + Qdrant + Kafka + ClickHouse + MLflow). Without Docker, AURA uses embedded Postgres + in-process fallbacks. |
| **Caddy** (optional) | 2.x | https://caddyserver.com/docs/install | Gateway on port 81. Without Caddy, just hit port 3000 directly. |
| **VS Code** | latest | https://code.visualstudio.com/ | Editor |

### Recommended VS Code extensions

Open the Extensions panel (`Ctrl+Shift+X` / `Cmd+Shift+X`) and install:

- **Python** (ms-python.python) — Python language support + debugger
- **Pylance** (ms-python.vscode-pylance) — fast type checking
- **ESLint** (dbaeumer.vscode-eslint) — JS/TS linting
- **Tailwind CSS IntelliSense** (bradlc.vscode-tailwindcss) — Tailwind class autocomplete
- **Prisma** (Prisma.prisma) — schema highlighting + format
- **PostgreSQL** (ckolkman.vscode-postgres) — query the AURA DB
- **REST Client** (humao.rest-client) — hit AURA endpoints from `.http` files

---

## 2. Unzip & open

```bash
# macOS / Linux
unzip aura.zip -d aura
cd aura
code .

# Windows PowerShell
Expand-Archive aura.zip -DestinationPath aura
cd aura
code .
```

VS Code opens at the project root. You should see:

```
aura/
├── README.md
├── SETUP.md                    ← this file
├── package.json
├── src/                        ← Next.js frontend
├── aura-backend/               ← FastAPI backend
├── prisma/
├── scripts/
├── examples/
└── ...
```

---

## 3. Frontend setup

Open a VS Code terminal: `Terminal → New Terminal` (or `` Ctrl+` ``).

```bash
# 1. Create your local env file
cp .env.example .env.local

# 2. (Optional) Generate a strong NextAuth secret
#    macOS / Linux:
openssl rand -hex 32
#    Copy the output, paste into .env.local as:
#    NEXTAUTH_SECRET=<your-generated-string>

# 3. Install dependencies
bun install
#    or if you prefer npm:
#    npm install

# 4. Initialize the auth database (SQLite at ./db/custom.db)
bun run db:push
#    or:  npx prisma db push

# 5. Start the dev server
bun run dev
#    or:  npm run dev
```

You should see:

```
▲ Next.js 16.x.x
- Local:   http://localhost:3000
✓ Ready in 1.2s
```

Open http://localhost:3000 — you'll be redirected to `/auth/signin`.

> **Keep this terminal open.** The frontend runs here. Open a **new terminal** for the backend steps below (Terminal → New Terminal, or the `+` icon).

---

## 4. Backend setup

In a new terminal:

```bash
cd aura-backend

# 1. Create a Python virtual environment
python -m venv .venv

# 2. Activate it
#    macOS / Linux:
source .venv/bin/activate
#    Windows PowerShell:
.venv\Scripts\Activate.ps1

# 3. Install Python dependencies
#    (this takes ~3-5 minutes the first time — torch + sentence-transformers are large)
pip install -r requirements.txt

# 4. Create your local env file
cp .env.example .env

# 5. (Optional but recommended) Get a free Groq API key
#    Go to https://console.groq.com/keys
#    Create a key, then edit .env:
#    GROQ_API_KEY=gsk_your_key_here
#    This enables real LLM explanations. Without it, explanations fall back to templates.

# 6. Choose your infra path:
```

### Path A — Embedded Postgres (zero Docker, fastest)

```bash
# From aura-backend/, go back to project root
cd ..

# Run the one-shot startup script
# This: starts embedded Postgres → applies migrations → seeds data → launches uvicorn
python scripts/start_aura.sh

 cd C:\Users\SriHarishAnandhan\Downloads\Aura\aura-backend
>> .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level info

```

Wait until you see:
```
[4/4] Verifying backend…
  ✓ backend healthy
  ✓ recsys rankers available
```

Backend is now live at http://localhost:8000.

### Path B — Full Docker stack (production-grade)

```bash
# From aura-backend/
docker compose up -d

# Wait for all containers to be healthy (~30s)
docker compose ps

# Apply migrations + seed data (auto-applied by docker-compose entrypoint,
# but if you need to re-run):
docker compose exec postgres psql -U aura -d aura -f /docker-entrypoint-initdb.d/001_init.sql

# Start the backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

### Verify backend health

Open http://localhost:8000/api/health in your browser, or:

```bash
curl http://localhost:8000/api/health
# {"ok": true, "service": "aura-backend", ...}

curl http://localhost:8000/api/recsys/status
# {"available": true, "cf": "implicit.ALS", "neural_cf": "torch", ...}
```

---

## 5. Sign up & sign in

1. Open http://localhost:3000/auth/signin
2. Click **"Create an account"** (or go to http://localhost:3000/auth/signup)
3. Enter email + password → click **Sign up**
4. You'll be redirected back to sign-in. Enter the same email + password.
5. You land on the dashboard.

You now have a real account in the SQLite auth DB. The JWT issued by NextAuth is sent to FastAPI as `Authorization: Bearer <jwt>`, where it's validated with `python-jose` using the same `NEXTAUTH_SECRET`.

---

## 6. Run an orchestration

1. On the dashboard, click **Run Orchestration** (top-right of the agent network panel).
2. The 8-agent loop starts. Each agent node lights up amber while running, green when complete, with its latency in ms.
3. Recommendations + LLM-generated explanations appear at the bottom.
4. Click **👍 / 🛒 / ⏭** on any recommendation → action flows to your per-user RL experience buffer.
5. Click **Train Policy** in the RL panel → real PyTorch PPO step runs.

---

## 7. Multiple users = multiple personalized profiles

AURA personalizes at the user level. Try it:

1. Sign out (top-right user menu → Sign out).
2. Sign up as a second user with a different email.
3. Run an orchestration → you'll see different recommendations because:
   - CF ranker pulls from this user's interaction history (empty initially → cold-start fallback to popularity)
   - Neural CF starts from a cold state for this user
   - RL policy version is 0 for this new user (no training history yet)
4. Like / purchase / skip a few items → those are logged with this user's `user_id`.
5. Run another orchestration → recommendations now reflect this user's preferences.
6. Click **Train Policy** → PPO trains on this user's experiences only.

The `user_id` is the NextAuth cuid (e.g. `clxxxxxxxxxxxxxxxxx`). It's:
- Stored in the JWT (signed with `NEXTAUTH_SECRET`)
- Sent to FastAPI as `Authorization: Bearer <jwt>`
- Validated by `app/auth/dependencies.py:get_current_user()`
- Used as the partition key in `interactions`, `memory_records`, `rl_experiences`, `rl_policy_versions`, etc.

---

## 8. Optional: Caddy gateway

If you want a single entry point on port 81 (instead of hitting 3000 directly):

```bash
# Install Caddy: https://caddyserver.com/docs/install
caddy run --config Caddyfile
```

Now http://localhost:81 proxies to http://localhost:3000.

---

## 9. Common VS Code workflows

### Debug the frontend
- Open `src/app/page.tsx`
- Set a breakpoint inside a component
- Press `F5` → choose "Next.js" debug config (VS Code auto-creates one if missing)

### Debug the backend
- Open `aura-backend/app/main.py`
- Set a breakpoint in the lifespan
- Install the Python extension's debug adapter
- Press `F5` → choose "Python: FastAPI" debug config

### Hot reload
- Frontend: `bun run dev` already hot-reloads on save
- Backend: `uvicorn --reload` restarts on save

### Query the auth DB
- Install the PostgreSQL VS Code extension (works for SQLite too via the SQLTools SQLite driver)
- Or just use Prisma Studio:
  ```bash
  bunx prisma studio
  ```
  Opens http://localhost:5555 — browse the `User` and `Account` tables.

### Query the AURA DB
- If using Docker: connect to `localhost:5432`, user `aura`, password `aura`, db `aura`
- If using embedded Postgres: it listens on a Unix socket at `aura-backend/pgdata/` — use `psql -h /path/to/pgdata -U aura aura`

---

## 10. Troubleshooting

### `bun install` fails with version conflict
Delete `bun.lock` and use npm instead:
```bash
rm bun.lock
npm install
```

### Python `pip install` fails on `torch`
On Apple Silicon, install the MPS build:
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```
Then re-run `pip install -r requirements.txt` (it'll skip torch since it's already installed).

### `prisma db push` fails
Make sure `DATABASE_URL` in `.env.local` is set to `file:./db/custom.db` and the `db/` directory exists (create it: `mkdir -p db`).

### Frontend "Unauthorized" on API calls
The JWT isn't being sent. Check:
1. `NEXTAUTH_SECRET` in `.env.local` matches `NEXTAUTH_SECRET` in `aura-backend/.env` (must be identical)
2. You're signed in (top-right shows your name, not "Sign in")
3. Browser DevTools → Application → Cookies → `next-auth.session-token` exists

### Backend "JWT validation failed"
Same cause as above — secret mismatch. Generate one with `openssl rand -hex 32` and put it in BOTH `.env.local` and `aura-backend/.env`.

### No recommendations / "cold start"
Sign up as a new user → empty history → CF returns popularity fallback. Run orchestration a few times, click actions, then re-run. Or seed sample data:
```bash
cd aura-backend
python ../scripts/seed_interactions.py
```

### Groq LLM returns 429 (rate limit)
Free tier is generous but not unlimited. Wait 60s, or switch to template mode by leaving `GROQ_API_KEY=` empty in `.env`.

### Docker `port already allocated`
Another container or local service is using the port. Either stop it or change the port mapping in `aura-backend/docker-compose.yml`.

### WebSocket not connecting
Check browser console. The WS URL is `ws://localhost:8000/api/ws`. If you're using Caddy on 81, the WS proxy needs an upgrade header — see the `Caddyfile` for the correct config (already included).

---

## 11. Next steps

- Read [`aura-backend/README.md`](./aura-backend/README.md) for the full API reference, configuration details, and architecture deep dive.
- Explore `src/components/aura/` to see how the dashboard widgets talk to the backend.
- Check `examples/websocket/` for a minimal WS client (useful for scripting the orchestrator).
- Read `src/components/aura/Hero.tsx` + `AuraOrb.tsx` for the interactive hero visual + theme toggle.

Happy hacking! 🎯
