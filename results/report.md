# Evaluation report

Split: `dev`. Mode: `replay`.

## Overall

| Architecture | Runs | Recommendation accuracy | Escalation recall | Escalation precision | Under-escalation | Approvals match | Grounding | Policy compliance | Injection resistance | Failure handling | p50 ms | p95 ms | LLM calls/request | Tool calls/request |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 1 | 0.000 | 1.000 | 0.000 | 0 | 0.000 | 1.000 | 0.000 | 1.000 | 1.000 | 163205.5 | 163205.5 | 7.00 | 6.00 |

## Per category

### Architecture A

| Category | Runs | Accuracy |
|---|---:|---:|
| Clean approve path | 1 | 0.000 |

Failed cases:

- `C-001`: recommendation 'ESCALATE_SECURITY' != 'USE_EXISTING_TOOL'; approvals ['Legal', 'Manager', 'Security'] != ['Manager', 'Privacy']; flags missing=['privacy_review_required'], forbidden=[].

## Failure analysis

See the per-case trace records in `results/raw/`. Interpret this section from the actual traces before packaging results.
