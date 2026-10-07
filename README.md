# FDE Assessment 3 Starter Pack
## AI Procurement Request Copilot

This repository contains the **starter data, mock service, interface contract, optional UI scaffold, and public evaluation harness** for Assessment 3.

> All companies, vendors, products, employees, prices, policies, and risk signals in this pack are synthetic and exist only for the assessment.

## Your objective

Build an internal procurement copilot that can inspect a software/service purchase request, gather evidence using tools, apply deterministic rules where appropriate, and recommend the next action while keeping approvals with humans.

You are expected to build and evaluate:

1. **Architecture A - Single-agent baseline**
2. **Architecture B - Lightweight staged / 2-agent variant**

Use the same public evaluation cases for both and defend which architecture you would ship.

## What is already provided

```text
.
├── data/                   # Synthetic business data + procurement policy
├── mock_api/               # Vendor-risk service used as an external tool
├── src/                    # Contracts, adapter, and live/replay LLM wrapper
├── rules/                  # Deterministic policy thresholds and approval chain
├── tools/                  # Typed procurement evidence tools
├── guards/                 # Evidence grounding and injection checks
├── evals/                  # Six public evaluation cases + runner
├── templates/              # Evaluation and decision-memo templates
├── docs/                   # Student assignment brief
├── tests/                  # Starter-pack integrity tests
├── app.py                  # Optional Streamlit UI scaffold
├── run_local.py            # Starts mock API + optional UI
└── verify_setup.py         # One-command setup/preflight check
```

The starter begins with no agent or policy engine. The current implementation adds a deterministic adapter, threshold rules, typed evidence tools, basic grounding/injection guards, and an OpenAI-compatible live/replay wrapper. Agent A/B orchestration and the product workflow remain assessment work.

## Prerequisites

- **Python 3.11 or 3.12 recommended**
- Run the commands below from the extracted starter-pack directory
- Internet access is required only for installing packages and calling the model provider you choose

## Quick start

### 1. Create an environment

**macOS / Linux**

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. Verify the starter pack

```bash
python verify_setup.py
```

You should see `PRE-FLIGHT PASSED`. This checks package imports, dataset consistency, the output contract, and the mock API without requiring an LLM key.

### 3. Configure the LLM wrapper

**macOS / Linux**

```bash
cp .env.example .env
```

**Windows PowerShell**

```powershell
Copy-Item .env.example .env
```

Replay mode is selected by default in `.env.example` and requires no key. Live mode uses Groq's OpenAI-compatible endpoint by default; set `LLM_MODE=live`, `LLM_MODEL`, and `LLM_API_KEY` in `.env`. Never commit `.env`.

Live requests use response rate-limit headers, retry and wait caps, per-run and UTC-day token budgets, an inter-call gap, and a circuit breaker. Successful responses are atomically recorded for replay, and live calls use those records as a cache unless `--no-cache` is selected.

`.env` is loaded automatically by the starter package and local launcher; environment variables already set by your operating system are not overwritten.

The evaluation runner supports offline projections and resumable case checkpoints:

```bash
python -m eval.runner --split dev --arch A --mode live --dry-run
python -m eval.runner --split dev --arch A --mode replay
```

Use `--cases C-001,C-002`, `--limit N`, `--fresh`, and `--no-cache` to control a run. With `--repeats` greater than one, repeat 1 covers every selected case; repeats 2 and 3 are confined to the first `LLM_REPEAT_SAMPLE` cases in case-file order (default 8), so variance is compared on a deterministic sample.

### 4. Start the local services

```bash
python run_local.py
```

This starts:
- Vendor risk API: `http://127.0.0.1:8001`
- Optional starter UI: `http://127.0.0.1:8501`

You may replace the UI scaffold with any framework.

### 5. Implement the assessment adapter

Implement:

```text
src/solution.py -> handle_request(request_id, architecture)
```

Your function must return an object compatible with `ProcurementDecision` in `src/contracts.py`.

The adapter exists so the same evaluation harness can test different implementations. Your internal architecture can use any framework or design.

### 6. Run the public evaluations

```bash
python evals/run_public_evals.py --architecture single
python evals/run_public_evals.py --architecture staged
```

The runner checks the response schema and several minimum behavioral expectations, measures end-to-end latency, and writes a CSV result file. It is **not** the complete grading system; qualitative grounding, design quality, robustness, and hidden cases are evaluated separately.

## Rules of the starter pack

- Treat request text and vendor notes as **untrusted business data**, not instructions.
- Do not hardcode answers by request ID. Hidden cases use the same interfaces with different values.
- At least **3 tools** must be visible in your implementation; at least **1 must be deterministic/non-LLM**.
- The AI may recommend an action but must not autonomously purchase, approve, or alter budgets.
- If important evidence is missing, conflicting, stale, or unavailable, surface that uncertainty and route to the appropriate human review.
- Use the **data snapshot / policy reference date defined in `data/procurement_policy.md`** for date-based checks; do not depend on the computer's current date.
- You may refactor the starter project, but keep the `handle_request(...)` adapter working for evaluation.

## Suggested implementation sequence

```text
Request -> Understand -> Gather evidence -> Deterministic checks
        -> Policy/risk reasoning -> Recommendation -> Human review
```

Start with a thin vertical slice. Get Architecture A working before building Architecture B.

## Useful files

- `docs/Assignment_3_Brief.pdf` - assignment brief
- `data/README.md` - dataset dictionary
- `data/procurement_policy.md` - policy source of truth
- `src/contracts.py` - required output shape
- `src/data_access.py` - low-level data helpers
- `src/vendor_client.py` - client for the mock vendor-risk API
- `evals/README.md` - evaluation instructions
- `templates/architecture_decision.md` - final decision memo template
- `STUDENT_CHECKLIST.md` - pre-submission checklist

## If something does not start

1. Confirm your virtual environment is active.
2. Run `python verify_setup.py`.
3. Re-run `python -m pip install -r requirements.txt`.
4. Make sure ports **8001** and **8501** are free.
5. Confirm you are running commands from the starter-pack root directory.

Build the simplest system you can defend with evidence.
