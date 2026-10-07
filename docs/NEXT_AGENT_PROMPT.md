Read these files in this exact order: `AGENTS.md`, `docs/HANDOVER.md`, `docs/FDE_LOG.md`, `docs/DISCOVERY.md`, then every file in `docs/specs/`.

Before editing anything, run `git status --short`, `git log -10 --oneline`, `./.venv/bin/python -m unittest discover -s tests -v`, and `./.venv/bin/python verify_setup.py`. Compare status, commit history, test count/pass status, and preflight result with `docs/HANDOVER.md`. Allow the current task commit described at the top of the documented history; if anything else differs, report the exact difference and stop.

Current phase: Phase 3 remains open. Architecture A and the product exist; only C-001 has been run, and its live and replay calls now complete. The next task is to inspect C-001's stored trace and explain its mismatch against the expected recommendation, approvals, and risk flags. Do not make another live request until the user approves the three-case stage.

Use only Groq with `openai/gpt-oss-120b`; do not switch models. Respect 30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD, 7,000 estimated tokens/request, 200 calls/run, 200,000 tokens/run, and the persisted UTC counter. Resume is enabled by default; use `--fresh` only when deliberately rerunning a failed checkpoint. No holdout call or label change without explicit user approval. Stop after each stage and wait.

Do not paste or ask for the API key. `.env` is already configured locally. Keep appending verified findings to `docs/FDE_LOG.md`, preserve its ignored status, and commit per phase with the required co-author trailer.
