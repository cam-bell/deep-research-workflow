# Architecture — Decisions Codex Must Not Second-Guess

This document records deliberate architectural decisions. When Codex
reads this, it must treat these as fixed constraints, not suggestions.
Do not "improve" any of these choices without being explicitly asked to.

---

## System Topology

```
User
 ├── Gradio (HF Spaces) ──────────────────────────────────── always on
 └── React (Vercel) ──→ FastAPI (Railway) ──→ Agent Pipeline
                                          ├──→ RAG Retriever (pgvector)
                                          ├──→ Web Search (fallback)
                                          ├──→ Supabase (sessions + users)
                                          └──→ LangFuse (tracing)
```

The Gradio surface and the React surface are independent. Gradio calls
the agent pipeline directly. The React surface calls FastAPI which calls
the agent pipeline. They share the same agent code but are separate
deployment surfaces with separate entry points.

---

## Agent Pipeline — Fixed

The agent pipeline in `agents/` is the core of the existing project and
must not change. The integration point is `research_manager.py`'s
`perform_searches` method — the RAG retriever plugs in here as a
pre-step before web search.

```
Query → clarify_agent → router_agent → planner_agent
     → [search_with_rag() per item] → writer_agent
     → evaluator_agent → (revision loop) → email_agent
```

The RAG layer is additive. It adds retrieved context before the writer.
It does not replace web search. It does not modify agent logic.

---

## RAG Layer

### Why pgvector, not Pinecone

pgvector lives in the same Supabase instance as relational data (sessions,
users). This means one managed service, one connection pool, one billing
account, and full SQL queryability over vectors. For a corpus of ~3,000
chunks, pgvector performance is more than sufficient. A dedicated vector
DB (Pinecone, Weaviate, Qdrant) would add operational complexity and cost
with no benefit at this scale.

At scale (>1M chunks, <100ms p99 SLA), pgvector would be replaced with
a dedicated vector DB. That is not this project.

### Why hybrid retrieval (BM25 + vector + RRF)

Keyword-only search (BM25) works well for precise queries: "Stripe
idempotency_key parameter", "Claude claude-3-opus-20240229 context window".
It fails on semantic queries: "what does GitLab say about trust between
managers and reports".

Vector-only search works well for semantic queries but misses exact
keyword matches in technical documentation.

RRF fusion (k=60, `score = 1/(60+rank_bm25) + 1/(60+rank_vector)`)
combines both rankings without requiring score normalisation. The k=60
value is the standard default from the original RRF paper. Do not change
this without running the eval harness to confirm impact.

### Chunking: 512 tokens, 64-token overlap

512 tokens fits within the embedding model's effective context window while
being long enough to contain a coherent argument or explanation. 64-token
overlap ensures sentences split across chunk boundaries are captured by
at least one chunk. These are starting values — the eval harness measures
the impact of changing them via RAGAS context_recall scores.

### Embedding model: text-embedding-3-small (1536 dimensions)

Cost: ~$0.02 per million tokens. Already in the OpenAI ecosystem.
1536 dimensions is compatible with pgvector's IVFFlat index.
Upgrading to text-embedding-3-large (3072 dimensions) would require
re-embedding the corpus and recreating the index.

---

## API Layer

### Why FastAPI

Async-native, Pydantic integration, auto-generated OpenAPI docs. The
agent pipeline is already async throughout. FastAPI is the standard
for Python AI backends in 2026.

### Why JWT, not OAuth2

JWT (python-jose, HS256, 7-day expiry) is sufficient for a portfolio
demo with a single user pool. OAuth2 with a provider (Auth0, Supabase
Auth) would be the right call for a production SaaS but adds OAuth
callback flows, provider accounts, and additional surface area.

The `get_current_user` FastAPI dependency is the standard pattern.
If OAuth2 is needed, the dependency can be swapped without changing
session or research endpoints.

### Session persistence schema

```sql
research_sessions (
  id, user_id, query, route,
  report,        -- full markdown report
  sources,       -- jsonb: [{source_name, source_url, section_title}]
  eval_scores,   -- jsonb: {faithfulness, relevancy, context_recall}
  cost_usd,      -- total OpenAI cost for the run
  latency_ms,    -- end-to-end wall clock time
  trace_url,     -- LangFuse trace URL
  created_at
)
```

`sources` and `eval_scores` are JSONB because their schema varies per
run. Everything else is a typed column.

---

## Frontend

### Why React + Vite, not Next.js

The React app is a static site that consumes the FastAPI service. It
has no server-side rendering requirement, no SEO requirement, and no
need for server-side data fetching. Vite builds a static bundle deployed
to Vercel. Next.js SSR would add complexity with no benefit.

### Three panels only

Session history (left), research output with citations (centre), trace
link (top right). This is the full scope. Do not add:
- Analytics dashboards
- Admin panels
- User management UI
- Settings pages
- Model selection UI (route override is sufficient)

### JWT in memory, not localStorage

The JWT is stored in React state, not localStorage. This is a deliberate
security choice: localStorage is accessible to XSS attacks; in-memory
state is not. The trade-off is that the token is lost on page refresh,
requiring re-login. Acceptable for a portfolio demo.

---

## Deployment

### Three live surfaces

| Surface | Host | Cold start | Purpose |
|---------|------|-----------|---------|
| Gradio | HF Spaces | None | Public AI demo, no auth |
| React | Vercel | None | Product demo, shown in interviews |
| FastAPI | Railway | ~20s | Backend for React |

### Two Git remotes

```
origin        → github.com/cam-bell/deep-research-workflow
huggingface   → huggingface.co/spaces/cameronbell/deep-research-workflow
```

GitHub is the source of truth. The HF remote receives only what the
Gradio Space needs: `app.py`, `agents/`, `requirements.txt`.
The GitHub Action handles this on merge to main.

### What Railway receives

The full repo. Railway builds the Dockerfile at the root.
CORS is configured to allow the Vercel origin.
All secrets are set as Railway environment variables, not in the repo.

---

## Observability

### LangFuse

Every `research_manager.run()` call is wrapped in a LangFuse trace.
The trace records: query, route, token counts per agent call, cost_usd,
latency_ms. The trace URL is stored in the session record and surfaced
in the React UI as a one-click link.

LangFuse was chosen over Arize and Helicone because it is purpose-built
for LLM tracing (not general APM), has a generous free tier, and the
trace URL pattern is simple enough to embed in the session record.

---

## What This Project Does Not Do

- Custom model fine-tuning
- WebSocket streaming (SSE is sufficient)
- Multi-tenant data isolation beyond user_id scoping
- Redis caching (query-level embedding cache is a Phase 3 enhancement,
  not a requirement)
- Real-time collaborative sessions
- OAuth2 / social login
- Payment processing
- Analytics beyond LangFuse traces
