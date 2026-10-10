# Procurement Copilot evaluation memo

No architecture is cleared for shipment: holdout has not run, and the dev runs used different model versions.

## Evidence

Both architectures have traces for the same 22 dev cases. A used GPT-OSS 120B; B used GPT-OSS 20B. B's measured totals include deterministic fallbacks.

| Metric | A, 22 dev cases | B, 22 dev cases |
|---|---:|---:|
| Recommendation accuracy, including fallback | 0.955 | 1.000 |
| Escalation recall | 1.000 | 1.000 |
| Approval match | 1.000 | 1.000 |
| Grounding | 1.000 | 1.000 |
| p50 / p95 latency (ms) | 157,965.6 / 161,434.0 | 181,684.0 / 223,346.0 |
| LLM calls per request | 5.91 | 6.68 |
| Provider-reported tokens | 141,363 | 175,836 |
| Agent execution failures | 0 | 6 |

These are dev measurements, not holdout evidence. B's recommendation score includes six fail-closed deterministic outputs where model calls failed (C-007, C-008, C-011, C-013, C-016, C-018). Its injection score is not informative: dev contains no injection cases. A's only recommendation mismatch is C-003. Metrics and failure details are in `results/dev_checkpoint_report.md`.

## Decision and controls

Do not apply the pre-registered ship rule until holdout is run with both architectures on the same model. A is the only reasonable demo fallback because its 22 model runs completed, but that is not a ship decision. B matched all labels on dev, including fallback labels, yet six model failures and the model-version difference prevent a fair comparison.

Code retained deterministic outcomes when model calls failed. The C-003 trace also shows why thresholds, required information, approvals, grounding, and final purchasing decisions must remain code- or human-owned. The model interprets evidence and drafts text; it does not approve purchases.

Accepted interim risks: no holdout result, no matched-model comparison, and six B execution failures. Revisit when both architectures complete matched dev and holdout runs on the selected model. Re-run evaluation sooner if request volume, policy types, or model/provider changes. Injection claims require the holdout injection cases; the current dev scores do not establish injection resistance.

Word count: 348
