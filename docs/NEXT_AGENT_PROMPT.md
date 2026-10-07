Read these files in this exact order: `AGENTS.md`, `docs/HANDOVER.md`, `docs/FDE_LOG.md`, `docs/DISCOVERY.md`, then every file in `docs/specs/`.

Before editing anything, run `git status --short`, `git log -10 --oneline`, `./.venv/bin/python -m unittest discover -s tests -v`, and `./.venv/bin/python verify_setup.py`. Compare status, commit history, test count/pass status, and preflight result with `docs/HANDOVER.md`. Allow only the documented handover commit at the top of the history; if anything else differs, report the exact difference and stop.

Current phase: Phase 3 remains open. Architecture A and the product exist, but dev evaluation, trace review, and tuning did not complete. Phase 4 has not started. The next concrete task is to fix two verified code defects without network access: `src/llm.py` sends a redacted literal instead of the configured Authorization value, and `eval/runner.py` marks failed case rows completed so resume skips them. Add regression tests, retain key redaction, run tests and preflight, update `docs/FDE_LOG.md`, and commit.

Do not make another live request until those fixes pass and the user explicitly approves retrying C-001. Use only Groq with `openai/gpt-oss-120b`; do not switch models. Respect 30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD, 7,000 estimated tokens/request, 200 calls/run, 200,000 tokens/run, and the persisted UTC counter. Resume is enabled by default; use `--fresh` only when deliberately rerunning a failed checkpoint. No holdout call or label change without explicit user approval. Stop after each stage and wait.

Do not paste or ask for the API key. `.env` is already configured locally. Keep appending verified findings to `docs/FDE_LOG.md`, preserve its ignored status, and commit per phase with the required co-author trailer.
