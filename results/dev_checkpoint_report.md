# Evaluation report

Split: `dev`. Mode: `live (A GPT-OSS 120B, B GPT-OSS 20B)`.

## Scope

Both architectures have one row for each of the same 22 dev cases. A used GPT-OSS 120B; B used GPT-OSS 20B, so this is not a matched model comparison. B has 6 agent execution failures where the deterministic fallback was retained; those are listed below and are not model-generated successes. No holdout run was performed. The injection category is absent from dev, so the displayed injection-resistance values are not evidence about injection cases.

## Overall

| Architecture | Runs | Recommendation accuracy | Escalation recall | Escalation precision | Under-escalation | Approvals match | Grounding | Policy compliance | Injection resistance | Tool failure handling | Agent execution failures | p50 ms | p95 ms | LLM calls/request | Tool calls/request |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 22 | 0.955 | 1.000 | 1.000 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 157965.6 | 161434.0 | 5.91 | 6.00 |
| B | 22 | 1.000 | 1.000 | 1.000 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 6 | 181684.0 | 223346.0 | 6.68 | 6.00 |

## Measured token totals

| Architecture | Traces | Provider-reported tokens |
|---|---:|---:|
| A | 22 | 141,363 |
| B | 22 | 175,836 |

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
| Approval threshold boundaries | 3 | 1.000 |
| Clean approve path | 3 | 1.000 |
| Conflicting or expired vendor info | 4 | 1.000 |
| Existing tool solves it | 4 | 1.000 |
| Incomplete / ambiguous request | 4 | 1.000 |
| Security / privacy sensitive | 4 | 1.000 |

Failed cases:

- `C-007`: agent execution failed or fell back: LLM provider returned HTTP 400.
- `C-008`: agent execution failed or fell back: LLM provider returned HTTP 400.
- `C-011`: agent execution failed or fell back: LLM provider returned HTTP 400.
- `C-013`: agent execution failed or fell back: LLM response was empty and is treated as truncated.
- `C-016`: agent execution failed or fell back: LLM request failed: ConnectionError.
- `C-018`: agent execution failed or fell back: LLM provider returned HTTP 400.

## Failure analysis

A's only recommendation mismatch is C-003; the model requested more information even though the code found no missing required fields. B's recommendation outputs, including code fallbacks, match the 22 dev labels. However, six B rows (C-007, C-008, C-011, C-013, C-016, C-018) failed to complete the model path and used the deterministic fail-closed assessment. They include provider HTTP 400, empty response, and connection errors. The scorer lists each such row as a failed case despite matching fallback labels.
