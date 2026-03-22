# Phase 4 Spec — Polish and Documentation

**Prerequisite**: Phases 1–3 complete. All three live surfaces functional.

**Objective**: Make the project interview-ready. Every claim in the README
must be backed by a script or a screenshot. No narrative metrics.

**Must not change**: `agents/`, `app.py`, `requirements.txt`

---

## Task 4.1 — Rewrite README.md

**Estimated agent time**: 15 minutes
**Files to modify**: `README.md`

The README must contain these sections in this order:

1. **Project title and one-line description**
   - "Enterprise Knowledge Intelligence — a production RAG system that answers
     technical and operational questions against a curated engineering corpus,
     with hybrid retrieval, measurable evaluation, and full observability."

2. **Two demo links, clearly labelled**
   - `[🤗 Gradio Demo (Hugging Face)](https://huggingface.co/spaces/cameronbell/deep-research-workflow)`
     — AI workflow demo, no auth required
   - `[🚀 Product Demo (React App)](https://your-vercel-url.vercel.app)`
     — full product interface with session history and source citations
   - Note: "First request to the API may take 20–30 seconds if the service
     has been idle (Railway free tier cold start)"

3. **Architecture diagram** (Mermaid)
   ```mermaid
   flowchart TD
     User --> React["React Frontend (Vercel)"]
     User --> Gradio["Gradio Demo (HF Spaces)"]
     React --> FastAPI["FastAPI Service (Railway)"]
     FastAPI --> Agents["Agent Pipeline"]
     Agents --> RAG["RAG Retriever (pgvector)"]
     Agents --> Web["Web Search (fallback)"]
     RAG --> Supabase["Supabase (pgvector + PostgreSQL)"]
     FastAPI --> LangFuse["LangFuse (tracing)"]
     FastAPI --> Supabase
   ```

4. **Corpus description** — table of 5 sources with volume and purpose

5. **Evaluation results** — link to `docs/evaluation.md`, show the
   routing benchmark table inline

6. **Setup instructions** — for running locally with docker-compose

7. **CI badge** — add GitHub Actions badge at the top

**Verification**: README renders correctly on GitHub with no broken links,
no placeholder text, and no claims without evidence.

---

## Task 4.2 — Update docs/design-decisions.md

**Estimated agent time**: 15 minutes
**Files to modify**: `docs/design-decisions.md`

Must cover each of these decisions with a 2–4 sentence rationale:

- **Chunk size (512 tokens, 64 overlap)**: why this starting point,
  what the before/after RAGAS context recall scores showed
- **Embedding model (text-embedding-3-small)**: cost vs quality trade-off,
  dimension compatibility with pgvector, what you would swap to at scale
- **pgvector over Pinecone/Weaviate**: single managed service argument,
  SQL queryability, cost at portfolio scale
- **Hybrid retrieval (BM25 + vector + RRF)**: why neither method alone
  is sufficient, how the Stripe API keyword queries vs GitLab semantic
  queries illustrate the difference
- **JWT over OAuth2**: scope justification, what would need to change
  to add OAuth2
- **React + Vite over Next.js**: no SSR requirement, simpler static
  deploy, same full-stack signal for interviews
- **Railway over Fly.io/Render**: free tier behaviour, GitHub integration,
  acceptable cold start for portfolio context
- **Two remotes (GitHub + HF)**: single source of truth argument,
  selective deploy pattern, how the GitHub Action handles it
- **RAGAS over manual scoring**: reproducibility, industry recognition,
  what RAGAS does not measure (and what LLM-as-judge covers instead)
- **LangFuse over Arize/Helicone**: purpose-built for LLM tracing,
  free tier, trace URL surfaced directly in the React UI

**Verification**: `docs/design-decisions.md` has a section for each
decision above and each section has a "What I would change at scale"
one-liner.

---

## Task 4.3 — Update docs/evaluation.md

**Estimated agent time**: 10 minutes
**Files to modify**: `docs/evaluation.md`

Must contain:
- **Methodology section**: what RAGAS measures, what LLM-as-judge measures,
  how the routing benchmark was run, what "CI regression" means
- **Baseline scores table** (pulled from `eval/results/baseline.md`):
  faithfulness, answer_relevancy, context_recall per route
- **Per-source breakdown**: average faithfulness per corpus source
  (GitLab Handbook vs Stripe Docs etc.) — shows which sources retrieve well
- **Routing benchmark table** (copy from baseline.md): latency, tokens,
  cost, faithfulness per route
- **Reproduction instructions**: exact commands to re-run the evaluation
- **Known limitations**: what RAGAS scores don't tell you, known weak spots

**Verification**: A technical reader can reproduce the baseline scores by
following the instructions in this document.

---

## Task 4.4 — Demo GIF and Screenshots

**Estimated agent time**: 20 minutes (manual capture, not agent work)
**Files to create**: 
- `assets/demo.gif`
- `assets/screenshots/01-session-panel.png`
- `assets/screenshots/02-research-panel-with-citations.png`
- `assets/screenshots/03-routing-decision.png`
- `assets/screenshots/04-langfuse-trace.png`
- `assets/screenshots/05-gradio-demo.png`

Demo GIF script (capture in this sequence):
1. Open React app, show empty session panel
2. Type: "How does Stripe handle idempotency keys?"
3. Click Research — show routing badge appear ("Route: technical")
4. Show streaming output arriving
5. Show source citation cards appearing below the report
6. Show the session saved to the left panel
7. Click "View trace" — LangFuse opens in new tab (show briefly)

The GIF should be 30–60 seconds, exported at 1280×720, under 5MB.
Use Kap (macOS) or LICEcap to capture.

**Verification**: `assets/demo.gif` exists and is under 5MB.
README embeds the GIF and it renders on GitHub.

---

## Task 4.5 — Update Hugging Face Space README

**Estimated agent time**: 5 minutes
**Files to modify**: The README section at the top of `app.py`
(the YAML frontmatter is already there — add content below it)

Add below the YAML frontmatter:
```markdown
# Deep Research Workflow

Enterprise knowledge intelligence platform. Multi-agent research pipeline
with RAG retrieval against a curated corpus of engineering documentation.

**This is the Gradio demo** — try a research query without signing in.
For the full product experience with session history and source citations,
see the [React frontend](https://your-vercel-url.vercel.app).

## Corpus
Questions about any of these sources are answered with retrieved citations:
- GitLab Handbook
- Stripe API Documentation  
- Anthropic + OpenAI API Docs
- AWS Well-Architected Framework
- Public Engineering RFCs (Cloudflare, Uber, Netflix, GitHub)

## Try these queries
- "What is GitLab's policy on blameless post-mortems?"
- "How does Stripe handle idempotency keys?"
- "What are the trade-offs between Claude Sonnet and Opus?"
- "What does AWS recommend for multi-region reliability?"
```

**Verification**: The HF Space page shows the updated description
after the next deploy.

---

## Phase 4 Done When

- [ ] README has no placeholder text, no broken links, no narrative metrics
- [ ] Both demo links are live and labelled correctly
- [ ] `docs/design-decisions.md` covers all 10 decisions with rationale
- [ ] `docs/evaluation.md` has baseline scores and reproduction instructions
- [ ] `assets/demo.gif` committed and embedded in README
- [ ] All 5 screenshots committed to `assets/screenshots/`
- [ ] HF Space README updated with corpus description and sample queries
- [ ] CI badge in README is green

## Interview Ready When You Can Answer These Without Notes

- "Why did you use pgvector instead of Pinecone?"
- "How did you evaluate your RAG pipeline and what were the results?"
- "What is your chunking strategy and how did you decide on it?"
- "How do you prevent hallucinations in the generated reports?"
- "How does the routing logic affect cost and quality?"
- "What happens when a query falls outside the corpus?"
- "How would you detect a prompt regression after a model update?"
- "Walk me through how a session is persisted and retrieved."
- "Why did you choose GitLab's handbook as part of the corpus?"
- "How does your system handle overlapping concepts — OpenAI and Anthropic both have tool use?"
