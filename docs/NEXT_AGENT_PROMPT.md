Read these files in this exact order: `AGENTS.md`, `docs/HANDOVER.md`, `docs/FDE_LOG.md`, `docs/DISCOVERY.md`, then every file in `docs/specs/`.

Before editing anything, run `git status --short`, `git log -10 --oneline`, `./.venv/bin/python -m unittest discover -s tests -v`, and `./.venv/bin/python verify_setup.py`. Compare status, commit history, test count/pass status, and preflight result with `docs/HANDOVER.md`. Allow the current task commit described at the top of the documented history; if anything else differs, report the exact difference and stop.

Current phase: Phase 3 remains open. Architecture A and the product exist; C-001's live and replay checks now complete and match the expected recommendation, approvals, and flags under the deterministic exact-match guard. The next step is to ask for approval before the three-case live stage (C-002 through C-004). Do not run it without approval.

Use only Groq with `openai/gpt-oss-120b`; do not switch models. Respect 30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD, 7,000 estimated tokens/request, 200 calls/run, 200,000 tokens/run, and the persisted UTC counter. Resume is enabled by default; use `--fresh` only when deliberately rerunning a failed checkpoint. No holdout call or label change without explicit user approval. Stop after each stage and wait.

Do not paste or ask for the API key. `.env` is already configured locally. Keep appending verified findings to `docs/FDE_LOG.md`, preserve its ignored status, and commit per phase with the required co-author trailer.
