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

---

## 2026-03-23 — Phase 1

### Ingestion / RFC source split and host-specific crawl controls

### What we were trying to do
Improve the quality and reliability of the public engineering RFC/ADR corpus by treating Cloudflare, Uber, Netflix, and GitHub as separate crawl targets instead of one aggregated source. The goal was to give each host its own crawl policy so low-quality taxonomy pages and host-specific fetch failures would not contaminate the whole RFC source.

### What happened
The original aggregated `engineering-rfcs` source behaved inconsistently because each host had different HTML structure, URL patterns, and fetch constraints. Cloudflare was pulling in tag and author pages that would dilute retrieval quality, Uber was failing with `406 Not Acceptable` under the default headers, Netflix was failing before ingestion, and GitHub was working but was mixed into the same coarse config. This made it difficult to tell whether the crawler itself was broken or whether one host was poisoning the aggregate results.

### Root cause
The source grouping was too coarse. Four different publishing stacks were being handled by one shared config, which meant the crawler could not express host-specific allow rules, blocked paths, or request headers. The failures were not caused by one generic bug; they were caused by heterogeneous source behavior being forced through a single source definition.

### What we changed
We updated `/Users/cameronbell/Projects/deep-research-workflow/rag/ingest.py` to replace the single `engineering-rfcs` source with four host-specific configs: `cloudflare-rfcs`, `uber-rfcs`, `netflix-rfcs`, and `github-rfcs`. We added source-level controls for `allowed_path_prefixes`, `blocked_path_substrings`, and `extra_headers`, then used them to block Cloudflare `/tag/` and `/author/` pages, constrain Uber crawling to `/blog/`, and send browser-like `Accept` and `Accept-Language` headers to Uber. We expanded `/Users/cameronbell/Projects/deep-research-workflow/tests/test_ingest.py` with source-specific coverage for host-specific URL admission, blocked taxonomy paths, listing-page rejection, and per-host headers.

### Why this fix and not another
The alternative was to keep one aggregated RFC source and pile on more generic crawler heuristics, but that would have hidden host-specific problems instead of solving them. Splitting the source was the lowest-risk way to keep the ingestion pipeline coherent while preserving the same overall corpus category. There was no practical benefit in pretending the four hosts behaved similarly when the live verification showed the opposite.

### What to watch for
The split improves diagnosis and control, but it also increases the number of source configs that must be maintained as sites change. Because the RFC hosts no longer share one source definition, eval and reporting code later in the project will need to be conscious of whether they care about per-host names or the broader “Engineering RFCs and ADRs” category. Cloudflare and GitHub may still need additional path noise tuning if new archive or taxonomy routes appear.

### What I learned
I learned that a heterogeneous source group is often a code smell in ingestion work: if hosts need different fetch behavior, they probably need different configs. I also learned that source-level clarity is worth the extra config surface because it makes live debugging much faster and keeps one bad host from obscuring the health of the others.

---

## 2026-03-23 — Phase 1

### Ingestion / Netflix Tech Blog recovery

### What we were trying to do
Get Netflix Tech Blog content into the RFC/ADR corpus without weakening global crawler security or silently dropping the source. The goal was to determine whether Netflix was truly unusable in this runtime or whether the problem could be fixed cleanly enough to keep the source in the corpus.

### What happened
Netflix initially failed with repeated certificate errors, so the ingestion code classified it as `environment_blocked` with `tls_certificate_verification_failed` and exited cleanly with zero chunks inserted. After further investigation, we found that the failure was no longer purely transport-related: once the TLS path was improved, the root `https://netflixtechblog.com/` page fetched successfully but contained only about 17 words and behaved like a thin Medium publication shell, so `_parse_document()` correctly skipped it before chunking. We also tested `https://netflixtechblog.medium.com/`, but that returned `403 Forbidden` even after the trust-store fallback, so it was not a better crawl entrypoint.

### Root cause
There were two separate root causes over time. First, the Python/httpx runtime could not verify the certificate path served by `netflixtechblog.com`, which blocked fetches entirely. Second, once fetches succeeded, the configured seed URL was still wrong for this ingestion pipeline: the homepage was a publication landing page rather than a substantive article page, so it never met the parser’s content threshold and never produced useful discovered links for the crawl queue.

### What we changed
We updated `/Users/cameronbell/Projects/deep-research-workflow/rag/ingest.py` to add a source-local TLS fallback for Netflix using `truststore`, plus `redirect_passthrough_hosts=["medium.com"]` so the `netflixtechblog.com -> medium.com -> netflixtechblog.com` identity redirect chain would not be rejected as out of scope. We added `truststore` to `/Users/cameronbell/Projects/deep-research-workflow/pyproject.toml` and refreshed `/Users/cameronbell/Projects/deep-research-workflow/uv.lock`. We then changed the Netflix source seeds in `/Users/cameronbell/Projects/deep-research-workflow/rag/ingest.py` from the homepage to a curated list of canonical article URLs such as `/scaling-global-storytelling-modernizing-localization-analytics-at-netflix-816f47290641` and `/optimizing-recommendation-systems-with-jdks-vector-api-30d2830401ec`, and tightened Netflix path blocking to include `/tagged/` and `/followers`. We expanded `/Users/cameronbell/Projects/deep-research-workflow/tests/test_ingest.py` to cover certificate-failure recovery, trusted passthrough redirect chains, Netflix article URL admission, and canonical article-link discovery from Netflix article pages.

### Why this fix and not another
The main alternatives were replacing Netflix with a different publication source, weakening TLS verification, or building a Medium-specific browser automation path. We rejected global TLS weakening because it would lower the crawler’s security bar for every source. We rejected the `netflixtechblog.medium.com` route because it returned `403` in this runtime. We also held off on replacing Netflix because Netflix is still part of the declared corpus and Phase 2 eval assumptions, so a source replacement would create avoidable spec drift. The article-seed approach was chosen because it preserved the intended source while staying within the existing ingestion architecture.

### What to watch for
Netflix is now operational, but it is still more curated and source-specific than the other documentation sources. The current crawl starts from article-level seeds rather than a clean server-rendered archive, so if Netflix changes how those canonical article URLs behave, the source may need another maintenance pass. The trust-store fallback and Medium passthrough are also source-specific behaviors that should be kept tightly scoped so they do not accidentally broaden redirect handling for unrelated hosts.

### What I learned
I learned that “the source is blocked” and “the source is unseedable” are different problems, and it is important to separate them before deciding to replace a corpus source. I also learned that a curated article seed list can still be a real crawl if the discovered links are canonicalized and allowed to expand, but it should be documented honestly as a deliberate tradeoff rather than treated like a generic docs crawl.

---

## 2026-03-24 — Phase 1

### Ingestion / Meta category-driven discovery

### What we were trying to do
Keep Meta as an experimental RFC/ADR source, but stop depending on a fixed list of recent article seeds. The goal was to let the crawler reach the broader archive through category pages without chunking the category listings themselves.

### What happened
The initial `meta-rfcs` implementation worked, but it started from hardcoded recent article URLs and mainly discovered the same neighborhood of linked posts. Meta category pages such as `https://engineering.fb.com/category/core-infra/` were fetchable, but under the previous parser contract a thin or listing-like page returned `None`, which meant its discovered links were effectively lost even when the HTML clearly contained article URLs.

### Root cause
The crawler was coupling “this page should become a document” with “this page can contribute discovered links.” That worked for docs-like sources, but it broke archive/category-driven sources where the useful content is in the outgoing article links rather than in the category page body.

### What we changed
We updated `/Users/cameronbell/Projects/deep-research-workflow/rag/ingest.py` to introduce `PageParseResult`, separating parsed documents from discovered links. `_parse_document(...)` now returns links even when a page is skipped for being thin or listing-like, and `ingest_source(...)` now enqueues those links regardless of whether a document was produced. We reconfigured `meta-rfcs` in `/Users/cameronbell/Projects/deep-research-workflow/rag/ingest.py` to use category seeds like `/category/core-infra/`, `/category/data-infrastructure/`, and `/category/developer-tools/`, removed `/category/` from Meta’s blocked paths, and raised Meta’s `max_pages` to `80`. We added tests in `/Users/cameronbell/Projects/deep-research-workflow/tests/test_ingest.py` to verify that listing pages can surface article links without being chunked.

### Why this fix and not another
The alternative was to keep expanding the hardcoded article seed list, but that would have turned Meta into a manually curated import instead of a crawl. Generalizing discovery from skipped listing pages solved the real architectural issue and also benefits other archive-style sources such as Cloudflare, Uber, and GitHub.

### What to watch for
The generalized behavior makes listing pages more useful, but it also increases the importance of source-specific blocklists because noisy archive pages can now feed the queue even when they are never chunked. Meta category pages currently work well, but if the site adds new taxonomy routes or tag variants, those may need to be blocked explicitly to keep discovery focused.

### What I learned
I learned that “skip this page” and “ignore this page” are not the same thing in a crawler. A listing page can be low-value as content and still be high-value as a discovery surface, and the parser contract needed to reflect that distinction.

---

## 2026-03-24 — Phase 1

### Ingestion / Cookie and consent chrome filtering

### What we were trying to do
Clean up cookie and consent banner noise that was still leaking into crawled content despite the existing structural noise stripping. The goal was to remove common banner elements more precisely before they could become part of chunk text.

### What happened
The ingestion code already removed broad noise patterns like `nav`, `footer`, and class/id tokens containing `cookie`, but it did not explicitly target common banner selectors or `aria-label` patterns. That meant the system was resilient to some cookie markup but not all of it, and it left an unclear gap between what the crawler “usually” filtered and what it explicitly guaranteed.

### Root cause
The original noise stripping logic relied mostly on broad class/id token matching and role attributes. That covered many cases, but modern consent UI often uses more specific selectors or `aria-label` values that were not being checked directly.

### What we changed
We updated `/Users/cameronbell/Projects/deep-research-workflow/rag/ingest.py` to add `_NOISE_CLASS_ID_TOKENS` and `_NOISE_SELECTORS`, then expanded `_strip_noise()` to decompose elements matching selectors such as `.cookie-banner`, `.cookie-consent`, `#cookie-notice`, `.consent`, `#consent-banner`, `[aria-label*='cookie']`, and `[aria-label*='consent']`. We added tests in `/Users/cameronbell/Projects/deep-research-workflow/tests/test_ingest.py` to confirm those elements are removed while substantive article content remains.

### Why this fix and not another
The alternative was to push more cookie-related words into `_NOISE_SECTION_TERMS`, but that would only affect rendered text and heading selection, not DOM cleanup. We chose structural stripping because cookie and consent banners are fundamentally layout chrome, and the most reliable place to remove them is before the content renderer sees them.

### What to watch for
Selector-based stripping is more precise, but it also depends on recurring markup conventions. If a source uses a novel consent UI that does not match these selectors or token patterns, cookie noise could still leak through and would need another small rule added to `_strip_noise()`.

### What I learned
I learned that the existing “good enough” cookie filtering was too implicit. Being explicit about the selectors we mean to strip makes the ingestion behavior easier to reason about and easier to verify with tests.

---

## 2026-03-24 — Phase 1

### Ingestion / Meta footer noise truncation

### What we were trying to do
Stop Meta article footer chrome from being chunked into the corpus. The goal was to remove trailing sections like “Share this”, “Read more in”, “Read the paper”, and “Acknowledgments” without harming the main article body.

### What happened
Meta article pages were successfully parsed, but some chunks still contained footer content that appeared after the main article text. These sections were not path-level noise and were not separate pages, so URL filters could not help. They passed through because the article container itself was substantive, which meant short footer headings at the end of the container were being rendered just like normal content.

### Root cause
The text noise terms that existed in `_NOISE_SECTION_TERMS` only affected heading selection, not content truncation. So even if a footer heading was recognized as noisy in principle, the rendered article body still continued past it.

### What we changed
We expanded `_NOISE_SECTION_TERMS` in `/Users/cameronbell/Projects/deep-research-workflow/rag/ingest.py` to include `share this`, `read more in`, `read the paper`, and `acknowledgments`. We also updated `_render_content(...)` in `/Users/cameronbell/Projects/deep-research-workflow/rag/ingest.py` so that short noise-section headings stop rendering when they appear as trailing footer boundaries inside an otherwise valid article container. We added regression coverage in `/Users/cameronbell/Projects/deep-research-workflow/tests/test_ingest.py` to confirm that these footer phrases no longer appear in parsed document content.

### Why this fix and not another
The alternative was to try to remove these sections with more CSS selectors, but the problem was not primarily structural; it was semantic. These footer sections live inside otherwise valid article containers, so the better fix was to teach the renderer where to stop once it reaches known footer boundary text.

### What to watch for
Text-based footer truncation is only as good as the phrases it recognizes. If Meta or another source changes its footer language, the cutoff terms may need to be expanded. There is also a small risk of over-truncation if a real article uses one of these phrases in a substantive heading, so future adjustments should stay conservative.

### What I learned
I learned that some ingestion problems are not about choosing the right container, but about knowing when to stop reading inside the right container. Footer chrome can survive all the structural filters if it shares the article DOM, so the renderer needs a semantic stopping point.

---

## 2026-03-24 — Phase 1

### Ingestion / Anthropic source scope tightening

### What we were trying to do
Bring the Anthropic source back to documentation-only crawling after the broader crawler improvements made it capable of wandering into the product app. The goal was to keep Anthropic coverage high without polluting the corpus with settings, dashboard, workbench, usage, or cookbook pages.

### What happened
Once the crawler became more permissive and resilient, `anthropic-docs` started exploring routes like `https://platform.claude.com/settings/keys`, `https://platform.claude.com/workbench`, `https://platform.claude.com/dashboard`, `https://platform.claude.com/usage`, and `https://platform.claude.com/cookbook/...` during live re-ingestion. The parser and chunker were functioning, but the source boundary was now too loose for Anthropic’s mixed docs/product host.

### Root cause
Anthropic documentation and product surfaces live on the same host, and the source config was still relying mainly on start URLs plus a minimal blocklist. That was not enough once same-host discovery was enabled, because the crawler had no source-specific rule telling it to stay inside the documentation path hierarchy.

### What we changed
We updated `anthropic-docs` in `/Users/cameronbell/Projects/deep-research-workflow/rag/ingest.py` to add `allowed_path_prefixes=["/docs/en/", "/en/docs/"]` and blocked path substrings for `/settings`, `/workbench`, `/dashboard`, `/usage`, `/cost`, `/cookbook`, `/cookbooks`, and `/cdn-cgi/`. We added a source-specific test in `/Users/cameronbell/Projects/deep-research-workflow/tests/test_ingest.py` to confirm that docs URLs remain allowed while those product/account routes are rejected.

### Why this fix and not another
The alternative was to keep broad same-host crawling and add more parser-side heuristics for Anthropic app pages, but that would have mixed source definition problems with content extraction problems. We chose path constraints because Anthropic’s boundary is a source-scoping issue: the docs tree is known, stable enough to encode, and easier to maintain than trying to parse our way out of the wrong pages.

### What to watch for
Anthropic’s docs site uses redirects and some cross-host transitions from `docs.anthropic.com` back to `platform.claude.com`, so the allowed prefixes need to keep matching both URL shapes. If Anthropic changes its docs path structure later, this source config will need to be updated or the crawler could become too restrictive.

### What I learned
I learned that host-level allow rules are not enough when a vendor mixes product UI and docs on one domain. In those cases, source-specific path constraints are not optional; they are the real boundary of the corpus.

---

## 2026-03-24 — Phase 1

### Ingestion / Supabase insert hardening for large runs

### What we were trying to do
Prevent larger ingestion runs from failing mid-stream on repeated Supabase transport errors after the first round of retry hardening had already been added. The goal was to make document inserts degrade gracefully under flaky HTTP/2/TLS behavior instead of aborting a full source run.

### What happened
A clean Anthropic re-ingest still died during a larger insert phase with repeated `httpx.ReadError: [SSL: SSLV3_ALERT_BAD_RECORD_MAC]`. The retry path fired twice, then the command exited with code `1`. This showed that the first hardening round was directionally correct but still too brittle for larger document insert batches under the current Supabase transport behavior.

### Root cause
The insert path still treated each fixed-size batch as all-or-nothing. If a retryable transport failure persisted for one batch, the system could still fail the whole document even though a smaller payload might have succeeded. The retry count and batch size helped, but they did not give the insert layer a fallback strategy when a specific batch shape remained unstable.

### What we changed
We updated `/Users/cameronbell/Projects/deep-research-workflow/rag/ingest.py` to increase `_MAX_INSERT_ATTEMPTS` from `3` to `4`, reduce `_MAX_INSERT_BATCH_SIZE` from `25` to `20`, add `_is_retryable_supabase_exception(...)`, and change `_insert_chunk_rows(...)` so retryable failing batches are recursively split into smaller sub-batches instead of aborting immediately. We added tests in `/Users/cameronbell/Projects/deep-research-workflow/tests/test_ingest.py` to verify successful batch splitting after repeated transport failures and to confirm that non-retryable `APIError` cases still fail fast without splitting.

### Why this fix and not another
The alternatives were to leave the current retries alone and keep rerunning failed ingests, or to make a more invasive transport change such as replacing the Supabase HTTP client path entirely. We chose adaptive batch splitting because it directly targets the observed failure mode with a small local change, preserves the existing Supabase architecture, and gives the insert layer a graceful fallback before more invasive work becomes necessary.

### What to watch for
Recursive splitting makes the system more robust, but it can also increase latency when a source is already under transport stress because one failing batch may turn into several smaller insert calls. If the underlying Supabase instability worsens, this strategy may still not be enough on its own and a lower-level transport change could still be needed.

### What I learned
I learned that retrying the same failing batch is not always enough; sometimes resilience requires changing the shape of the request, not just repeating it. I also learned that insert hardening needs to be tested on large, realistic source runs because that is where the transport edge cases actually show up.
