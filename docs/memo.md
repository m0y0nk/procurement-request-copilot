# Procurement Copilot evaluation memo

The submission cannot select a ship architecture yet: the holdout split has not run, so the pre-registered ship rule cannot be applied.

## Evidence available

The live dev evidence is not a head-to-head comparison. Architecture A completed all 22 dev cases. Architecture B completed only C-001–C-004 with the prompt before the evidence-ID allowlist fix.

| Metric | A, 22 cases | B, 4 cases |
|---|---:|---:|
| Recommendation accuracy | 0.955 | 1.000 |
| Escalation recall | 1.000 | 1.000 |
| Grounding | 1.000 | 0.452 |
| Injection resistance | 1.000 | 1.000 |
| p50 / p95 latency (ms) | 157,965.6 / 161,434.0 | 177,642.7 / 201,562.2 |
| LLM calls per request | 5.91 | 8.00 |
| Measured tokens | 141,363 | 36,249 |

The metrics come from `results/dev_checkpoint_report.md` and committed raw traces. B's four cases contain no injection examples, so its injection score does not establish injection performance. Its grounding score is low because the analyst emitted non-canonical evidence identifiers; the updated prompt allowlist has not been verified in a live run. A's only live recommendation mismatch was C-003. A deterministic guard fixed that recommendation in replay, not in the original live measurement.

## Operational decision

Do not ship either architecture based on these results. Keep Architecture A as the current fallback because it completed the dev set with full grounding, but this is not a final selection. Do not infer that B is better from its higher recommendation accuracy on four cases. The current 22-case dry-run estimates 122,988 tokens for A and 165,614 for B; these values are in `results/dev_dry_run.txt`. Those are projections, not measured spend guarantees. The earlier B four-case projection was below measured usage.

The user-provided Groq limits are 30 requests/minute, 1,000 requests/day, 8,000 tokens/minute, and 200,000 tokens/day. The wait guard stopped a fresh B smoke after the provider requested a wait exceeding the configured maximum. No holdout evaluation or additional live run is approved by this memo.

## Required before final decision

1. Verify the B evidence-ID prompt fix with an approved, budget-checked live smoke.
2. Complete matched dev evaluation for B and inspect traces.
3. Obtain explicit approval before running holdout; preserve its labels.
4. Apply the pre-registered ship rule to the resulting holdout metrics and record the outcome.

Word count: 386
