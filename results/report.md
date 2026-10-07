# Evaluation report

Split: `dev`. Mode: `replay`.

## Overall

| Architecture | Runs | Recommendation accuracy | Escalation recall | Escalation precision | Under-escalation | Approvals match | Grounding | Policy compliance | Injection resistance | Failure handling | p50 ms | p95 ms | LLM calls/request | Tool calls/request |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 1 | 1.000 | 1.000 | 1.000 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 143092.3 | 143092.3 | 6.00 | 6.00 |

## Per category

### Architecture A

| Category | Runs | Accuracy |
|---|---:|---:|
| Clean approve path | 1 | 1.000 |

Failed cases:

- None.

## Failure analysis

See the per-case trace records in `results/raw/`. Interpret this section from the actual traces before packaging results.
