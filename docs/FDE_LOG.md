# FDE log

## 2026-10-07 — Phase 0 discovery

- **Found / decided:** The starter is a Python 3.14.2 scaffold with ten synthetic requests, a FastAPI vendor-risk mock, a Streamlit starter UI, and six public evaluator cases. After installing the declared packages into the ignored project `.venv`, preflight and all ten tests passed; `run_local.py` started the API and UI. Both public evaluator architecture options reach the expected unimplemented `handle_request` stub. Two transient evaluator attempts raised `ModuleNotFoundError: dotenv`; immediate retries passed import and reached the stub, and the cause was not established.
- **Why:** Discovery evidence is required before product and rule design. The fixed review reference date is 2026-09-30, not the host date.
- **What changed:** Added `docs/DISCOVERY.md`; replaced the recommendation/approver discovery marker in `docs/specs/01-product.md`; clarified threshold-vs-Finance-escalation behavior and the fixed-date review boundary; aligned the vendor tool response in `docs/specs/02-architecture.md` with the actual mock fields. No feature code or dependency manifest changed.
- **Additional findings:** SignalWatch is 456 days past review and the registry/service disagree; NimbusAI produces a 503; REQ-1006 contains an instruction-injection attempt. The mock API double-decodes percent-escape sequences. The extracted directory has no prior Git metadata; initialize it for the required phase commit.
- **Git scope:** Per the user's instruction, keep `AGENTS.md`, `STUDENT_CHECKLIST.md`, `.github/copilot-instructions.md`, `docs/specs/`, and the supplied `docs/FDE_Assessment_3.md` in the workspace but out of Git tracking. Keep the useful discovery/log deliverables tracked.
- **Spec persistence:** Discovery corrections to `docs/specs/01-product.md` and `docs/specs/02-architecture.md` are present in the workspace but excluded from Git by that tracking instruction; the rationale is recorded here and in `docs/DISCOVERY.md`.
- **Dependency note:** No manifest dependency was added. The declared packages were installed only into the ignored project `.venv` to run the starter.
- **Phase ship rule:** Not registered in Phase 0. It must be recorded before the first holdout evaluation, as required by `docs/specs/03-eval.md`.
