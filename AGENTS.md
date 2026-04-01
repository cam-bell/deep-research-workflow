# AGENTS.md — Deep Research Workflow

Persistent context for Codex. Read this at the start of every session.
Do not exceed 500 lines. Do not add content that only applies to one task.

---

## What This Project Is

An enterprise knowledge intelligence platform built on top of an existing
multi-agent research pipeline. The agent architecture is complete and
deployed. This project adds a RAG layer, evaluation harness, FastAPI API,
React frontend, and observability — without touching the existing agents.

The product story: a RAG system that answers technical and operational
questions against a curated corpus of engineering documentation, mimicking
what a B2B SaaS engineering organisation would build for internal use.

---

## ⛔ DO NOT CHANGE — Ever

These files and folders must never be modified, refactored, or "improved":

```
agents/             — all agent files, do not touch
app.py              — Hugging Face Spaces entrypoint, do not touch
requirements.txt    — HF Spaces dependencies, do not touch
```

If a task appears to require changes to any of the above, stop and ask
for clarification. Do not proceed with modifications to these files.

The agents are:
- `clarify_agent.py` — sequential clarifying questions
- `router_agent.py` — classifies query into quick/deep/technical/comparative
- `planner_agent.py` — produces WebSearchPlan
- `search_agent.py` — executes individual web searches
- `writer_agent.py` — synthesises findings into ReportData
- `evaluator_agent.py` — scores report quality, drives revision loop
- `email_agent.py` — sends final report
- `research_manager.py` — orchestrates all agents

Integration point: `research_manager.py` calls `perform_searches()`.
The RAG retriever plugs in here — before web search, not instead of it.

---

## Repository Structure

```
deep-research-workflow/
├── agents/                  ← DO NOT TOUCH
│   ├── clarify_agent.py
│   ├── router_agent.py
│   ├── planner_agent.py
│   ├── search_agent.py
│   ├── writer_agent.py
│   ├── evaluator_agent.py
│   ├── email_agent.py
│   └── research_manager.py
├── app.py                   ← DO NOT TOUCH (HF entrypoint)
├── requirements.txt         ← DO NOT TOUCH (HF dependencies)
├── rag/                     ← Phase 1: ingestion + retrieval
│   ├── ingest.py            — fetch, chunk, embed, upsert corpus
│   ├── retrieve.py          — hybrid BM25 + pgvector retrieval
│   └── chunker.py           — recursive character splitting logic
├── eval/                    ← Phase 2: evaluation harness
│   ├── queries.json         — 25 fixed queries with reference answers
│   ├── run_ragas.py         — RAGAS evaluation script
│   ├── run_judge.py         — LLM-as-judge script
│   ├── run_benchmark.py     — routing benchmark across all 4 paths
│   └── results/
│       └── baseline.md      — committed baseline scores
├── api/                     ← Phase 3: FastAPI service
│   ├── main.py              — FastAPI app, lifespan, middleware
│   ├── auth.py              — JWT register/login/middleware
│   ├── sessions.py          — session endpoints
│   ├── models.py            — SQLAlchemy models
│   └── schemas.py           — Pydantic request/response schemas
├── frontend/                ← Phase 3: React app
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── SessionPanel.tsx
│   │   │   ├── ResearchPanel.tsx
│   │   │   └── CitationCard.tsx
│   │   └── lib/
│   │       └── api.ts       — typed API client
│   ├── package.json
│   └── vite.config.ts
├── docs/
│   ├── specs/               — phase task specs (Codex reads these)
│   ├── architecture.md      — decisions Codex must not second-guess
│   ├── design-decisions.md  — written rationale per decision
│   └── evaluation.md        — baseline scores and methodology
├── .github/
│   └── workflows/
│       ├── ci.yml           — eval regression on every PR
│       ├── deploy-hf.yml    — push Gradio files to HF remote on main
│       └── deploy-railway.yml — deploy FastAPI to Railway on main
├── Dockerfile               — FastAPI service only
├── docker-compose.yml       — local dev: FastAPI + Supabase config
└── AGENTS.md                — this file
```

---

## Commands

### Run locally

```bash
# Install dependencies (uses uv)
uv sync

# Run Gradio demo (HF entrypoint)
uv run python app.py

# Run RAG ingestion (Phase 1)
uv run python rag/ingest.py --source gitlab-handbook
uv run python rag/ingest.py --source stripe-docs
uv run python rag/ingest.py --source anthropic-docs
uv run python rag/ingest.py --source openai-docs
uv run python rag/ingest.py --source aws-waf
uv run python rag/ingest.py --source engineering-rfcs

# Run full ingestion pipeline
uv run python rag/ingest.py --all

# Run evaluation harness (Phase 2)
uv run python eval/run_ragas.py
uv run python eval/run_judge.py
uv run python eval/run_benchmark.py

# Run FastAPI service (Phase 3)
uv run uvicorn api.main:app --reload --port 8000

# Run full local stack
docker-compose up

# Run React frontend (Phase 3)
cd frontend && npm install && npm run dev
```

### Git remotes

```bash
# Push to GitHub (source of truth)
git push origin main

# Push Gradio files only to Hugging Face
git subtree push --prefix=. huggingface main
# OR let GitHub Actions handle it automatically on merge to main
```

### Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Run eval regression subset (5 queries, used in CI)
uv run python eval/run_ragas.py --subset ci

# Check a single retrieval
uv run python rag/retrieve.py --query "What is GitLab's policy on blameless post-mortems?"
```

---

## Environment Variables

Required in `.env` (never commit this file):

```
OPENAI_API_KEY=
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
SUPABASE_DB_URL=          # postgres connection string for pgvector
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=            # https://cloud.langfuse.com
JWT_SECRET=               # random 32-char string
SENDGRID_API_KEY=         # existing, already in use by email_agent
TAVILY_API_KEY=           # required when SEARCH_PROVIDER=tavily
SEARCH_PROVIDER=          # optional: "openai" (default) or "tavily"
```

In CI/CD: set all of the above as GitHub Secrets. They are referenced
in `.github/workflows/ci.yml` as `${{ secrets.OPENAI_API_KEY }}` etc.

---

## Coding Conventions

- **Async throughout**: all I/O operations must be `async def`. No blocking calls.
- **Pydantic for all contracts**: no raw dicts crossing function boundaries.
  Every function input/output that crosses a module boundary uses a Pydantic model.
- **Type hints required**: all function signatures must have full type hints.
- **No print() in production code**: use `logging.getLogger(__name__)`.
- **Error handling**: all external calls (OpenAI, Supabase, LangFuse) must be
  wrapped in try/except with structured logging on failure.
- **Fallback pattern**: if RAG retrieval returns 0 results, fall back to web
  search. Never raise an exception to the user for a retrieval miss.
- **Citation metadata**: every retrieved chunk must carry `source_name`,
  `source_url`, `section_title` through to the writer. Do not drop metadata.

---

## Architecture Constraints

These are deliberate decisions. Do not change them without being asked to:

1. **pgvector, not Pinecone**: vector storage lives in Supabase alongside
   relational data. Do not add a Pinecone dependency.

2. **Hybrid retrieval**: BM25 keyword search + pgvector cosine similarity,
   merged with reciprocal rank fusion (RRF). Do not replace with vector-only
   or keyword-only retrieval.

3. **RAG before web search**: the retriever is called first in
   `research_manager.py`. Web search is the fallback for out-of-corpus queries.
   Do not invert this order.

4. **512-token chunks, 64-token overlap**: this is the baseline chunking
   configuration. Do not change it without updating `docs/design-decisions.md`
   and running the eval harness to confirm impact.

5. **text-embedding-3-small**: the embedding model. Do not swap to a different
   model without updating the eval baseline.

6. **JWT auth, not OAuth2**: the FastAPI API uses JWT (python-jose). Do not
   add OAuth2 dependencies.

7. **Gradio stays on HF Spaces**: `app.py` and the agents are deployed to
   Hugging Face via a secondary git remote. The FastAPI service and React app
   are separate deployments. Do not merge these surfaces.

---

## Corpus Sources

The RAG corpus is sourced from these public documents:

| Source | Target chunks |
|--------|--------------|
| GitLab Handbook (handbook.gitlab.com) | ~1,500 |
| Stripe API Docs (stripe.com/docs) | ~600 |
| Anthropic API Docs (docs.anthropic.com) | ~200 |
| OpenAI API Docs (platform.openai.com/docs) | ~200 |
| AWS Well-Architected Framework | ~450 |
| Public Engineering RFCs (Cloudflare, Uber, Netflix, GitHub) | ~150 |

Total target: 3,000+ chunks. Minimum to proceed: 500 chunks.

Each chunk must store metadata: `source_name`, `source_url`,
`section_title`, `date_fetched`.

---

## Phase Overview

| Phase | What it adds | Verification |
|-------|-------------|--------------|
| 1 — RAG | Ingestion + retrieval + agent integration | Query returns cited source |
| 2 — Eval | RAGAS harness + routing benchmark + CI gate | Baseline scores committed |
| 3 — API + Frontend | FastAPI + React + Railway + Vercel | Live demo URL works |
| 4 — Polish | README + docs + demo GIF + screenshots | Interview-ready |

See `docs/specs/` for detailed task breakdowns per phase.

---

## Session Start Prompt

Begin every Codex session with:

> Read AGENTS.md and the relevant phase spec in docs/specs/. Do not write
> any code yet. Tell me what you understand about the current task and
> what files you will need to read before starting.

Only after confirmation, begin the first task in the spec.
