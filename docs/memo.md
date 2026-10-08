# Procurement Copilot evaluation memo

Do not select a ship architecture yet: holdout has not run, so the pre-registered ship rule cannot be applied.

## Evidence available

These are dev results, not holdout evidence. A completed 22 live cases. B completed four live cases using the prompt before its evidence-ID allowlist fix. They are not a matched comparison.

| Metric | A, 22 cases | B, 4 cases |
|---|---:|---:|
| Recommendation accuracy | 0.955 | 1.000 |
| Escalation recall | 1.000 | 1.000 |
| Grounding | 1.000 | 0.452 |
| Injection resistance | 1.000 | 1.000 |
| p50 / p95 latency (ms) | 157,965.6 / 161,434.0 | 177,642.7 / 201,562.2 |
| LLM calls per request | 5.91 | 8.00 |
| Provider-reported tokens | 141,363 | 36,249 |

The metrics are generated from committed traces in `results/dev_checkpoint_report.md`. B's four cases contain no injection examples; its injection score says nothing about injection performance. Its grounding failures came from analyst evidence IDs outside the canonical allowlist. The prompt was updated afterward, but not live-verified. A's only live recommendation mismatch was C-003.

## Guard behavior and trust boundary

The C-003 trace shows the model mistook a required Privacy approval for missing information. The code guard preserved the deterministic recommendation because no required information was missing. On B's four old-prompt cases, code rejected non-canonical analyst evidence references instead of accepting unsupported citations. These results support using the model to interpret evidence and draft text, not to decide thresholds, approvals, evidence validity, or the final purchase.

## Decision and risks

Do not ship either architecture from this incomplete comparison. Keep A as the dev fallback, not a final selection: it completed the dev set with full grounding, while B's sample is partial and its prompt fix lacks live evidence. The B recommendation score cannot be compared fairly with A's because sample sizes and case coverage differ.

Risks accepted for this interim checkpoint: B grounding remains unverified after the prompt fix; the sample does not establish either architecture's holdout performance; and provider rate limits stopped recent live attempts. Dry-run estimates are not spend guarantees. Revisit after an approved B smoke passes grounding, both architectures have matched dev results, and the user approves holdout. Revisit sooner if request volume, policy types, or the model/provider changes. The pre-registered holdout rule remains authoritative.