# Design Decisions

## 1. Why Routing + Evaluator Loop

Routing and evaluation are complementary controls:

- Routing chooses the minimum viable workflow for the query class
- Evaluation adds a quality gate where uncertainty and complexity are higher

This pairing avoids paying maximum cost for every task while still supporting stronger outputs on high-complexity requests.

## 2. Why Async Search Execution

Search tasks are independent IO-bound operations, so concurrency is the natural fit. Running searches in parallel lowers end-to-end latency and keeps the orchestrator responsive during retrieval.

## 3. Why Typed Intermediate Outputs

Pydantic output schemas make handoffs explicit and machine-validated. This is critical for multi-agent orchestration because each step depends on stable structure from prior steps.

## 4. Cost vs Quality Tradeoff Strategy

The strategy is rule-based:

- `quick` route: fewer searches, skip evaluator loop
- non-`quick` routes: more searches, run evaluator loop

This explicitly trades off speed/cost for depth/quality based on query characteristics.

## 5. Why Keep `app.py` as HF Entrypoint

`app.py` launches Gradio with `server_name="0.0.0.0"` and `server_port=7860`, which aligns with Hugging Face Spaces expectations and avoids local browser launch behavior.

## 6. Documentation Architecture Choice

Documentation is standardized under `/docs` to keep README scan-friendly for recruiters while preserving deeper technical rationale in dedicated files.
