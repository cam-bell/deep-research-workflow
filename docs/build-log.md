---
# Build Log

Running record of what was built, what broke, how it was fixed, and why 
decisions were made. Written during and after each session, not retroactively.
Each entry is dated and tagged with the phase and component it relates to.

---

## 2026-03-22 — Phase 1

### Ingestion / Supabase transport hardening

### What we were trying to do
Stabilize the ingestion pipeline so transient Supabase/PostgREST transport failures would not abort a crawl after embedding work had already completed. The goal was to make both the read-before-insert path and the batched write path resilient enough for repeated live ingestion runs.

### What happened
Live ingestion runs were failing intermittently during Supabase requests even when crawling and embedding were otherwise working. The failures included transport-layer exceptions such as `httpx.ReadError: [SSL: SSLV3_ALERT_BAD_RECORD_MAC]`, `httpx.WriteError: [Errno 32] Broken pipe`, and successful retry logs like `Retrying Supabase insert attempt=1 rows=25 batch_start=25`, which showed the failures were transient rather than deterministic schema or data problems.

### Root cause
The ingestion code only partially handled transient network issues. It retried some write-side transport errors after batching was introduced, but it did not centralize retry logic, did not make client/session reset explicit, and still allowed read-side Supabase calls to fail hard. The underlying TLS/HTTP2 instability appears to be between the local client and Supabase/PostgREST; I cannot prove the exact lower-level cause beyond that.

### What we changed
We updated `/Users/cameronbell/Projects/deep-research-workflow/rag/ingest.py` to add an explicit cached Supabase client plus `_reset_supabase_client()`, created a shared `_run_supabase_operation(...)` retry wrapper, and applied it to both `_select_existing_chunk_indices()` and `_insert_chunk_rows()`. We kept insert batching at `25` rows, but changed retry handling from direct transport exceptions only to selective retry of retryable `APIError` statuses (`408`, `429`, `500`, `502`, `503`, `504`) plus transport exceptions. We also expanded `/Users/cameronbell/Projects/deep-research-workflow/tests/test_ingest.py` from parser/crawl tests to include retryable insert failures, non-retryable API failures, and read-side retry coverage.

### Why this fix and not another
The main alternatives were disabling HTTP/2 entirely, replacing Supabase/PostgREST with direct database writes, or accepting the transient failures and relying on reruns. We chose centralized retry plus explicit client reset because it addresses the observed failure mode with minimal architectural change, keeps the existing ingestion contract intact, and preserves the Supabase table write path already used elsewhere. There was no strong reason to replace the persistence layer while the failures were clearly transient and recoverable.

### What to watch for
If Supabase starts surfacing more transient failures as `APIError` variants with messages or status shapes we did not account for, the retry classifier may still miss some retryable cases. If very large pages continue to generate huge numbers of chunks, the current `25`-row batch size may still need tuning or adaptive splitting. Also, repeated client resets could become inefficient if ingestion scales up substantially.

### What I learned
I learned that a retry strategy is only half-finished if it protects writes but not the read-side query that decides whether writes are needed. I also learned that making client reset explicit is worth it, because otherwise a retry can quietly reuse the same broken connection and give a false sense of resilience. Next time I would centralize transport retry policy earlier instead of patching each failure mode incrementally.

---

## 2026-03-22 — Phase 1

### Retrieval / Hybrid retrieval function

### What we were trying to do
Complete Task 1.5 by building a hybrid retriever that combines BM25 over the ingested corpus with pgvector similarity search, then fuses both rankings with reciprocal rank fusion. The goal was to make retrieval verifiable against the live Supabase corpus before moving on to agent integration.

### What happened
The retrieval work initially looked blocked because there was no existing `match_corpus_chunks` RPC and no installed Postgres driver for a direct pgvector path. During debugging, live smoke tests showed the retriever could import and talk to Supabase and OpenAI, but vector queries were returning no rows even though embedded Anthropic chunks existed in `corpus_chunks`. After validating the surrounding data and query assumptions, we implemented a committed Supabase RPC instead and switched the live vector branch to `POST /rest/v1/rpc/match_chunks`, which then returned rows and made the retrieval verification pass.

### Root cause
The original issue was not missing corpus data; it was the lack of a clean, supported vector-query interface in the codebase. We spent time exploring a direct Postgres path because there was no retrieval RPC yet, but the final root cause was architectural rather than data-related: the project needed an explicit pgvector query surface instead of trying to force vector search through generic table access.

### What we changed
We updated `/Users/cameronbell/Projects/deep-research-workflow/rag/schema.sql` to define `create or replace function match_chunks(query_embedding vector(1536), match_count int default 5, filter_source text default null) returns table (...)`, so the vector query lives in committed schema rather than only in the Supabase UI. We updated `/Users/cameronbell/Projects/deep-research-workflow/rag/retrieve.py` so `_vector_search()` embeds the query with `embed_single(...)`, calls `supabase.rpc("match_chunks", {"query_embedding": query_embedding, "match_count": limit})`, and feeds those results into the existing RRF merge with BM25 candidates from the cached corpus. We kept the corpus cache, BM25 index, and `RetrievedChunk` interface intact; the before/after change was specifically from “no committed RPC / vector path still in flux” to “schema-backed `match_chunks` RPC called directly from the retriever.”

### Why this fix and not another
The alternatives were to keep pursuing a direct psycopg/pgvector client path, construct raw SQL over `SUPABASE_DB_URL`, or degrade to BM25-only retrieval temporarily. We chose the RPC because it is cleaner, keeps the pgvector SQL in Postgres where the `<=>` operator belongs, matches Supabase’s documented pattern, and fails loudly if the function is missing. There was no advantage in keeping the direct-driver path once the RPC approach was defined and committed in schema.

### What to watch for
The retrieval path now depends on the `match_chunks` function existing in every environment where `rag/retrieve.py` runs, so schema drift would break vector search immediately. Because the RPC returns rows from `corpus_chunks`, retrieval quality still depends on corpus volume and metadata quality, and low-coverage sources can still make the fusion results look worse than the algorithm itself. If the embedding dimension or model changes later, the RPC signature and stored vectors must stay aligned.

### What I learned
I learned that it is worth distinguishing between an implementation dead end and a temporary debugging path; the psycopg investigation helped narrow the problem, but it was not the right final abstraction for this project. I also understand more clearly now that hybrid retrieval is easier to reason about when the vector branch is explicit, schema-backed, and easy to smoke-test independently of BM25.

---

## 2026-03-22 — Phase 1

### Ingestion / Crawl logic review and recovery

### What we were trying to do
Review the already-implemented Task 1.4 ingestion script to understand why the corpus was not growing beyond GitLab and to identify what had to change to reach the `>= 500` chunk gate. The goal was to validate the corrected source URLs first, then fix the crawling and extraction logic that was starving the rest of the corpus.

### What happened
We manually checked the configured `base_url` and `start_paths`, tested the updated URLs, and confirmed the crawler was reaching the right documentation hosts. That review showed the crawl constraints were still too strict: allowed hosts had to match the configured host exactly, and discovered links still had to begin with one of the configured `start_paths`. In practice, GitLab was producing most of the corpus while other sources were barely contributing, which matched the later code review findings that `_is_allowed_url()` was still prefix-based, there was no explicit URL blocklist for paths like `/blog/` or `/login/`, thin-page filtering was still too weak, and there was no retry/backoff around fetches or Supabase inserts.

### Root cause
The main problem was not the source list anymore; it was the crawler policy and extraction thresholds. The implementation still treated `start_paths` as an ongoing allowlist instead of initial seeds, which starved discovery after redirects or site restructures. That was compounded by generic content-container selection, a character-based thin-page threshold that let low-value pages through while wasting crawl budget, and missing retry logic that let transient network failures kill otherwise valid ingestion runs.

### What we changed
We updated `/Users/cameronbell/Projects/deep-research-workflow/rag/ingest.py` so crawl scope became seed-based same-host crawling with blocked noise paths instead of strict prefix allowlisting. We added one-hop allowed cross-host redirect handling for trusted docs destinations, improved content selection to prioritize `main`, `article`, `[role="main"]`, `.content`, `.docs-content`, and `.markdown-body`, strengthened thin-page filtering from a weak character threshold to a substantive-content check, hardened `_strip_noise()` against malformed attributes, and added retry/backoff around both fetches and Supabase insert operations with smaller insert batches. We also added targeted regression coverage in `/Users/cameronbell/Projects/deep-research-workflow/tests/test_ingest.py` for URL admission, redirect handling, parser robustness, thin-page skipping, and transient insert/fetch failures, and added `pytest` support in `/Users/cameronbell/Projects/deep-research-workflow/pyproject.toml`.

### Why this fix and not another
The alternative was to keep adjusting source seeds and host values one source at a time and hope coverage improved, but that would not have fixed the structural starvation in the crawler itself. We chose to change the crawling policy because the manual URL checks had already shown the source definitions were no longer the main bottleneck. Once the logic was made seed-based and resilient, each source could contribute based on its actual content instead of being clipped by the crawler’s scope rules.

### What to watch for
The looser crawl policy increases the risk of wandering into low-value or noisy sections if a source’s blocklist is incomplete, so source-specific path noise may still need tuning. Cross-host redirect allowance should stay tightly bounded to trusted docs destinations, otherwise a marketing or auth redirect could accidentally expand crawl scope. Also, stronger extraction and filtering improve quality, but they can still underperform on sources whose HTML structure changes materially.

### What I learned
I learned that validating `base_url` and `start_paths` is necessary but not sufficient; a crawler can be pointed at the correct site and still fail because its discovery rules are wrong. I also learned that corpus starvation shows up first as a retrieval problem, but the real fix is often in crawl policy and content selection rather than in the retriever. Next time I would instrument acceptance and rejection reasons earlier so I can see crawl starvation before it becomes a larger pipeline issue.
