# Evaluation report

Split: `dev`. Mode: `replay`.

## Overall

| Architecture | Runs | Recommendation accuracy | Escalation recall | Escalation precision | Under-escalation | Approvals match | Grounding | Policy compliance | Injection resistance | Failure handling | p50 ms | p95 ms | LLM calls/request | Tool calls/request |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 22 | 1.000 | 1.000 | 1.000 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 157960.8 | 161428.3 | 5.91 | 6.00 |

## Per category

### Architecture A

| Category | Runs | Accuracy |
|---|---:|---:|
| Approval threshold boundaries | 3 | 1.000 |
| Clean approve path | 3 | 1.000 |
| Conflicting or expired vendor info | 4 | 1.000 |
| Existing tool solves it | 4 | 1.000 |
| Incomplete / ambiguous request | 4 | 1.000 |
| Security / privacy sensitive | 4 | 1.000 |

Failed cases:

- None.

## Failure analysis

See the per-case trace records in `results/raw/`. Interpret this section from the actual traces before packaging results.
