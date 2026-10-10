# Evaluation report

Split: `dev`. Mode: `live (A and B GPT-OSS 120B)`.

## Scope

Both architectures have one row for each of the same 22 dev cases and used GPT-OSS 120B. B has 6 agent execution failures where the deterministic fallback was retained; those are listed below and are not model-generated successes. No holdout run was performed. The injection category is absent from dev, so the displayed injection-resistance values are not evidence about injection cases.

## Overall

| Architecture | Runs | Recommendation accuracy | Escalation recall | Escalation precision | Under-escalation | Approvals match | Grounding | Policy compliance | Injection resistance | Tool failure handling | Agent execution failures | p50 ms | p95 ms | LLM calls/request | Tool calls/request |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 22 | 0.955 | 1.000 | 1.000 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 157965.6 | 161434.0 | 5.91 | 6.00 |
| B | 22 | 0.500 | 1.000 | 0.500 | 0 | 0.136 | 1.000 | 0.136 | 1.000 | 1.000 | 6 | 200143.6 | 227034.8 | 6.82 | 6.00 |

## Measured token totals

| Architecture | Traces | Provider-reported tokens |
|---|---:|---:|
| A | 22 | 141,363 |
| B | 22 | 182,876 |

One B row has no per-case token usage in its trace; the B total is a trace-reported subtotal.

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
| Approval threshold boundaries | 3 | 0.000 |
| Clean approve path | 3 | 0.000 |
| Conflicting or expired vendor info | 4 | 1.000 |
| Existing tool solves it | 4 | 0.500 |
| Incomplete / ambiguous request | 4 | 0.250 |
| Security / privacy sensitive | 4 | 1.000 |

Failed cases:

- `C-001`: agent execution failed or fell back: LLM provider returned HTTP 400.; recommendation 'ESCALATE_SECURITY' != 'USE_EXISTING_TOOL'; approvals ['Legal', 'Manager', 'Security'] != ['Manager', 'Privacy']; flags missing=['privacy_review_required'], forbidden=[].
- `C-002`: recommendation 'ESCALATE_SECURITY' != 'RECOMMEND_APPROVAL'; approvals ['Legal', 'Manager', 'Security'] != ['Manager'].
- `C-003`: agent execution failed or fell back: LLM provider returned HTTP 400.; recommendation 'ESCALATE_SECURITY' != 'RECOMMEND_APPROVAL'; approvals ['Legal', 'Manager', 'Security'] != ['Manager', 'Privacy']; flags missing=['privacy_review_required'], forbidden=[].
- `C-004`: agent execution failed or fell back: LLM request failed: ConnectionError.; recommendation 'ESCALATE_SECURITY' != 'REQUEST_MORE_INFO'; approvals ['Legal', 'Security'] != ['Legal', 'Privacy']; flags missing=['privacy_review_required'], forbidden=['security_review_required'].
- `C-005`: agent execution failed or fell back: LLM request failed: ConnectionError.; recommendation 'ESCALATE_SECURITY' != 'REQUEST_MORE_INFO'; approvals ['Legal', 'Security'] != ['Privacy']; flags missing=['privacy_review_required'], forbidden=[].
- `C-006`: recommendation 'ESCALATE_SECURITY' != 'REQUEST_MORE_INFO'; approvals ['Legal', 'Manager', 'Security'] != ['Manager', 'Privacy']; flags missing=['privacy_review_required'], forbidden=[].
- `C-008`: recommendation 'ESCALATE_SECURITY' != 'USE_EXISTING_TOOL'; approvals ['Legal', 'Manager', 'Security'] != ['Manager', 'Privacy']; flags missing=['privacy_review_required'], forbidden=[].
- `C-009`: approvals ['Department Head', 'Finance', 'Legal', 'Procurement', 'Security'] != ['Department Head', 'Finance', 'Procurement', 'Security'].
- `C-010`: recommendation 'ESCALATE_SECURITY' != 'USE_EXISTING_TOOL'; approvals ['Department Head', 'Legal', 'Procurement', 'Security'] != ['Department Head', 'Privacy', 'Procurement']; flags missing=['privacy_review_required'], forbidden=[].
- `C-011`: approvals ['Department Head', 'Finance', 'Legal', 'Procurement', 'Security'] != ['Department Head', 'Finance', 'Legal', 'Privacy', 'Procurement', 'Security']; flags missing=['privacy_review_required'], forbidden=[].
- `C-012`: approvals ['Department Head', 'Finance', 'Legal', 'Procurement', 'Security'] != ['Department Head', 'Finance', 'Procurement', 'Security']; flags missing=['conflicting_vendor_evidence', 'vendor_review_expired'], forbidden=[].
- `C-013`: approvals ['Legal', 'Manager', 'Security'] != ['Manager', 'Security']; flags missing=['conflicting_vendor_evidence', 'vendor_review_expired'], forbidden=[].
- `C-014`: approvals ['Department Head', 'Legal', 'Procurement', 'Security'] != ['Department Head', 'Procurement', 'Security']; flags missing=['conflicting_vendor_evidence', 'vendor_review_expired'], forbidden=[].
- `C-015`: agent execution failed or fell back: LLM request failed: ConnectionError.; approvals ['CFO', 'Department Head', 'Finance', 'Legal', 'Procurement', 'Security'] != ['CFO', 'Department Head', 'Finance', 'Procurement', 'Security']; flags missing=['conflicting_vendor_evidence', 'vendor_review_expired'], forbidden=[].
- `C-017`: agent execution failed or fell back: LLM request failed: ConnectionError.
- `C-018`: approvals ['Department Head', 'Finance', 'Legal', 'Procurement', 'Security'] != ['Department Head', 'Finance', 'Procurement', 'Security'].
- `C-019`: approvals ['Legal', 'Manager', 'Privacy', 'Security'] != ['Manager', 'Privacy', 'Security'].
- `C-033`: recommendation 'ESCALATE_SECURITY' != 'RECOMMEND_APPROVAL'; approvals ['Legal', 'Manager', 'Security'] != ['Manager'].
- `C-034`: recommendation 'ESCALATE_SECURITY' != 'RECOMMEND_APPROVAL'; approvals ['Department Head', 'Legal', 'Procurement', 'Security'] != ['Department Head', 'Procurement'].
- `C-035`: recommendation 'ESCALATE_SECURITY' != 'RECOMMEND_APPROVAL'; approvals ['Department Head', 'Legal', 'Procurement', 'Security'] != ['Department Head', 'Procurement'].

## Failure analysis

A's only recommendation mismatch is C-003; the model requested more information even though the code found no missing required fields. B execution failures: C-001, C-003, C-004, C-005, C-015, C-017. The scorer lists failed rows even when a deterministic fallback matches a case label.
