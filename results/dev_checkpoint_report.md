# Evaluation report

Split: `dev checkpoint`. Mode: `live (A full, B partial)`.

## Scope

Architecture A contains the full 22-case dev run. Architecture B contains only C-001 through C-004 from the pre-allowlist prompt. The rows are not a completed head-to-head comparison. B's updated evidence-ID prompt has not been live-verified. The holdout split has not been run.

## Overall

| Architecture | Runs | Recommendation accuracy | Escalation recall | Escalation precision | Under-escalation | Approvals match | Grounding | Policy compliance | Injection resistance | Failure handling | p50 ms | p95 ms | LLM calls/request | Tool calls/request |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 22 | 0.955 | 1.000 | 1.000 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 157965.6 | 161434.0 | 5.91 | 6.00 |
| B | 4 | 1.000 | 1.000 | 1.000 | 0 | 1.000 | 0.452 | 1.000 | 1.000 | 1.000 | 177642.7 | 201562.2 | 8.00 | 6.00 |

## Measured token totals

| Architecture | Traces | Provider-reported tokens |
|---|---:|---:|
| A | 22 | 141,363 |
| B | 4 | 36,249 |

## Per category

### Architecture A

| Category | Runs | Accuracy |
|---|---:|---:|
| Approval threshold boundaries | 3 | 1.000 |
| Clean approve path | 3 | 0.667 |
| Conflicting or expired vendor info | 4 | 1.000 |
| Existing tool solves it | 4 | 1.000 |
| Incomplete / ambiguous request | 4 | 1.000 |
| Security / privacy sensitive | 4 | 1.000 |

Failed cases:

- `C-003`: recommendation 'REQUEST_MORE_INFO' != 'RECOMMEND_APPROVAL'.

### Architecture B

| Category | Runs | Accuracy |
|---|---:|---:|
| Clean approve path | 3 | 1.000 |
| Incomplete / ambiguous request | 1 | 1.000 |

Failed cases:

- `C-001`: 12 evidence item(s) are ungrounded.
- `C-002`: 11 evidence item(s) are ungrounded.
- `C-003`: 12 evidence item(s) are ungrounded.
- `C-004`: 11 evidence item(s) are ungrounded.

## Failure analysis

Architecture A's only recommendation mismatch is C-003: the live model returned `REQUEST_MORE_INFO` although code found no missing required fields. The later deterministic guard preserves the code-computed recommendation in replay; the original live result remains a mismatch. Architecture B's four old-prompt cases returned analyst evidence identifiers outside the canonical allowlist, causing grounding failures in C-001 through C-004. The allowlist prompt fix is not represented in these live traces and has not been verified live.
