# Procurement Copilot evaluation memo

Do not ship either architecture yet; use A for a demo if needed. Holdout has not run, so the pre-registered ship rule cannot be applied.

## Evidence

Both architectures ran on the same 22 dev cases using GPT-OSS 120B. B's outcomes include six deterministic fail-closed fallbacks.

| Metric | A | B |
|---|---:|---:|
| Recommendation accuracy, including fallback | 0.955 | 0.500 |
| Escalation recall | 1.000 | 1.000 |
| Approval match | 1.000 | 0.136 |
| Grounding | 1.000 | 1.000 |
| p50 / p95 latency (ms) | 157,965.6 / 161,434.0 | 200,143.6 / 227,034.8 |
| LLM calls per request | 5.91 | 6.82 |
| Trace-reported tokens | 141,363 | 182,876* |
| Agent execution failures | 0 | 6 |

*B's trace total is a subtotal: C-005 has no per-case token usage. The local 120B usage ledger recorded 184,695 tokens for B. B failed on C-001, C-003, C-004, C-005, C-015, and C-017. It also over-escalated non-security cases, which reduced recommendation and approval accuracy. A's only recommendation mismatch is C-003. Details are in `results/dev_checkpoint_report.md`.

## Decision and controls

A is the provisional demo choice because B's matched-model dev results are worse, not because A passed the ship rule. Do not call this a validated release decision; run holdout for both architectures on the same model before applying the pre-registered rule. Dev contains no injection cases, so its injection score establishes nothing about injection resistance.

Code enforced fail-closed outcomes when model calls failed. The C-003 trace also shows why thresholds, required information, approvals, grounding, and final purchasing decisions must remain code- or human-owned. The model interprets evidence and drafts text; it does not approve purchases.

Revisit the choice if matched holdout changes the comparison, or if request volume, policy types, model, or provider changes. Known interim risks are the unrun holdout, six B execution failures, and B's excess escalation on dev.

Word count: 326
