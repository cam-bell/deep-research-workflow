# Phase 2 Spec — Evaluation Harness

**Prerequisite**: Phase 1 complete. At least 500 chunks in corpus.

**Objective**: Replace directional quality claims with reproducible metrics.
Every number in the documentation must come from a script that can be re-run.

**Verification**: `eval/results/baseline.md` exists in the repo, contains
RAGAS scores above 0, and the CI workflow fails a PR that would drop scores
by more than 10%.

**Must not change**: `agents/`, `app.py`, `requirements.txt`

**New dependencies**:
```
ragas
datasets
pandas
```

---

## Task 2.1 — Fixed Query Set

**Estimated agent time**: 10 minutes
**Files to create**: `eval/queries.json`

Create 25 evaluation queries with reference answers. These must be
answerable from the corpus, not from general LLM knowledge alone.
Distribute across all five corpus sources.

```json
[
  {
    "id": "gitlab-001",
    "query": "What is GitLab's policy on blameless post-mortems and how should they be structured?",
    "source": "GitLab Handbook",
    "reference_answer": "GitLab conducts blameless post-mortems after incidents. The focus is on process and system failures, not individual blame. A post-mortem should include a timeline, root cause analysis, and action items. They should be completed within 48 hours of an incident.",
    "route": "technical"
  },
  {
    "id": "gitlab-002",
    "query": "What is GitLab's approach to handbook-first communication?",
    "source": "GitLab Handbook",
    "reference_answer": "GitLab operates handbook-first, meaning decisions and processes are documented in the handbook before or immediately after being communicated verbally. This ensures remote-friendly, asynchronous access to information.",
    "route": "deep"
  },
  {
    "id": "stripe-001",
    "query": "How does Stripe handle idempotency keys and what happens if the same key is used twice?",
    "source": "Stripe API Documentation",
    "reference_answer": "Stripe uses idempotency keys to safely retry requests. If the same key is used for a second request with the same parameters, Stripe returns the result of the original request. If parameters differ, a 400 error is returned.",
    "route": "technical"
  },
  {
    "id": "stripe-002",
    "query": "What is the difference between a Stripe PaymentIntent and a Charge?",
    "source": "Stripe API Documentation",
    "reference_answer": "PaymentIntents are the recommended way to accept payments and support 3D Secure and SCA. Charges are the legacy API. PaymentIntents track the lifecycle of a payment through multiple steps.",
    "route": "comparative"
  },
  {
    "id": "anthropic-001",
    "query": "What are the trade-offs between Claude Sonnet and Claude Opus models for production use?",
    "source": "Anthropic API Documentation",
    "reference_answer": "Claude Opus is the most capable model for complex tasks but is slower and more expensive. Claude Sonnet balances capability and speed, making it suitable for most production workloads. The choice depends on task complexity and latency requirements.",
    "route": "comparative"
  },
  {
    "id": "anthropic-002",
    "query": "How does Anthropic's tool use feature work and what are its limitations?",
    "source": "Anthropic API Documentation",
    "reference_answer": "Anthropic's tool use allows Claude to call external functions. The model receives tool definitions, decides when to call them, and returns structured tool call requests. Limitations include no parallel tool calling in some versions and token cost overhead.",
    "route": "technical"
  },
  {
    "id": "openai-001",
    "query": "How does OpenAI's structured output feature differ from function calling?",
    "source": "OpenAI API Documentation",
    "reference_answer": "Structured outputs guarantee JSON schema conformance in the response. Function calling is for tool use where the model decides to invoke external functions. Structured outputs use response_format with a JSON schema, while function calling uses the tools parameter.",
    "route": "comparative"
  },
  {
    "id": "openai-002",
    "query": "What are the context window limits for GPT-4o and how does truncation work?",
    "source": "OpenAI API Documentation",
    "reference_answer": "GPT-4o supports a 128k token context window. When the context exceeds this limit, older messages are truncated. Developers are responsible for managing context length to avoid unexpected truncation.",
    "route": "technical"
  },
  {
    "id": "aws-001",
    "query": "What does the AWS Well-Architected Framework recommend for reliability in multi-region deployments?",
    "source": "AWS Well-Architected Framework",
    "reference_answer": "The Reliability pillar recommends using multiple Availability Zones and Regions for fault tolerance, implementing health checks, using Route 53 for DNS failover, and designing for graceful degradation when a region fails.",
    "route": "deep"
  },
  {
    "id": "aws-002",
    "query": "What are the five pillars of the AWS Well-Architected Framework?",
    "source": "AWS Well-Architected Framework",
    "reference_answer": "The five pillars are: Operational Excellence, Security, Reliability, Performance Efficiency, and Cost Optimization. A sixth pillar, Sustainability, was added later.",
    "route": "quick"
  },
  {
    "id": "aws-003",
    "query": "What does AWS recommend for cost optimisation in cloud workloads?",
    "source": "AWS Well-Architected Framework",
    "reference_answer": "AWS recommends right-sizing instances, using Reserved Instances or Savings Plans for predictable workloads, leveraging Spot Instances for fault-tolerant tasks, and continuously monitoring and eliminating unused resources.",
    "route": "technical"
  },
  {
    "id": "rfc-001",
    "query": "How does Cloudflare's engineering team approach graceful degradation in their edge network?",
    "source": "Engineering RFCs and ADRs",
    "reference_answer": "Cloudflare uses a tiered degradation model where edge nodes can serve cached content even when origin is unreachable. They use circuit breakers, health checks, and fallback rules to maintain availability.",
    "route": "technical"
  },
  {
    "id": "rfc-002",
    "query": "What trade-offs did Netflix consider when moving from monolith to microservices?",
    "source": "Engineering RFCs and ADRs",
    "reference_answer": "Netflix moved to microservices to enable independent scaling and deployment. Trade-offs included increased operational complexity, distributed system failure modes, and the need for a service mesh. They built tools like Hystrix for circuit breaking and Eureka for service discovery.",
    "route": "comparative"
  },
  {
    "id": "gitlab-003",
    "query": "How does GitLab approach remote work and what are their core remote work principles?",
    "source": "GitLab Handbook",
    "reference_answer": "GitLab is an all-remote company. Core principles include async communication, handbook-first documentation, results over hours, and inclusive meeting practices. They document extensively to enable asynchronous collaboration across time zones.",
    "route": "deep"
  },
  {
    "id": "gitlab-004",
    "query": "What is GitLab's code review process and what are the responsibilities of a maintainer?",
    "source": "GitLab Handbook",
    "reference_answer": "GitLab requires code review before merging. Reviewers check functionality, security, and code quality. Maintainers have merge authority and are responsible for codebase health. The process uses a reviewer-then-maintainer two-step review.",
    "route": "technical"
  },
  {
    "id": "stripe-003",
    "query": "How does Stripe's webhook system work and how should developers handle webhook failures?",
    "source": "Stripe API Documentation",
    "reference_answer": "Stripe sends webhook events via HTTP POST to configured endpoints. Developers should return a 200 response immediately and process asynchronously. Stripe retries failed webhooks with exponential backoff over 3 days. Endpoints should be idempotent.",
    "route": "technical"
  },
  {
    "id": "stripe-004",
    "query": "What is the difference between Stripe Connect and the standard Stripe API?",
    "source": "Stripe API Documentation",
    "reference_answer": "Stripe Connect enables platforms to process payments on behalf of connected accounts. The standard API is for direct payment processing. Connect adds concepts like connected accounts, application fees, and transfer routing.",
    "route": "comparative"
  },
  {
    "id": "anthropic-003",
    "query": "What are Anthropic's rate limits and how should developers handle rate limit errors?",
    "source": "Anthropic API Documentation",
    "reference_answer": "Anthropic rate limits are measured in tokens per minute and requests per minute. Rate limit errors return a 429 status. Developers should implement exponential backoff with jitter and monitor usage via the API headers.",
    "route": "technical"
  },
  {
    "id": "openai-003",
    "query": "How does the OpenAI Assistants API differ from the Chat Completions API?",
    "source": "OpenAI API Documentation",
    "reference_answer": "The Assistants API manages conversation threads, file attachments, and tool use with persistent state. Chat Completions is stateless — the caller manages history. Assistants is higher-level and suited for multi-turn agent workflows.",
    "route": "comparative"
  },
  {
    "id": "aws-004",
    "query": "What does the AWS Well-Architected Framework say about security in the cloud?",
    "source": "AWS Well-Architected Framework",
    "reference_answer": "The Security pillar covers identity and access management, detection, infrastructure protection, data protection, and incident response. Key practices include least privilege access, encryption at rest and in transit, and automated security scanning.",
    "route": "deep"
  },
  {
    "id": "rfc-003",
    "query": "How does Uber's engineering team manage database migrations at scale?",
    "source": "Engineering RFCs and ADRs",
    "reference_answer": "Uber uses online schema changes to avoid table locks, employs shadow tables during migrations, and runs migrations during low-traffic windows. They have tooling that validates migrations in staging before production rollout.",
    "route": "technical"
  },
  {
    "id": "cross-001",
    "query": "Compare how Anthropic and OpenAI handle system prompts and their effect on model behaviour",
    "source": "Anthropic API Documentation, OpenAI API Documentation",
    "reference_answer": "Both support system prompts but with different conventions. Anthropic's system prompt sets context and guidelines. OpenAI uses a system role message. Both affect model behaviour throughout the conversation, but Anthropic's Constitutional AI training means it may override certain instructions.",
    "route": "comparative"
  },
  {
    "id": "cross-002",
    "query": "What do GitLab and AWS both recommend about incident response processes?",
    "source": "GitLab Handbook, AWS Well-Architected Framework",
    "reference_answer": "Both recommend defined incident response runbooks, clear escalation paths, post-incident reviews, and automation where possible. GitLab emphasises blameless culture; AWS emphasises automated detection and response.",
    "route": "deep"
  },
  {
    "id": "gitlab-005",
    "query": "How does GitLab define and measure engineering productivity?",
    "source": "GitLab Handbook",
    "reference_answer": "GitLab measures engineering productivity through deployment frequency, lead time for changes, mean time to recovery, and change failure rate (the DORA metrics). They also track merge request cycle time and review turnaround.",
    "route": "technical"
  },
  {
    "id": "aws-005",
    "query": "What is the AWS Shared Responsibility Model?",
    "source": "AWS Well-Architected Framework",
    "reference_answer": "AWS manages security of the cloud (infrastructure, hardware, networking). Customers manage security in the cloud (data, applications, identity, operating systems). The boundary depends on the service type: IaaS, PaaS, or SaaS.",
    "route": "quick"
  }
]
```

**Verification**: `python -c "import json; q = json.load(open('eval/queries.json')); print(len(q))"` prints `25`.

---

## Task 2.2 — RAGAS Evaluation Script

**Estimated agent time**: 15 minutes
**Files to create**: `eval/run_ragas.py`

```python
# Expected CLI interface
# uv run python eval/run_ragas.py                  — full run, all 25 queries
# uv run python eval/run_ragas.py --subset ci      — 5-query CI subset
# uv run python eval/run_ragas.py --output results/run_YYYYMMDD.json
```

Requirements:
- Load queries from `eval/queries.json`
- For each query: run `research_manager.run(query)` and capture the output
- Also retrieve context chunks with `rag.retrieve.retrieve(query)`
- Score with RAGAS metrics:
  - `faithfulness` — answer grounded in retrieved context
  - `answer_relevancy` — answer addresses the query
  - `context_recall` — retrieval surfaces the right chunks
- Output per-query scores and aggregate means to JSON
- CI subset: use queries with ids ending in `-001` (one per source, 5 total)
- Print summary table to stdout on completion

**Verification**: `uv run python eval/run_ragas.py --subset ci` completes
and prints a table with scores between 0 and 1.

---

## Task 2.3 — LLM-as-Judge Script

**Estimated agent time**: 10 minutes
**Files to create**: `eval/run_judge.py`

```python
# Expected CLI interface
# uv run python eval/run_judge.py --input results/run_YYYYMMDD.json
```

Scoring rubric (hardcode in the script):

```python
JUDGE_RUBRIC = """
Score the research report on a scale of 1-10 based on:
- Accuracy (1-10): Are all claims supported by sources? No hallucinations?
- Completeness (1-10): Does the report fully address the query?
- Coherence (1-10): Is the report well-structured and readable?
- Citation quality (1-10): Are sources cited correctly and usefully?

Return a JSON object with keys: accuracy, completeness, coherence,
citation_quality, overall (mean of above), reasoning (one sentence).
"""
```

Requirements:
- Use `gpt-4o` (not mini) for final judge scoring
- Output CSV with columns: query_id, accuracy, completeness, coherence,
  citation_quality, overall, reasoning
- Save to `eval/results/judge_YYYYMMDD.csv`

**Verification**: Script runs on sample input and produces a valid CSV.

---

## Task 2.4 — Routing Benchmark

**Estimated agent time**: 10 minutes
**Files to create**: `eval/run_benchmark.py`

```python
# Expected CLI interface
# uv run python eval/run_benchmark.py
```

Requirements:
- Run the full 25-query set against all four routing paths:
  `quick`, `deep`, `technical`, `comparative`
- For each run record: route, latency_ms, token_count, cost_usd, ragas_faithfulness
- Output markdown table to `eval/results/baseline.md`
- Table format:

```markdown
| Route       | Avg Latency | Avg Tokens | Avg Cost | Faithfulness |
|-------------|-------------|------------|----------|--------------|
| quick       | Xs          | X          | $X       | X.XX         |
| deep        | Xs          | X          | $X       | X.XX         |
| technical   | Xs          | X          | $X       | X.XX         |
| comparative | Xs          | X          | $X       | X.XX         |
```

**Verification**: `eval/results/baseline.md` exists with a populated table
and numbers that are non-zero.

---

## Task 2.5 — CI Eval Regression Workflow

**Estimated agent time**: 10 minutes
**Files to create**: `.github/workflows/ci.yml`

```yaml
name: CI — Eval Regression

on:
  pull_request:
    branches: [main]

jobs:
  eval-regression:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - name: Run CI eval subset
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          SUPABASE_DB_URL: ${{ secrets.SUPABASE_DB_URL }}
        run: uv run python eval/run_ragas.py --subset ci --output eval/results/ci_run.json
      - name: Check regression against baseline
        run: uv run python eval/check_regression.py --baseline eval/results/baseline.md --current eval/results/ci_run.json --threshold 0.10
```

Also create `eval/check_regression.py`:
- Load baseline scores from `baseline.md`
- Load current scores from the CI run JSON
- If any metric dropped by more than `--threshold` (10%), exit with code 1
- Print a human-readable diff of scores

**Verification**: Create a dummy PR. The CI workflow should appear in
the GitHub Actions tab and run the 5-query subset.

---

## Phase 2 Done When

- [ ] `eval/queries.json` has 25 queries covering all 5 corpus sources
- [ ] `uv run python eval/run_ragas.py --subset ci` completes without errors
- [ ] `eval/results/baseline.md` committed with routing benchmark table
- [ ] RAGAS faithfulness score in baseline is above 0.7
- [ ] `.github/workflows/ci.yml` runs on every PR
- [ ] `docs/evaluation.md` updated with methodology and baseline scores
