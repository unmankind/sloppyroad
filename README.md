# SloppyRoad

**AI-generated progression fantasy web novels.** A parody of Royal Road with a sardonic, self-aware voice. The premise: *"Why worry whether your favorite web novel is AI slop when you could know for sure?"*

Multi-author platform where users generate worlds and write chapter-by-chapter novels with AI. Anonymous readers follow via share links.

**Live at [sloppyroad.com](https://sloppyroad.com)**

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | FastAPI (async, SSE streaming) |
| **Database** | SQLite + aiosqlite (dev) / PostgreSQL 16 (prod), SQLAlchemy 2.0, Alembic |
| **LLM** | LiteLLM (provider-agnostic: Claude, OpenAI, local models) |
| **Frontend** | HTMX + Jinja2 + Tailwind CSS (dark/immersive aesthetic) |
| **Auth** | JWT (passlib + python-jose), cookie-based anonymous readers |
| **Queue** | Redis + arq (async background tasks, pub/sub for SSE, generation locks) |
| **Embeddings** | nomic-embed-text via Ollama (768-dim), sqlite-vec (dev) / pgvector (prod) |
| **Images** | Provider-agnostic (Replicate/flux-schnell, ComfyUI, DALL-E 3, HF-Space) |
| **Testing** | pytest + pytest-asyncio (37 test files, ~600 tests) |
| **Deployment** | Docker Compose (5 services), GitHub Actions CI/CD, Hetzner CPX21 |

## Project Structure

```
src/aiwebnovel/
├── main.py                  # FastAPI app factory + lifespan
├── config.py                # 86 settings via pydantic-settings (AIWN_ prefix)
│
├── auth/                    # JWT, OAuth stubs, CSRF, rate limiting, anon readers
├── db/
│   ├── models.py            # SQLAlchemy ORM (60 tables)
│   ├── schemas.py           # Pydantic serialization models
│   ├── queries.py           # Query helpers
│   ├── session.py           # DB connection management
│   └── vector.py            # sqlite-vec / pgvector abstraction
│
├── api/
│   ├── routes_*.py          # REST API endpoints (16 route files, 69 handlers)
│   └── pages/               # HTML page rendering (13 modules)
│
├── llm/
│   ├── provider.py          # LiteLLM wrapper with cost tracking + retry
│   ├── prompts.py           # All prompt templates (27 templates)
│   ├── parsers.py           # Pydantic models for LLM JSON output
│   └── budget.py            # Token budget enforcement
│
├── story/
│   ├── pipeline.py          # World + chapter generation orchestration
│   ├── seeds.py             # Diversity seed bank (~130 seeds, 9 categories)
│   ├── planner.py           # Arc + chapter planning (3 modes)
│   ├── context.py           # Context assembly + enhanced recap
│   ├── analyzer.py          # Consolidated analysis (2 LLM calls)
│   ├── generator.py         # Chapter text generation
│   ├── validator.py         # Power system validation
│   ├── anti_repetition.py   # Cross-novel repetition detection
│   ├── tags.py              # Author tag system
│   ├── semantic.py          # Semantic search integration
│   ├── extractor.py         # DB extraction from LLM output
│   └── scene_markers.py     # Scene boundary detection
│
├── chekhov/                 # Chekhov gun system (detection, tracking, injection)
├── summarization/           # Chapter/arc summaries, story bible, relevance scoring
├── perspective/             # Per-character knowledge tracking
├── images/                  # Visual asset pipeline (providers, prompts, evolution)
├── worker/
│   ├── tasks.py             # 17 background task functions
│   ├── queue.py             # arq WorkerSettings + cron tasks
│   └── health.py            # Heartbeat, stale detection, recovery
│
├── templates/               # 40 Jinja2 templates (3 base, 28 pages, components)
└── static/                  # Tailwind CSS, HTMX, ambient loader
```

## Core Systems

### World Generation Pipeline
8-stage pipeline run in 3 parallel waves via `asyncio.gather`:
1. **Wave 1** (parallel): Cosmology, Power System, Geography
2. **Wave 2** (parallel): History, Current State
3. **Wave 3** (parallel): Protagonist, Antagonists, Supporting Cast

Each stage uses Claude Haiku 4.5 with structured JSON output parsed by Pydantic models. Diversity seeds (130 seeds across 9 categories including "chaos modifiers") are injected into prompts to ensure unique worlds. An anti-repetition system bans overused names and patterns.

### Chapter Generation
- Redis-locked concurrent generation (one chapter per novel at a time)
- Context assembly: enhanced recap (~1200 tokens) + story bible + character knowledge
- Consolidated analysis: 2 LLM calls (narrative + system) instead of 4, ~40% cost savings
- Power system validation: earned power rules enforced, auto-retry on rejection
- SSE streaming with typewriter effect in browser

### Arc Planning
Three modes: autonomous (AI decides), supervised (AI proposes, author approves), collaborative (author + AI). Bridge chapters between arcs, final arc designation with mandatory resolution.

### Story Bible
Vector-indexed semantic memory using sqlite-vec (dev) / pgvector (prod) with 768-dim nomic-embed-text embeddings. Composite relevance scoring for context retrieval.

### Visual Assets
Provider-agnostic image generation (Replicate/flux-schnell in production). Portrait and map evolution chains that update as characters and the world change. Separate image budget tracking per author and per novel.

### Background Worker
arq-based async worker with:
- Generation tasks (world, arc, chapter, images)
- Cron tasks: stale job detection (every 60s), art queue processing (every 30s), autonomous generation tick, novel stats refresh
- Heartbeat monitoring with automatic recovery of stale jobs

## Database

60 SQLAlchemy 2.0 tables covering:
- Users, auth, author/reader profiles
- Novels, chapters, drafts, summaries
- World building stages (cosmology, geography, history, etc.)
- Characters, relationships, knowledge, power profiles
- Power systems, ranks, disciplines
- Arc plans, chapter plans, plot threads, escalation
- Story bible entries with vector embeddings
- Chekhov guns (foreshadowing tracking)
- Visual assets and generation queue
- Reader influence (signals, oracle questions, butterfly choices, factions)
- LLM and image usage logging, billing
- Notifications, ratings, tags

Migrations managed by Alembic. Dev uses SQLite, production uses PostgreSQL 16.

## Development Setup

### Prerequisites
- Python 3.13+
- Docker + Docker Compose
- Redis (or use Docker)

### Local Development

```bash
# Clone and setup
git clone git@github.com:unmankind/sloppyroad.git
cd sloppyroad
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run with Docker (recommended)
docker compose -f docker-compose.dev.yml up

# Or run directly (needs Redis running)
uvicorn aiwebnovel.main:create_app --factory --reload --port 8003
```

The dev stack uses SQLite (file-based at `./data/aiwebnovel.db`), hot reload, and debug mode.

### Environment Variables

All settings use the `AIWN_` prefix. Key ones:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AIWN_JWT_SECRET_KEY` | Yes | — | JWT signing secret |
| `AIWN_DATABASE_URL` | No | `sqlite+aiosqlite:///./aiwebnovel.db` | Database connection |
| `AIWN_REDIS_URL` | No | `redis://localhost:6379` | Redis connection |
| `AIWN_LITELLM_API_KEY` | Yes | — | LLM provider API key |
| `AIWN_LITELLM_DEFAULT_MODEL` | No | `anthropic/claude-sonnet-4-6` | Default LLM model |
| `AIWN_IMAGE_ENABLED` | No | `false` | Enable image generation |
| `AIWN_IMAGE_PROVIDER` | No | `comfyui` | Image provider (replicate, dall-e-3, hf-space) |
| `AIWN_REPLICATE_API_TOKEN` | No | — | Replicate API token (if using replicate) |

See `src/aiwebnovel/config.py` for all 86 settings.

### Running Tests

```bash
# Full test suite (matches CI)
pytest tests/ -x -q \
  --ignore=tests/test_e2e_integration.py \
  --ignore=tests/test_e2e_pipeline.py

# Quick unit tests
pytest tests/test_seeds.py tests/test_parsers.py tests/test_prompts.py -x

# With coverage
pytest tests/ --cov=aiwebnovel --cov-report=term-missing
```

### Linting

```bash
# Check (matches CI)
ruff check src/ tests/ --select E,F,I

# Auto-fix
ruff check src/ tests/ --select E,F,I --fix
```

## CI/CD Pipeline

### Pull Requests

All changes go through PRs to `main`. The CI pipeline runs automatically:

1. **Lint**: `ruff check src/ tests/ --select E,F,I` — pycodestyle errors, pyflakes, import sorting
2. **Test**: `pytest tests/ -x -q` with in-memory SQLite

Both must pass before merge. PR reviews are required.

### Deployment

Merging to `main` triggers automatic deployment:

1. **Lint + Test** (same as CI)
2. **SSH Deploy** to Hetzner:
   - `git pull` latest code
   - `docker compose build` (rebuilds app + worker images)
   - `docker compose up -d` (rolling restart)
   - Health check loop (60s timeout via `docker exec`)
3. App runs database migrations on startup (Alembic)

### Branch Workflow

```
feature-branch → PR → CI passes → merge to main → auto-deploy
```

- Create feature branches from `main`
- Keep PRs focused — one feature or fix per PR
- CI must pass before merge
- `main` is always deployable

## Production Stack

| Service | Image | Purpose |
|---------|-------|---------|
| `aiwn-app` | Custom (Dockerfile) | FastAPI via gunicorn + uvicorn (2 workers) |
| `aiwn-worker` | Same image | arq background task worker |
| `aiwn-db` | postgres:16-alpine | Primary database |
| `aiwn-redis` | redis:7-alpine | Queue, pub/sub, generation locks |
| `aiwn-caddy` | caddy:2-alpine | Reverse proxy, HTTPS termination |

**Infrastructure**: Hetzner CPX21 (3 vCPU, 4GB RAM) in Ashburn, behind Cloudflare.

## Key Design Decisions

- **LiteLLM for provider agnosticism**: Switch between Claude, OpenAI, or local models via config. No vendor lock-in.
- **Pydantic for all LLM output**: Every LLM response is parsed into a typed Pydantic model. Validation catches malformed output before it hits the database.
- **Redis generation locks**: One generation job per novel at a time. Prevents duplicate chapters and race conditions.
- **Consolidated analysis**: 2 LLM calls instead of 4 per chapter (narrative + system analysis combined). ~40% cost savings.
- **Enhanced recap over full context**: ~1200 token recap replaces sending the full previous chapter, keeping context windows manageable.
- **Chaos seeds with high temperature**: World generation uses 0.95 temperature and mandatory "chaos modifier" seeds to prevent generic, repetitive outputs. Parser constraints are deliberately loose to accommodate creative LLM responses.
- **Heartbeat-based stale detection**: Background jobs update a heartbeat timestamp. A cron task detects jobs that stop updating and recovers them.
- **Separate image budget**: Image generation has its own per-author and per-novel budget, tracked separately from LLM costs.

## LLM Models Used

| Purpose | Model | Temperature |
|---------|-------|-------------|
| World generation (8 stages) | claude-haiku-4-5-20251001 | 0.7–0.95 |
| Chapter generation | claude-sonnet-4-6 | 0.7 |
| Narrative analysis | claude-sonnet-4-6 | 0.7 |
| System analysis (power validation) | claude-3-haiku | 0.7 |
| Image prompt composition | claude-sonnet-4-6 | 0.7 |
| Arc planning | claude-sonnet-4-6 | 0.9 |
| Fallback | gpt-4o-mini | — |

## Contributing

1. Fork and clone the repo
2. Create a feature branch: `git checkout -b my-feature`
3. Make changes, write tests
4. Ensure lint passes: `ruff check src/ tests/ --select E,F,I`
5. Ensure tests pass: `pytest tests/ -x -q --ignore=tests/test_e2e_integration.py --ignore=tests/test_e2e_pipeline.py`
6. Push and open a PR to `main`
7. Wait for CI to pass, then request review

### Working GitHub Issues

All work should be tracked via [GitHub Issues](https://github.com/unmankind/sloppyroad/issues). Follow this workflow:

1. **Investigate** — Read the issue, explore the code, understand root cause and full scope
2. **Comment findings** — Post investigation results on the issue (root cause, affected files, scope)
3. **Implement** — Make changes, test locally, lint
4. **Commit with closing keyword** — Use `Closes #N` or `Fixes #N` in the commit message so GitHub auto-closes the issue on merge
5. **Post resolution comment** — After deploy, comment on the issue with: commits made, what was fixed, production verification results

This keeps each issue as a self-contained record of problem → investigation → solution → verification.

### For AI Agents

Point your agent at this README and `CLAUDE.md` for full project context. The `CLAUDE.md` file contains detailed architecture notes, agent team structure, and implementation phases. Key files to understand the codebase:

- **Entry point**: `src/aiwebnovel/main.py`
- **Config**: `src/aiwebnovel/config.py` (all settings)
- **Models**: `src/aiwebnovel/db/models.py` (60 tables)
- **Core pipeline**: `src/aiwebnovel/story/pipeline.py`
- **Prompts**: `src/aiwebnovel/llm/prompts.py` (27 templates)
- **Parsers**: `src/aiwebnovel/llm/parsers.py` (LLM output schemas)
- **Worker**: `src/aiwebnovel/worker/tasks.py` (17 background tasks)
- **Seeds**: `src/aiwebnovel/story/seeds.py` (world diversity system)
