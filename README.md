# Computer-Use Automation System

A focused implementation of the interface.ai take-home assignment: an LLM discovers a legacy back-office workflow once, records it as a typed capability artifact, and deterministic replay executes that capability in production with zero model calls.

The target is a local, fictional credit-union member servicing console. It uses table-heavy markup, no test IDs, and deterministic runtime states (not found, permission denied, blocking dialog).

## Quick start for reviewers

1. Read [REPORT.md](REPORT.md) for design decisions and trade-offs.
2. Inspect [capabilities/lookup_member_balance.json](capabilities/lookup_member_balance.json).
3. Open [evidence/submission/MANIFEST.md](evidence/submission/MANIFEST.md).
4. Run `pytest -q`.

## Architecture

```text
Natural-language goal
        |
        v
+---------------------+
| DiscoveryAgent      |  LangGraph observe -> plan -> act loop
| (OpenAI planner)    |
+----------+----------+
           |
           v
+---------------------+       +-------------------+
| PlaywrightSurface   |<----->| Legacy demo UI    |
+----------+----------+       +-------------------+
           |
           v
+---------------------+
| Capability artifact |  typed inputs/outputs, locator candidates
+----------+----------+
           |
           v
+---------------------+
| ReplayEngine        |  llm_calls = 0
+---------------------+
```

The LLM selects semantic element ids (`e1`, `e2`). The surface adapter converts those into ordered locator candidates. The artifact stores the contract, not the raw transcript.

## Requirements

- Python 3.10+
- Playwright Chromium
- OpenAI API key for the genuine discovery run

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
```

Set your key in `.env`:

```text
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
```

Never commit `.env`.

## Run the demo app

Terminal 1:

```bash
source .venv/bin/activate
python -m demo_app.app
```

The app listens on http://127.0.0.1:8765. Operator password is `demo`.

## Demo path

### Offline smoke test (not submission evidence)

```bash
python scripts/run_offline_demo.py
```

Uses a mock planner so the architecture can be exercised without an API key.

### Genuine end-to-end flow

Terminal 2:

```bash
source .venv/bin/activate
export OPENAI_API_KEY=...
python scripts/run_submission_flow.py
```

Or run manually:

Discovery:

```bash
python -m computer_use discover \
  --planner openai \
  --goal "Sign in, look up member {{member_id}}, and read the savings balance" \
  --param member_id=12345 \
  --name lookup_member_balance \
  --output capabilities/lookup_member_balance.json \
  --headless
```

Successful replay:

```bash
python -m computer_use replay capabilities/lookup_member_balance.json \
  --input member_id=54321 \
  --input operator_password=demo \
  --headless
```

Business outcome:

```bash
python -m computer_use replay capabilities/lookup_member_balance.json \
  --input member_id=99999 \
  --input operator_password=demo \
  --headless
```

Human handoff (blocking dialog on member 42424):

```bash
python -m computer_use replay capabilities/lookup_member_balance.json \
  --input member_id=42424 \
  --input operator_password=demo \
  --human-mode interactive
```

Headless runs auto-acknowledge the dialog for CI friendliness. Interactive mode pauses for operator input on the same browser session.

## Agent-facing API (stretch)

```bash
uvicorn computer_use.api.server:app --host 127.0.0.1 --port 8766
```

- `GET /capabilities` lists saved artifacts
- `POST /capabilities/{name}/invoke` replays with typed inputs

## Evidence

After running discovery and replay scenarios:

```bash
python scripts/collect_submission_evidence.py
python scripts/preflight_submission.py
```

Curated evidence lives in `evidence/submission/`. Raw runs stay in `evidence/runs/` (gitignored).

## Tests

```bash
pytest -q
```

## Project layout

```text
computer_use/     discovery, replay, surfaces, safety, escalation, API
demo_app/         legacy-style target UI
capabilities/     saved capability artifacts
evidence/         run logs, screenshots, traces
scripts/          demo and submission helpers
tests/            contract, replay, policy tests
REPORT.md         required design write-up
```

## Result contract

Replay returns one of:

- `success` with declared outputs
- `business_outcome` with a stable code (for example `MEMBER_NOT_FOUND`)
- `failure` with step id, expected vs observed, and failure screenshot

## Safety

`policy.json` enforces localhost allowlists, action vocabulary limits, risky-control classification, and log redaction for secrets and sensitive values. Passwords are parameterized in artifacts, never persisted as literals.
