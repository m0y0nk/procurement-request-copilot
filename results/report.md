# Evaluation report

Split: `dev`. Mode: `live`.

## Overall

| Architecture | Runs | Recommendation accuracy | Escalation recall | Escalation precision | Under-escalation | Approvals match | Grounding | Policy compliance | Injection resistance | Failure handling | p50 ms | p95 ms | LLM calls/request | Tool calls/request |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B | 4 | 1.000 | 1.000 | 1.000 | 0 | 1.000 | 0.452 | 1.000 | 1.000 | 1.000 | 177642.7 | 201562.2 | 8.00 | 6.00 |

## Per category

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

See the per-case trace records in `results/raw/`. Interpret this section from the actual traces before packaging results.
