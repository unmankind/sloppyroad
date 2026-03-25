# SloppyRoad — Certified AI Slop (formerly AIWN 2.0)

## Project Overview
**SloppyRoad** (sloppyroad.com) — AI-generated progression fantasy web novels. A sardonic, self-aware web fiction platform. The premise: "Why worry whether your favorite web novel is AI slop when you could know for sure?" Multi-user platform where authors generate worlds and write chapter-by-chapter novels with AI. Anonymous readers follow via share links.

## Tech Stack
- **Backend**: FastAPI (async, SSE streaming, Pydantic built-in)
- **Database**: SQLite + aiosqlite (dev) / PostgreSQL (prod) via SQLAlchemy 2.0 + Alembic
- **LLM**: LiteLLM (provider-agnostic: Claude, OpenAI, local models)
- **Frontend**: HTMX + Jinja2 + Tailwind CSS (dark/immersive mystery/whimsy aesthetic)
- **Auth**: JWT (passlib + python-jose), OAuth2 stubs, cookie-based anonymous readers
- **Billing**: Stripe for author payment, LLM cost tracking + separate image cost tracking (premium)
- **Queue**: Redis + arq (async background task queue, pub/sub for streaming, generation locks)
- **Embeddings**: nomic-embed-text via Ollama (768-dim), sqlite-vec (dev) / pgvector (prod)
- **Images**: Provider-agnostic (ComfyUI, Replicate, DALL-E), separate premium budget
- **Validation**: Pydantic v2 for all LLM output parsing
- **Testing**: pytest + pytest-asyncio
- **Deployment**: Docker Compose (app, db, worker, redis, caddy), port 8003

## Architecture Reference
- Full architecture: `ARCHITECTURE.md` — all systems, DB schemas (~60 tables), algorithms, prompt templates
- Implementation plan: `IMPLEMENTATION_PLAN.md` — 8 agent codenames, execution order, cross-agent contracts, checklists

## Core Systems
1. **8-Stage World Pipeline**: Cosmology → Power System → Geography → History → Current State → Protagonist → Antagonists → Supporting Cast
2. **Power System Tracking**: Earned Power validator (LLM-based 4-rule eval via consolidated system analysis, score < 0.5 = rejected, auto-retry once then flag)
3. **Escalation Engine**: Scope tiers with 6-phase cycle, foreshadowing seeds, tension curve management
4. **Docker Deployment**: 5-service stack (app, db, worker, redis, caddy), port 8003
5. **Visual Asset Pipeline**: Text-to-image for maps/portraits/sigils, evolution chains, provider-agnostic, separate premium budget
6. **Reader Influence**: Sentiment signals, Oracle questions, Butterfly choices, faction alignment — gravitational pull, not direct control
7. **Living Story Bible**: Vector-indexed semantic memory (sqlite-vec/pgvector, 768-dim), composite relevance scoring, character knowledge tracking
8. **Perspective System**: Worldview filters, POV rotation, narrative voice differentiation, divergence tracking
9. **Auth & Multi-Tenancy**: JWT authors, cookie-based anonymous readers (optional account claiming), Stripe billing, per-author isolation
10. **Arc & Chapter Planning**: 3 modes (autonomous/supervised/collaborative), arc proposal → review → approval, bridge chapters between arcs, final arc designation with mandatory resolution
11. **Chapter Revision**: Draft versioning, auto-retry on rejection, author flag workflow
12. **Cost Management**: Per-model LLM pricing + per-provider image pricing, per-novel budgets, daily autonomous budget caps
13. **Context Window Management**: Dynamic model-aware token budgets, enhanced recap (~1200 tokens replaces full previous chapter), priority-based truncation
14. **Generation Workflow**: Reader-triggered generation within arcs, author-triggered always, Redis concurrency lock, generation_jobs with heartbeat
15. **Autonomous Mode**: Configurable cadence (default 24h), auto-arc planning, daily budget cap, skip-arc-boundaries option, 9 stop conditions
16. **Streaming**: SSE via Redis pub/sub, typewriter effect in browser, status events during pipeline stages
17. **Worker Resilience**: Heartbeat tracking, stale job detection, recovery on startup, dead letter handling
18. **Notifications**: In-app (bell icon, polling), types: arc_plan_ready, chapter_failed, new_chapter, budget_warning
19. **Novel Discovery**: Public browse with filters/sort, leaderboard (most read, active, rated, rising), ratings, tags
20. **Story Completion**: Final arc designation, mandatory resolution of threads/guns, completion summary, "THE END" page
21. **Rate Limiting**: Redis sliding window, 5 tiers (auth, generation, reader, browse, API)
22. **Consolidated Analysis**: 2 LLM calls instead of 4 (narrative + system), ~40% cost savings, graceful fallback

## Project Structure
```
src/
  aiwebnovel/
    __init__.py
    main.py              # FastAPI entry + middleware (auth, rate limit, SSE)
    config.py            # Settings via pydantic-settings
    auth/
      jwt.py             # JWT creation + validation
      dependencies.py    # get_current_author, get_reader_or_anonymous
      oauth.py           # OAuth2 provider stubs
      middleware.py       # Anonymous reader cookie + rate limiting middleware
    db/
      models.py          # SQLAlchemy ORM models (~60 tables)
      session.py         # DB session management
      queries.py         # Common query helpers
      schemas.py         # Pydantic serialization models
      vector.py          # Vector store abstraction (sqlite-vec / pgvector)
    llm/
      provider.py        # LiteLLM wrapper with cost tracking
      prompts.py         # All prompt templates
      parsers.py         # Pydantic models for LLM JSON output
      budget.py          # LLM + image budget enforcement
    story/
      planner.py         # Arc + chapter planning (3 modes), bridge chapters, final arcs
      context.py         # Context assembly + dynamic token budgets + enhanced recap
      generator.py       # LLM generation call with streaming
      analyzer.py        # Consolidated analysis (2 calls: narrative + system)
      extractor.py       # DB extraction from analysis
      validator.py       # Validation from consolidated system analysis
      pipeline.py        # Orchestrates all stages, Redis lock, generation_jobs
      revision.py        # Draft versioning + auto-retry
      semantic.py        # Semantic context assembly
    chekhov/
      detector.py        # Emergent gun detection
      tracker.py         # Pressure scoring, lifecycle
      injector.py        # Context injection for guns
    perspective/
      filter.py          # Worldview-based narrative filtering
      knowledge.py       # Per-character knowledge tracking
    summarization/
      chapter_summary.py # Standard + enhanced recap summaries
      arc_summary.py
      story_bible.py
      relevance.py
    worker/
      queue.py           # arq setup + cron tasks
      tasks.py           # Background task implementations
      health.py          # Heartbeat, stale detection, recovery
    images/
      provider.py        # Image gen provider abstraction + cost logging
      evolution.py       # Portrait + map evolution chains
      prompts.py         # Narrative-to-image prompt composition
    api/
      routes_auth.py
      routes_dashboard.py
      routes_story.py
      routes_planning.py
      routes_chapter.py
      routes_characters.py
      routes_world.py
      routes_chekhov.py
      routes_reader.py
      routes_browse.py   # Novel discovery + leaderboard
      routes_notifications.py
      routes_stream.py   # SSE streaming endpoint
    templates/
    static/
tests/
```

## Agent Team (Implementation)
1. **FOUNDATION** — scaffold, config, Docker, CI, auth module, rate limiting, SSE infra
2. **BEDROCK** — SQLAlchemy models (~60 tables), migrations, queries, schemas
3. **ORACLE** — LiteLLM provider, prompts (consolidated analysis, enhanced recap), parsers, budget enforcement
4. **WEAVER** — story pipeline (with Redis lock, streaming, heartbeat), planning (bridge chapters, final arcs), consolidated analysis, context assembly (enhanced recap)
5. **LIBRARIAN** — story bible, vector search (sqlite-vec/pgvector, 768-dim), semantic retrieval, character knowledge
6. **CARTOGRAPHER** — frontend UI/UX, API routes (including browse, leaderboard, notifications, SSE stream), templates (mystery/whimsy aesthetic)
7. **ARTIFICER** — background workers (with cron tasks, heartbeat, recovery), image pipeline (with cost tracking), asset management
8. **SENTINEL** — test suite, fixtures, integration tests, security tests, worker tests

## Execution Order
1a: FOUNDATION + BEDROCK (parallel)
1b: ORACLE (needs config)
1c: WEAVER + LIBRARIAN (parallel, need BEDROCK + ORACLE)
1d: CARTOGRAPHER (needs WEAVER pipeline interfaces)
1e: ARTIFICER (needs models + queue infra)
Throughout: SENTINEL

## Implementation Phases
1. **MVP**: Scaffold, Docker, models, auth, LiteLLM, world pipeline, chapter pipeline (with streaming + generation lock), summaries (including enhanced recap), basic UI
2. **Deep Tracking**: Relational extraction, Story Bible + vector search (sqlite-vec, 768-dim), arc summaries, relationship graph
3. **Chekhov System**: Detection, pressure scoring, lifecycle, dashboard
4. **Perspective System**: Worldview profiles, voice, POV generation, divergence tracking, character knowledge
5. **Visual Assets**: Image providers, art triggers, evolution chains, gallery, image cost tracking (premium)
6. **Reader Influence**: Engagement tracking, Oracle, Butterfly, factions, reader-triggered generation
7. **Polish**: Browse/leaderboard, notifications, autonomous mode, final arcs, story completion, EPUB, audio (future)

## Current Status
**Phase**: MVP through Phase 5 substantially complete. Phases 1-3 fully working, Phase 4 (Perspective) ~15% (only knowledge.py, filter.py not implemented), Phase 5 (Images) working with Replicate including art regeneration with author feedback.

**Security audit**: Comprehensive audit completed March 2026 — 40 issues filed, 34 fixed across 5 waves (auth ownership checks, XSS, worker reliability, budget race conditions, CI/CD improvements). PGVectorStore fully implemented (not a stub).

**Brand**: SloppyRoad — sardonic, self-aware AI slop. All user-facing text uses lighthearted, self-deprecating humor about AI-generated content.

## Key Conventions

### Image Asset URLs
Art assets stored in `ArtAsset.file_path` use relative paths (e.g., `14/portrait_76/v1.png`). When building URLs for templates, **always** use `/assets/images/{file_path}`:
```
CORRECT: /assets/images/14/portrait_76/v1.png
WRONG:   /assets/14/portrait_76/v1.png
```

### Character Identity System
Characters are pre-rolled with names, sex, pronouns, and physical traits in `story/names.py` before the LLM generates them. These are stored as structured fields on the `Character` model (`sex`, `pronouns`, `physical_traits` JSON, `visual_appearance` text) and flow into chapter context, portrait generation, and character pages.

## Deployment & CI/CD

### Production Stack
- **Stack**: Docker Compose — app (gunicorn+uvicorn), worker (arq), PostgreSQL 16, Redis 7, Caddy
- **Domain**: sloppyroad.com (behind Cloudflare)

### CI/CD Pipeline (GitHub Actions)
- **On PR to main**: `.github/workflows/ci.yml` — lint (ruff) + test (pytest)
- **On push to main**: `.github/workflows/deploy.yml` — lint + test + SSH deploy to production
- **Deploy process**: `git pull` → `docker compose build` → `docker compose up -d` → health check

### Development Workflow
1. **Feature branches**: Create branch from `main`, make changes, push
2. **PRs required**: All changes go through PR → CI passes → merge to main
3. **Auto-deploy**: Merging to `main` triggers deploy pipeline automatically
4. **Local dev**: `docker compose -f docker-compose.dev.yml up` (hot reload, SQLite, debug mode)
5. **Production**: `docker-compose.yml` (PostgreSQL, no debug, Caddy reverse proxy)

### Secrets (NEVER commit)
- Production `.env` lives on the server (not in git) — see `.env.example` for required variables
- GitHub Actions secrets: `DEPLOY_SSH_KEY`, `DEPLOY_HOST`
- Store API keys in a secrets manager; retrieve at runtime, never hardcode
