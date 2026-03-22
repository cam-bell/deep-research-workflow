# Phase 1 Spec — RAG Foundation

**Objective**: Add a hybrid retrieval layer grounded in a real document corpus.
Research queries retrieve and cite actual sources rather than relying entirely
on LLM generation.

**Verification**: A query about GitLab's blameless post-mortem policy returns
a report with at least one cited source from the corpus, with source name and
section visible in the output.

**Must not change**: `agents/`, `app.py`, `requirements.txt`

**New dependencies to add to `pyproject.toml`**:
```
supabase
pgvector
rank-bm25
langchain-text-splitters
httpx
beautifulsoup4
```

---

## Task 1.1 — Supabase Schema

**Estimated agent time**: 5 minutes
**Files to create**: `rag/schema.sql`

Create the pgvector schema in Supabase. The SQL must be idempotent
(safe to run multiple times).

```sql
-- Enable pgvector extension
create extension if not exists vector;

-- Corpus chunks table
create table if not exists corpus_chunks (
  id          uuid primary key default gen_random_uuid(),
  source_name text not null,
  source_url  text not null,
  section_title text,
  content     text not null,
  embedding   vector(1536),
  date_fetched timestamptz default now(),
  chunk_index integer
);

-- Index for cosine similarity search
create index if not exists corpus_chunks_embedding_idx
  on corpus_chunks
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

-- Sessions table (used in Phase 3)
create table if not exists research_sessions (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid,
  query       text not null,
  route       text,
  report      text,
  sources     jsonb,
  eval_scores jsonb,
  cost_usd    float,
  latency_ms  integer,
  created_at  timestamptz default now()
);

-- Users table (used in Phase 3)
create table if not exists users (
  id            uuid primary key default gen_random_uuid(),
  email         text unique not null,
  password_hash text not null,
  created_at    timestamptz default now()
);
```

**Verification**: Run `psql $SUPABASE_DB_URL -f rag/schema.sql` with no errors.

---

## Task 1.2 — Chunker

**Estimated agent time**: 10 minutes
**Files to create**: `rag/chunker.py`

```python
# Expected interface
def chunk_document(
    content: str,
    source_name: str,
    source_url: str,
    section_title: str = "",
) -> list[ChunkMetadata]:
    ...

class ChunkMetadata(BaseModel):
    content: str
    source_name: str
    source_url: str
    section_title: str
    chunk_index: int
```

Requirements:
- Use `langchain_text_splitters.RecursiveCharacterTextSplitter`
- chunk_size=512 tokens, chunk_overlap=64 tokens
- Use `tiktoken` with `cl100k_base` encoding for token counting
- Preserve section headers as `section_title` when detectable
  (look for `#` markdown headings above the chunk)
- Return list of `ChunkMetadata` Pydantic objects

**Verification**: `uv run python -c "from rag.chunker import chunk_document; chunks = chunk_document('test content', 'test', 'http://test.com'); print(len(chunks))"` returns without error.

---

## Task 1.3 — Embedding Helper

**Estimated agent time**: 5 minutes
**Files to create**: `rag/embedder.py`

```python
# Expected interface
async def embed_texts(texts: list[str]) -> list[list[float]]:
    ...

async def embed_single(text: str) -> list[float]:
    ...
```

Requirements:
- Use OpenAI `text-embedding-3-small` model
- Output dimension: 1536
- Batch texts in groups of 100 to avoid rate limits
- Raise `EmbeddingError` (custom exception) on API failure
- Log token usage per batch with `logging.getLogger(__name__)`

**Verification**: `uv run python -c "import asyncio; from rag.embedder import embed_single; v = asyncio.run(embed_single('test')); print(len(v))"` prints `1536`.

---

## Task 1.4 — Ingestion Script

**Estimated agent time**: 15 minutes
**Files to create**: `rag/ingest.py`

This is the one-time script that populates the corpus. It must be
idempotent — running it twice for the same source should not create
duplicate chunks (check by source_url + chunk_index before inserting).

```python
# Expected CLI interface
# uv run python rag/ingest.py --source gitlab-handbook
# uv run python rag/ingest.py --all
# uv run python rag/ingest.py --source stripe-docs --limit 50  (for testing)
```

Source configurations (hardcode these in the script):

```python
SOURCES = {
    "gitlab-handbook": {
        "base_url": "https://handbook.gitlab.com",
        "start_paths": ["/engineering/", "/product/", "/hiring/", "/security/"],
        "source_name": "GitLab Handbook",
        "max_pages": 500,
    },
    "stripe-docs": {
        "base_url": "https://docs.stripe.com",
        "start_paths": ["/api", "/payments", "/connect", "/billing"],
        "source_name": "Stripe API Documentation",
        "max_pages": 200,
    },
    "anthropic-docs": {
        "base_url": "https://docs.anthropic.com",
        "start_paths": ["/en/docs/"],
        "source_name": "Anthropic API Documentation",
        "max_pages": 100,
    },
    "openai-docs": {
        "base_url": "https://platform.openai.com",
        "start_paths": ["/docs/"],
        "source_name": "OpenAI API Documentation",
        "max_pages": 100,
    },
    "aws-waf": {
        "base_url": "https://docs.aws.amazon.com",
        "start_paths": ["/wellarchitected/latest/framework/"],
        "source_name": "AWS Well-Architected Framework",
        "max_pages": 150,
    },
    "engineering-rfcs": {
        "urls": [
            "https://blog.cloudflare.com/tag/engineering/",
            "https://eng.uber.com/",
            "https://netflixtechblog.com/",
            "https://github.blog/engineering/",
        ],
        "source_name": "Engineering RFCs and ADRs",
        "max_pages": 50,
    },
}
```

Ingestion flow per source:
1. Fetch pages with `httpx.AsyncClient` (respect robots.txt, add 1s delay between requests)
2. Parse HTML with `BeautifulSoup`, extract main content (remove nav, footer, ads)
3. Chunk with `rag.chunker.chunk_document`
4. Embed with `rag.embedder.embed_texts` (batch)
5. Upsert to Supabase `corpus_chunks` table (skip if duplicate)
6. Log progress: source, page count, chunk count, token estimate

**Verification**: 
```bash
uv run python rag/ingest.py --source anthropic-docs --limit 10
# Should print: "Ingested X chunks from Anthropic API Documentation"
# Check Supabase: SELECT count(*) FROM corpus_chunks WHERE source_name = 'Anthropic API Documentation';
```

---

## Task 1.5 — Retrieval Function

**Estimated agent time**: 15 minutes
**Files to create**: `rag/retrieve.py`

```python
# Expected interface
class RetrievedChunk(BaseModel):
    content: str
    source_name: str
    source_url: str
    section_title: str
    score: float  # RRF-merged score, higher = more relevant

async def retrieve(
    query: str,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    ...
```

Requirements:
- **BM25**: use `rank_bm25.BM25Okapi` over the in-memory corpus index
  (build index on first call, cache in module-level variable)
- **Vector search**: embed the query, run cosine similarity against
  `corpus_chunks` in Supabase using pgvector
- **RRF fusion**: merge BM25 and vector rankings using reciprocal rank
  fusion formula: `score = 1/(k + rank_bm25) + 1/(k + rank_vector)` where k=60
- Return top_k results sorted by RRF score descending
- If corpus is empty (0 chunks), return empty list immediately
  (do not raise an exception — the caller handles fallback to web search)

CLI test interface:
```bash
uv run python rag/retrieve.py --query "What is GitLab's policy on blameless post-mortems?"
# Should print top 5 chunks with source names and scores
```

**Verification**: Running the CLI above returns at least 1 result with
`source_name = "GitLab Handbook"` after Task 1.4 has ingested gitlab-handbook.

---

## Task 1.6 — Agent Integration

**Estimated agent time**: 10 minutes
**Files to modify**: `research_manager.py` (ONLY the `perform_searches` method)

This is the only permitted change to the existing codebase.
Do not modify any other method in `research_manager.py`.
Do not modify any agent file.

The change: before performing a web search for each `WebSearchItem`,
call `rag.retrieve.retrieve(item.query)`. If results are returned,
prepend them to the search result as formatted context. If no results,
proceed with web search as before.

```python
# In research_manager.py, modify perform_searches():
# BEFORE: tasks = [asyncio.create_task(self.search(item)) for item in search_plan.searches]
# AFTER:
async def search_with_rag(self, item: WebSearchItem) -> str | None:
    from rag.retrieve import retrieve
    rag_results = await retrieve(item.query, top_k=3)
    
    if rag_results:
        rag_context = self._format_rag_results(rag_results)
        # Still run web search for recency/out-of-corpus coverage
        web_result = await self.search(item)
        return f"{rag_context}\n\n{web_result or ''}"
    else:
        return await self.search(item)

def _format_rag_results(self, chunks: list) -> str:
    lines = ["[Retrieved from corpus:]"]
    for chunk in chunks:
        lines.append(f"Source: {chunk.source_name} — {chunk.section_title}")
        lines.append(f"URL: {chunk.source_url}")
        lines.append(chunk.content)
        lines.append("---")
    return "\n".join(lines)
```

**Verification**: Run a research query about GitLab post-mortems through
the Gradio UI. The output report should contain a citation to
"GitLab Handbook" in the sources section.

---

## Task 1.7 — Integration Test

**Estimated agent time**: 5 minutes
**Files to create**: `tests/test_rag_integration.py`

```python
import pytest
import asyncio
from rag.retrieve import retrieve

@pytest.mark.asyncio
async def test_retrieve_returns_results():
    """Corpus must return at least one result for a known query."""
    results = await retrieve("GitLab blameless post-mortem policy")
    assert len(results) > 0
    assert results[0].source_name is not None
    assert results[0].content != ""

@pytest.mark.asyncio
async def test_retrieve_returns_metadata():
    """Every result must have source_url and section_title."""
    results = await retrieve("Stripe idempotency keys")
    for r in results:
        assert r.source_url.startswith("http")
        assert r.score > 0

@pytest.mark.asyncio
async def test_empty_corpus_returns_empty_list():
    """Retrieval against empty corpus must not raise exceptions."""
    # This test runs against real Supabase — skip if corpus not loaded
    results = await retrieve("query that won't match anything xyzzy123")
    assert isinstance(results, list)
```

**Verification**: `uv run pytest tests/test_rag_integration.py -v` passes.

---

## Phase 1 Done When

- [ ] `rag/schema.sql` runs against Supabase with no errors
- [ ] At least 500 chunks ingested (check: `SELECT count(*) FROM corpus_chunks`)
- [ ] `uv run python rag/retrieve.py --query "..."` returns results with source names
- [ ] Research query through Gradio UI returns report with at least one corpus citation
- [ ] `uv run pytest tests/test_rag_integration.py` passes
- [ ] `docs/design-decisions.md` updated with: chunk size rationale, embedding model choice, why pgvector
