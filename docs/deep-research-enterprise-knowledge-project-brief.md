# Project Brief

## Deep Research Workflow

### Enterprise Knowledge Intelligence: RAG + Eval + Full-Stack

- **Author:** Cameron Bell
- **Date:** March 2026
- **Status:** Active — Planning Phase
- **Target:** AI Engineer Portfolio

## 1. Context and Strategic Rationale

This document defines the scope, goals, technical plan, and success criteria for upgrading the Deep Research Workflow from a multi-agent demo into a production-grade AI engineering portfolio project.

### 1.1 Current State

The Deep Research Workflow already demonstrates five core agentic patterns: prompt chaining, routing, parallelization, orchestrator-worker, and evaluator-optimizer. It is deployed on Hugging Face Spaces with a Gradio UI. These are genuine engineering achievements.

What it currently lacks:

- RAG layer — all generation is pure LLM with no retrieved context
- Persistent storage — sessions are ephemeral and cannot be compared or replayed
- Evaluation harness — quality claims are directional, not measurable
- Observability — no tracing, no structured logging, no cost tracking per run
- API layer — no programmatic access outside the Gradio UI
- Auth — no user identity, no rate limiting
- Docker and CI — no containerization, no automated test pipeline

### 1.2 Product Positioning

The upgraded project is positioned as an Enterprise Knowledge Intelligence platform — a RAG system that answers technical and operational questions against a curated corpus of engineering and product documentation, mimicking what a real B2B SaaS or FinTech engineering organisation would build for internal use.

This positioning is deliberate. The most commonly hired-for AI engineering use case in enterprise SaaS and FinTech in 2026 is internal knowledge retrieval: tools that let engineers, analysts, and product teams query internal docs, policies, runbooks, API references, and architectural decisions through natural language. The corpus for this demo is drawn entirely from publicly available analogues of that content — so it is legally unambiguous and fully reproducible, but the product story is immediately recognisable to any technical interviewer at a B2B company.

The corpus is multi-domain but coherent: it is the knowledge base of what an AI engineer at a modern engineering organisation would actually need to query. This makes the demo more credible than a single-domain corpus, and makes the evaluation queries more varied and interesting.

### 1.3 Why This Project (Not a New One)

AI engineer roles in 2026 evaluate candidates on a specific and consistent skill set. The skills that differentiate strong candidates from tutorial completers are:

- Production RAG pipelines with hybrid retrieval and measurable quality
- Agent orchestration with real tool use and multi-step workflows
- LLM evaluation methodology — offline evals, regression tests, LLM-as-judge
- Observability and cost instrumentation
- API design, auth, and deployment under production constraints

This project is the fastest path to demonstrating all of those skills in a single coherent system, because the agent architecture is already built. The upgrade adds the missing production layers around it — same repo, same agents — rather than starting from zero. The corpus choice and product positioning are framing changes, not architectural ones. Not a single line of existing agent code changes.

### 1.4 Relationship to Capstone

The cloud migration capstone demonstrates full SDLC, GCP deployment, CI/CD, BigQuery schema design, and graded code quality under assessment conditions. It should remain on the CV exactly as positioned. It is not being replaced or modified.

These two projects are complementary: the capstone proves software engineering discipline; this project proves AI engineering depth. They tell a complete story together.

## 2. Goals and Non-Goals

### 2.1 Primary Goals

- Add a RAG layer grounded in a real document corpus so that research queries retrieve and cite actual sources rather than relying entirely on LLM generation.
- Add a structured evaluation harness with reproducible metrics (RAGAS or LLM-as-judge) so quality claims are measurable, not narrative.
- Add LangFuse (or equivalent) for per-run tracing, token cost tracking, and latency instrumentation.
- Add persistent session storage (PostgreSQL via Supabase) so research sessions can be saved, retrieved, and compared.
- Wrap the agent in a FastAPI layer so the system is accessible via API, not just through the Gradio UI.
- Add JWT-based auth so the API demonstrates access control and per-user session scoping.
- Containerize with Docker and add GitHub Actions CI with prompt regression tests.

### 2.2 Secondary Goals

- Document all major design decisions: chunking strategy, embedding model choice, retrieval method, eval methodology, model selection rationale.
- Publish a benchmark comparing routing paths (quick vs deep) on a fixed query set with reproducible scores.
- Add a demo GIF and screenshot set for the Hugging Face Space and GitHub README.
- Ensure the Hugging Face hosted demo remains functional and publicly accessible throughout the upgrade.

### 2.3 Non-Goals

- This is not a SaaS product. No payment layer, no multi-tenant data isolation beyond basic auth scoping.
- This is not a real-time system. No WebSocket streaming, no push notifications.
- The capstone codebase is not being merged with or modified by this project.
- Custom model fine-tuning is out of scope. All LLM calls use hosted inference APIs.
- The Gradio UI is being supplemented, not replaced. Both interfaces coexist.

## 3. Target Architecture

### 3.1 System Overview

The upgraded system is composed of six layers. Each layer has a clear boundary and can be tested independently.

| Layer | Component | Technology | Status |
| --- | --- | --- | --- |
| Presentation | Gradio UI | Gradio 5.x | Exists — retained |
| API | REST API | FastAPI + JWT | New — to build |
| Orchestration | Agent pipeline | OpenAI Agents SDK | Exists — extend |
| Retrieval | RAG pipeline | Supabase pgvector | New — to build |
| Persistence | Session storage | Supabase PostgreSQL | New — to build |
| Observability | Tracing + evals | LangFuse | New — to build |

### 3.2 RAG Pipeline Design

#### Corpus: Enterprise Knowledge Intelligence

The corpus is drawn from five publicly available document sets that collectively mirror what a real engineering organisation's internal knowledge base would contain. Each source was chosen for a specific reason: content density, domain relevance to target roles, and the engineering challenge it poses for retrieval.

| Source | Volume | Why It Is In the Corpus | Retrieval Challenge |
| --- | --- | --- | --- |
| GitLab Handbook | `handbook.gitlab.com` (public) ~2,000+ pages | The most complete public analogue of a real company handbook. Covers engineering, product, HR, finance, security, and hiring. Every B2B SaaS company has this content internally. | Dense cross-references between sections. Queries about process or policy require retrieving across multiple non-adjacent chunks. Tests context recall under high corpus volume. |
| Stripe API Documentation | `stripe.com/docs` (public) ~800 pages | Real enterprise B2B product documentation. Dense, versioned, and cross-referenced. Directly relevant to FinTech roles. Tests whether the system handles versioned technical content cleanly. | Multiple versions of the same concept (e.g. API v1 vs v2 behaviour). Requires retrieval to surface the most current or most relevant version rather than an outdated one. |
| Anthropic + OpenAI API Docs | `docs.anthropic.com`, `platform.openai.com` (public) ~400 pages combined | Directly relevant to AI Engineer roles. Interviewers at AI-adjacent companies will recognise and respect the inclusion. Demonstrates you understand the tools you are building on. | Overlapping concepts between providers (e.g. both have "context windows", "tool use", "structured outputs") that require precise retrieval to avoid conflating provider-specific behaviour. |
| AWS Well-Architected Framework | `docs.aws.amazon.com` (public) ~600 pages | Cross-domain architecture decision content. Maps directly to how enterprise SaaS companies make infrastructure decisions. The capstone also touched GCP, making cloud architecture a coherent thread. | High-level architectural guidance that often requires synthesising across multiple pillars (reliability, security, cost optimisation). Tests multi-chunk synthesis rather than single-chunk lookup. |
| Public Engineering RFCs and ADRs | Cloudflare Blog, Uber Eng, Netflix Tech, GitHub Eng (public) ~150 documents | Architectural Decision Records and engineering blog posts that mirror how real teams document technical choices. Demonstrates you understand how engineering orgs communicate decisions — a product-aware signal. | Short, opinionated documents with context-dependent conclusions. Retrieval must surface the right ADR for the right system context, not just keyword-match on technology names. |

#### Sample Evaluation Queries

These queries are drawn directly from the corpus and serve as the fixed evaluation set. They are intentionally varied across document types to stress-test retrieval breadth.

- `"What is GitLab's policy on blameless post-mortems and how should they be structured?"` → GitLab Handbook
- `"How does Stripe handle idempotency keys and what happens if the same key is used twice?"` → Stripe API Docs
- `"What are the trade-offs between Anthropic's Claude Sonnet and Opus models for production use?"` → Anthropic Docs
- `"What does the AWS Well-Architected Framework recommend for reliability in multi-region deployments?"` → AWS WAF
- `"How does Cloudflare's engineering team approach graceful degradation in their edge network?"` → Engineering RFCs
- `"What is GitLab's approach to handbook-first communication and why does it exist?"` → GitLab Handbook
- `"How does OpenAI's structured output feature differ from function calling?"` → OpenAI Docs
- `"What trade-offs did Netflix consider when moving from monolith to microservices?"` → Netflix Tech Blog

These queries are answerable only from the corpus, not from general LLM knowledge alone — which means RAGAS faithfulness scores are a meaningful signal rather than a trivially satisfied check.

#### Chunking Strategy

Use recursive character splitting with 512-token chunks and 64-token overlap as the starting point. The GitLab Handbook and AWS WAF both have natural section boundaries that can be used as hard split points, reducing the risk of splitting mid-argument. This decision should be documented with before/after RAGAS context recall scores to demonstrate the impact of chunking choices.

#### Embedding Model

Use `text-embedding-3-small` (OpenAI) for initial implementation. It is cost-effective at approximately $0.02 per million tokens, produces 1536-dimensional vectors compatible with pgvector, and is well-documented in the context of the OpenAI ecosystem that the project already uses. If latency or cost becomes a concern during evaluation, the harness makes it straightforward to swap models and re-score.

#### Retrieval Method

Implement hybrid retrieval: BM25 keyword search combined with dense vector cosine similarity, with a reciprocal rank fusion step to merge result lists. This is the approach most commonly asked about in AI engineer interviews because it handles both keyword-sensitive queries (e.g. specific API parameter names in Stripe docs) and semantic queries (e.g. policy questions in the GitLab Handbook) better than either method alone.

### 3.3 Agent Integration

The RAG layer integrates with the existing agent pipeline at the search agent step. When a search agent executes a query, it first hits the RAG retriever for in-corpus knowledge, then falls back to web search for current or out-of-corpus information. The writer agent receives both retrieved chunks (with source citations) and web search results as context.

The router agent logic is extended: queries classified as `technical` or `deep` prioritize the RAG layer; queries classified as `quick` may skip retrieval entirely. This makes the cost trade-off explicit and measurable.

### 3.4 Evaluation Harness

This is the most important new component from a portfolio perspective. Without it, quality claims are narrative. With it, they are reproducible.

#### Offline Evaluation

Build a fixed query set of 20–30 questions covering the corpus domain, with manually verified reference answers. Run the full pipeline against this set and score with:

- RAGAS faithfulness — does the answer stay grounded in retrieved context?
- RAGAS answer relevancy — does the answer address the query?
- RAGAS context recall — does retrieval surface the right chunks?
- LLM-as-judge overall quality — GPT-4 scoring on a 1-10 rubric

#### Regression Testing

The CI pipeline runs a lightweight subset of this eval set (5–10 queries) on every pull request. If any score drops below a threshold relative to the previous run, the PR is flagged. This demonstrates prompt regression awareness, which is a specific signal interviewers look for.

#### Routing Benchmark

Run the fixed query set across all four routing paths (`quick`, `deep`, `technical`, `comparative`) and record: latency, token count, cost, and eval scores. Publish the results as a markdown table in the repository. This replaces the current directional performance claims with reproducible numbers.

### 3.5 Frontend Architecture and Deployment Topology

#### React Frontend

A React frontend serves as the product-facing demo surface — the interface shown in interviews and linked from the CV. It is built with Vite, Tailwind CSS, and shadcn/ui components. The scope is deliberately narrow: three panels, one workflow, enterprise aesthetic. No analytics dashboard, no settings pages, no user management UI.

The three panels are:

- Session panel (left) — lists past research sessions pulled from Supabase via the API, showing query, route taken, and timestamp. Makes the persistence layer visible rather than invisible.
- Research panel (centre) — streaming output with routing decision displayed prominently, source citation cards below the report (source name, section, link), and a visible cost and latency summary per run.
- Trace link (top right) — one-click link to the LangFuse trace for the current run. Surfaces the observability layer in the demo itself.

The React app is a static site deployed to Vercel. It consumes the FastAPI service via HTTPS. It has no Python dependency and no server-side rendering requirement. shadcn/ui is the component library of choice because it is what most AI product teams are using in 2026 and interviewers at AI-first companies recognise it as a credible choice.

#### Deployment Topology

There are three live surfaces and one source of truth.

| Surface | Host | Availability | Purpose |
| --- | --- | --- | --- |
| Gradio demo | Hugging Face Spaces | Always on, free | Public AI demo surface. Anyone can try the research workflow without auth. Linked from HF profile. |
| React frontend | Vercel | Always on, free | Product-facing demo. Shown in interviews. Linked from CV and GitHub README. Requires FastAPI to be running. |
| FastAPI service | Railway (free tier) | Sleeps when idle, cold-starts in ~20s | Backend for the React app. Handles agent runs, session persistence, auth, and LangFuse tracing. Note cold start in README. |

#### Repository Structure

| Path | Purpose |
| --- | --- |
| `agents/` | Existing agent code — router, planner, search, writer, evaluator, clarify. Untouched. |
| `app.py` | Gradio Hugging Face entrypoint. Untouched. Deployed to HF Spaces remote. |
| `rag/` | Document ingestion script, retrieval function, chunking utilities. Phase 1. |
| `eval/` | Fixed query set, RAGAS script, LLM-as-judge script, baseline results. Phase 2. |
| `api/` | FastAPI application — endpoints, auth middleware, session persistence, LangFuse integration. Phase 3. |
| `frontend/` | React + Vite + Tailwind + shadcn/ui. Three-panel research interface. Phase 3. |
| `docs/` | Architecture, design decisions, evaluation methodology, API reference. |
| `.github/workflows/` | CI eval regression on every PR. Deploy Gradio to HF on merge to main. Deploy FastAPI to Railway on merge to main. |

The two-remote setup is configured once and maintained automatically:

- `git remote add origin https://github.com/cam-bell/deep-research-workflow`
- `git remote add huggingface https://huggingface.co/spaces/cameronbell/deep-research-workflow`
- GitHub Actions handles the HF push — only `app.py`, `agents/`, and `requirements.txt` are included in the HF deploy, keeping the Space clean and fast to boot.

## 4. Technology Stack

Every technology choice below is deliberate. The rationale is documented here because explaining why you chose a technology is as important to interviewers as knowing how to use it.

| Area | Choice | Rationale |
| --- | --- | --- |
| LLM API | OpenAI (GPT-4o, 3-small) | Already integrated. Structured outputs via Pydantic. Best eval tooling support. |
| Agent SDK | OpenAI Agents SDK | Already integrated. Demonstrates native SDK use rather than a wrapper framework. |
| Vector store | Supabase pgvector | Avoids a separate vector DB service. PostgreSQL gives full SQL queryability alongside vectors. Supabase provides managed hosting. |
| Relational DB | Supabase PostgreSQL | Same instance as pgvector. Single managed service for both relational data and vector storage. |
| API framework | FastAPI | Async-native, Pydantic integration, auto-generated OpenAPI docs. Industry standard for Python AI backends. |
| Auth | JWT (`python-jose`) | Lightweight, demonstrates the auth pattern without adding OAuth complexity. Scope can expand to OAuth2 later. |
| Observability | LangFuse | Purpose-built for LLM tracing. Captures token usage, latency, cost, and eval scores per trace. Free tier sufficient. |
| Eval framework | RAGAS | Standard RAG evaluation library. Produces faithfulness, relevancy, and context recall scores. Widely recognised by interviewers. |
| Retrieval | BM25 + pgvector (hybrid) | Hybrid retrieval with RRF fusion. Better coverage than either method alone. Documented in design decisions. |
| UI — demo surface | Gradio 5.x (retain) | Already deployed on Hugging Face Spaces. Stays as the public AI demo surface. Not replaced — supplemented. |
| UI — product surface | React + Vite + Tailwind + shadcn/ui | Product-facing demo shown in interviews. Faster to build than Next.js with no SSR requirement. shadcn/ui is the 2026 standard for AI product UIs — recognisable to interviewers at AI-first companies. |
| Containerisation | Docker + Compose | Single Dockerfile for the FastAPI service. Compose for local dev with Supabase-compatible config. Interviewers can run the full stack locally with `docker-compose up`. |
| CI/CD | GitHub Actions | Eval regression on every PR. On merge to `main`: deploy Gradio to HF Spaces remote, deploy FastAPI to Railway, trigger Vercel rebuild of React frontend. |
| Gradio deployment | Hugging Face Spaces | Free, always on. Pushed via secondary Git remote. Only agent code and `app.py` are included — not FastAPI or React. |
| React deployment | Vercel (free tier) | Static site, auto-deployed from GitHub on merge to `main`. Free tier sufficient. Always on, no cold start. |
| FastAPI deployment | Railway (free tier) | Sleeps when idle, cold-starts in ~20 seconds. Free tier sufficient for a portfolio demo. Note cold start behaviour in README. CORS configured to allow Vercel origin. |

## 5. Implementation Plan

The project is structured in four phases. Each phase produces a working, deployable increment. No phase requires the next to be started before it is complete and pushed.

### Phase 1 — Foundation and RAG (Weeks 1–2)

#### Deliverables

- Supabase project provisioned with pgvector extension enabled
- Document ingestion script: fetch, chunk (512 tokens, 64 overlap), embed (`text-embedding-3-small`), upsert to pgvector — supporting all five corpus sources
- Corpus loaded: GitLab Handbook, Stripe API docs, Anthropic + OpenAI API docs, AWS Well-Architected Framework, and selected public engineering RFCs — minimum 500 chunks, target 3,000+
- Source metadata stored per chunk: source name, URL, section title, date fetched — enables citation in generated reports
- Retrieval function: hybrid BM25 + cosine similarity with RRF fusion, returning top-k chunks with source metadata
- Search agent updated to call retriever before web search; falls back to web search for out-of-corpus queries
- Writer agent updated to cite retrieved sources with source name and section in the output report
- Integration test: end-to-end query against a known corpus document returns answer with at least one cited source

#### Key Decisions to Document

- Chunk size and overlap rationale
- Embedding model selection and cost estimate
- Why pgvector over a dedicated vector DB (Pinecone, Weaviate)

### Phase 2 — Evaluation Harness (Weeks 3–4)

#### Deliverables

- Fixed query set of 25 questions with reference answers committed to `eval/queries.json` — drawn from all five corpus sources, covering lookup, synthesis, and cross-document queries
- RAGAS evaluation script: runs pipeline against query set, outputs faithfulness, answer relevancy, context recall per query and as aggregate scores
- LLM-as-judge script: GPT-4o scores each answer 1–10 on a defined rubric, outputs CSV with per-query scores and reasoning
- Routing benchmark: runs the query set across all four routing paths (`quick`, `deep`, `technical`, `comparative`), records latency, token count, cost, and RAGAS scores per path
- Results published as `eval/results/baseline.md` — includes methodology, aggregate scores, per-source breakdown, and instructions to reproduce
- CI workflow: PR check runs a 5-query subset covering one query per corpus source, fails if any RAGAS score drops more than 10% from baseline

#### Key Decisions to Document

- Why RAGAS over manual scoring
- LLM-as-judge rubric definition and inter-rater reliability discussion
- Threshold choice for regression CI gate

### Phase 3 — API, Auth, Observability, and Frontend (Weeks 5–6)

#### Deliverables — API and Backend

- FastAPI application with endpoints: `POST /sessions` (start research session), `GET /sessions/{id}` (retrieve), `GET /sessions` (list user sessions), `POST /auth/register`, `POST /auth/login`
- JWT middleware: all session endpoints require valid token
- Session persistence: research sessions saved to Supabase with `user_id`, `query`, `route`, `sources`, `report`, `eval scores`, `cost`
- LangFuse integration: every LLM call and retrieval operation emits a trace with token count, latency, cost, and route
- Structured logging: all API requests logged in JSON format with trace ID
- CORS configured to allow the Vercel frontend origin
- Dockerfile and `docker-compose.yml` for local development — full stack runs with `docker-compose up`
- OpenAPI docs auto-generated and committed to `docs/api/`
- FastAPI service deployed to Railway free tier — cold start behaviour noted in README

#### Deliverables — React Frontend

- React + Vite + Tailwind + shadcn/ui project scaffolded under `frontend/`
- Session panel: lists past research sessions from Supabase via API, showing query, route, and timestamp
- Research panel: streaming output, routing decision displayed prominently, source citation cards (name, section, link), cost and latency summary per run
- Trace link: one-click link to LangFuse trace for the current run, visible in the UI header
- Auth flow: register and login screens, JWT stored in memory (not `localStorage`), token passed in `Authorization` header
- React app deployed to Vercel — auto-deploys from GitHub on merge to `main`
- Two-remote Git configuration documented: GitHub (source of truth) and Hugging Face Spaces (Gradio deploy target)
- GitHub Actions workflow: on merge to `main`, deploy Gradio files to HF remote and trigger Vercel rebuild

#### Key Decisions to Document

- Why JWT over OAuth2 for this scope
- Session schema design: what to persist and why
- LangFuse vs alternatives (Arize, Helicone) — rationale for choice
- Why React + Vite over Next.js — no SSR requirement, simpler static deploy, same full-stack signal
- Why Railway over Fly.io or Render — free tier, GitHub integration, acceptable cold start behaviour for a portfolio demo
- Why two remotes rather than two repos — single source of truth, selective deploy to HF via GitHub Actions

### Phase 4 — Polish and Documentation (Weeks 7–8)

#### Deliverables

- README rewritten to reflect enterprise knowledge intelligence positioning and production architecture, with architecture diagram, corpus description, setup instructions, and links to eval results
- README includes two demo links clearly labelled: Gradio demo (Hugging Face) for the AI workflow demo, React app (Vercel) for the product-facing demo
- `docs/design-decisions.md` updated: corpus selection rationale, chunk size, embedding model, retrieval method, eval methodology, model selection, cost trade-offs, React vs Next.js decision, Railway deployment rationale
- `docs/evaluation.md` updated: baseline scores with per-source breakdown, routing benchmark table, instructions to reproduce
- Demo GIF captured from the React app: query input → routing decision visible → retrieved source citation cards shown → final report → session saved to history panel
- Screenshots committed: React session panel, research panel with citations, LangFuse trace link visible, Gradio demo on HF for comparison
- Hugging Face Space README updated with enterprise framing, corpus description, and link to full React demo
- CI badge added to main README

## 6. AI Engineer Skills Coverage

The table below maps each commonly assessed AI engineer skill to the project component that demonstrates it. This is intended as preparation for interview conversations, not just a checklist.

| Skill Area | Project Component | Phase |
| --- | --- | --- |
| RAG pipeline design | Hybrid retrieval, chunking, pgvector | Phase 1 |
| Embedding model selection | `text-embedding-3-small` with documented rationale | Phase 1 |
| Hallucination mitigation | Source grounding + faithfulness scoring | Phase 1–2 |
| LLM evaluation methodology | RAGAS + LLM-as-judge + routing benchmark | Phase 2 |
| Offline vs online eval | Fixed query set (offline) + CI regression (online) | Phase 2 |
| Regression testing for prompts | PR-gated eval subset with threshold check | Phase 2 |
| Agent orchestration | Router, planner, search, writer, evaluator | Existing |
| Gen AI / LLM API | OpenAI Agents SDK, structured outputs | Existing |
| API design | FastAPI, versioned endpoints, OpenAPI docs | Phase 3 |
| Authentication | JWT middleware, user-scoped sessions | Phase 3 |
| Persistence decisions | Why PostgreSQL + pgvector vs separate services | Phase 3 |
| Logging and observability | LangFuse tracing, structured JSON logs | Phase 3 |
| Full-stack AI integration | React frontend consuming FastAPI + streaming agent output | Phase 3 |
| Frontend state management | Session history, auth token, streaming response handling | Phase 3 |
| Multi-surface deployment | Two remotes: GitHub + HF Spaces. Three live surfaces. | Phase 3 |
| Cost optimisation | Routing paths reduce cost 30–50% on simple queries | Existing + Phase 2 |
| Latency vs accuracy trade-offs | Routing benchmark documents this explicitly | Phase 2 |
| Model selection reasoning | GPT-4o vs 4o-mini for writer vs evaluator | Phase 4 docs |
| Containerisation | Dockerfile, `docker-compose` — full stack runs locally | Phase 3 |
| CI/CD | GitHub Actions: eval regression, HF deploy, Railway deploy, Vercel rebuild | Phase 3–4 |
| Config management | Environment variables, secrets via GitHub Secrets | Phase 3 |
| Error handling / fallbacks | RAG miss → web search fallback | Phase 1 |
| Caching strategies | Query-level embedding cache to avoid re-embedding | Phase 3 |

## 7. Success Criteria

The project is complete when all of the following can be demonstrated or pointed to in the repository.

### 7.1 Functional Criteria

- A research query returns a report with at least two cited sources from the RAG corpus on every run where the query falls within the corpus domain.
- The evaluation harness runs end-to-end and produces a RAGAS score report against the fixed query set.
- RAGAS faithfulness score on the baseline query set is above 0.7.
- The routing benchmark table exists in the repository with reproducible numbers for all four routing paths.
- The FastAPI server starts, accepts authenticated requests, and persists sessions to Supabase.
- LangFuse dashboard shows traces with token counts and latency for every LLM call.
- CI passes on `main` and the eval regression check runs on every PR.
- The Hugging Face demo remains publicly accessible and functional throughout.

### 7.2 Documentation Criteria

- README explains the architecture at a level where a technical reader understands every major component without reading the code.
- Every significant design decision has a written rationale in `docs/design-decisions.md`.
- Evaluation methodology and baseline results are in `docs/evaluation.md` with instructions to reproduce.
- A demo GIF is committed and embedded in the README.

### 7.3 Interview Readiness Criteria

The project is interview-ready when you can answer the following questions concisely and with reference to actual code or data:

- `"Why did you use pgvector instead of Pinecone?"`
- `"How did you evaluate your RAG pipeline and what were the results?"`
- `"What is your chunking strategy and how did you decide on it?"`
- `"How do you prevent hallucinations in the generated reports?"`
- `"How does the routing logic affect cost and quality, and how do you know?"`
- `"What happens when a query falls outside the corpus — say, someone asks about GCP when you only have AWS?"`
- `"How would you detect a prompt regression after a model update?"`
- `"Walk me through how a session is persisted and retrieved."`
- `"Why did you choose GitLab's handbook as part of the corpus?"`
- `"How does your system handle overlapping concepts across providers — like OpenAI and Anthropic both having tool use?"`

## 8. Risks and Mitigations

| Risk | Severity | Likelihood | Mitigation |
| --- | --- | --- | --- |
| RAGAS scores are lower than expected, undermining quality claims | High | Medium | Treat as a learning outcome: document what caused the gap and what you changed. A thoughtful low score with analysis is more valuable than a fabricated high score. |
| OpenAI API costs exceed budget during eval runs | Medium | Medium | Use GPT-4o-mini for RAGAS evaluation and reserve GPT-4o for the final LLM-as-judge pass only. Estimate costs before running full benchmark. |
| `pgvector` query performance degrades at scale | Low | Low | Corpus is bounded at ~5,000 chunks. pgvector handles this comfortably. Add an IVFFlat index if needed. |
| Hugging Face Space breaks during upgrade | Medium | Low | Keep the existing Space on a separate branch until Phase 3 is complete. Upgrade to new Space only after local validation. |
| Scope creep extends timeline significantly | Medium | Medium | Phases 1 and 2 are the minimum viable portfolio contribution. Phases 3 and 4 add depth. Stop after Phase 2 if time is constrained. |

## 9. Scope Boundaries and Anti-Patterns

These are explicit boundaries based on the most common ways AI portfolio projects go wrong.

### 9.1 Do Not Add Custom ML Training

Custom model training on synthetic data for this domain adds complexity without adding portfolio signal. What AI engineer roles want to see is production use of hosted models with proper evaluation and engineering discipline around them, not bespoke sklearn pipelines. The capstone already demonstrates model training; this project demonstrates AI systems engineering.

### 9.2 Do Not Fabricate Metrics

The archived capstone documentation contained performance claims (85% recommendation accuracy, 91% risk prediction) that were written before the models were evaluated, not after. The actual evaluation found the primary model at 46% — below its own stated target. Never write metric claims before you have reproducible measurements. Every number in this project's documentation must come from a script that can be re-run.

### 9.3 Do Not Add Unnecessary Services

Adding Redis for caching, a dedicated Pinecone instance, a separate ChromaDB deployment, and a Celery worker queue is scope inflation. Each adds complexity, maintenance burden, and monthly cost for marginal portfolio benefit. Start with the simplest architecture that demonstrates the skill, document why you chose it, and note what you would add at scale. That is a more sophisticated answer than a complex architecture that is not fully understood.

### 9.4 Do Not Neglect the Existing Agent Architecture

The routing and evaluator-optimizer patterns are the strongest parts of the existing project. They should be retained, extended, and — most importantly — connected to the new evaluation harness so their quality impact is measurable. Rebuilding the agent from scratch in LangChain or LangGraph is not an improvement; it is a rewrite that loses the existing portfolio value.

### 9.5 Do Not Delay Documentation

Design decisions should be written in `docs/design-decisions.md` as each phase is completed, not retroactively at the end. The decisions are fresher, the rationale is more accurate, and the habit of documenting while building is itself a signal interviewers value.
