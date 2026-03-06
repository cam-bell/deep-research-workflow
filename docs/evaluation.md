# Evaluation

## Goal

Assess whether orchestration patterns improve research workflow characteristics:

- latency behavior
- cost behavior
- output quality behavior

## Current Evidence Level

This repository currently demonstrates implementation patterns and expected effects, but does not yet include a formal benchmark harness with controlled datasets and recorded runs.

Because of that, claims should be interpreted as directional and reproducibility-oriented, not fixed headline percentages.

## Recommended Metrics

- End-to-end runtime per route (`quick`, `deep`, `technical`, `comparative`)
- Number of searches executed per route
- Number of evaluator revisions per run
- Token usage and cost per run
- Human-rated quality rubric (accuracy, completeness, coherence, relevance)

## Reproducibility Procedure

1. Prepare a fixed query set with route diversity.
2. Run each query through auto-routing mode and record:
   - selected route
   - elapsed time
   - revision count
   - token/cost telemetry
3. Run a controlled baseline variant (for example, sequential search, no evaluator loop).
4. Compare medians and variance across at least 10 runs per query category.
5. Store raw outputs and scoring sheets for auditability.

## Acceptance Criteria for Future Hard Claims

Only publish hard numeric claims when:

- benchmark script and raw results are committed
- methodology is documented and repeatable
- quality scoring rubric and raters are defined
- confidence intervals or run variance are shown

## Known Limitations

- No pinned benchmark corpus in repo yet
- No automated telemetry export in current scripts
- No CI job enforcing docs-to-metrics consistency

## Next Step

Add a benchmark script and results artifact, then update this document with measured numbers and methodology references.
