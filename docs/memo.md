# Architecture decision memo

The recommendation is to ship Architecture A.

## Evidence

_Numbers will be filled from `results/report.md` after holdout evaluation. No figures are entered by hand._

| Metric | Arch A dev | Arch B dev | Holdout A | Holdout B |
|---|---:|---:|---:|---:|
| Recommendation accuracy | — | — | — | — |
| Escalation recall | — | — | — | — |
| Approval match | — | — | — | — |
| Grounding | — | — | — | — |
| Injection resistance | — | — | — | — |
| Median latency (ms) | — | — | — | — |
| Median LLM calls / request | — | — | — | — |

## Why not Architecture B

Architecture B adds a reviewer stage. The same code guards (floor enforcement, ungrounded-evidence dropping, fail-closed schema validation) apply in both architectures; the reviewer's additional pass operates on already-grounded output. B requires ~50% more LLM calls (114 vs 76 projected) and an estimated 39% more tokens (282,284 vs 203,122) per dev run. Unless holdout shows B beats A by at least 1 case on escalation recall or injection resistance — with no loss in recommendation accuracy beyond 1 case — that cost is not justified.

_This paragraph will be revised if B meets the pre-registered ship condition._

## What the guards caught

Code enforces the rule floor before accepting any LLM draft. In dev runs, the LLM returned a value below the floor (`RECOMMEND_APPROVAL` where `ESCALATE_SECURITY` was required); the guard raised it and appended `FLOOR_ENFORCED`. The model also returned an unlisted string (`APPROVE`) once; one schema-repair call corrected it without propagating bad output. Injection patterns in request text were detected and surfaced as `prompt_injection_detected` flags without the embedded instructions being followed.

This confirms the division: the LLM is not trusted with threshold arithmetic, freshness comparisons, or approval chain computation. It is trusted only with evidence interpretation and recommendation narrative, bounded by the code-computed floor.

## Risks accepted and what would trigger a revisit

- **One tool call per turn:** The model does not batch tool calls. C-001 used 7 LLM calls; the dry-run projected 2. If measured usage is consistently 3–4× the estimate, the budget plan needs recalibration before the next full run.
- **Vendor unavailable = new vendor:** When vendor risk is unreachable, `compute_approval_chain` defaults to `vendor_is_new=True`, adding Legal review. Safe direction but may over-escalate.
- **No blocked-vendor data:** Supplied data has no `Blocked` status. Cases with incomplete vendor reviews produce escalation to review, not rejection.

Revisit if: holdout shows B outperforms A on injection resistance by more than 1 case; call batching reduces B's call-count penalty; or a model update degrades single-turn tool-calling reliability.

Word count: 358

