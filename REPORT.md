# 1. Architecture

The system is a single-process Python application with five boundaries: an OpenAI-backed planner, a Playwright `Surface` adapter, a typed capability recorder, a deterministic replay engine, and shared safety, escalation, and observability services.

Discovery follows `goal -> observe -> plan one action -> execute -> record step`. Replay loads only the saved artifact and invocation inputs. It never calls a model.

I chose Python because it matches my day-to-day work on FastAPI services and agent tooling. Playwright provides reliable browser automation and tracing. Pydantic validates the capability contract. LangGraph models the discovery loop as an explicit graph rather than an unbounded while loop, which keeps step limits and termination conditions visible.

The target is a local legacy-style member servicing console: nested tables, no test IDs, fictional balances, and injectable runtime states (not found, permission denied, blocking dialog). This mirrors the back-office banking tools I worked on at Hexaware, without touching real financial systems.

The most important boundary is that the LLM does not author production selectors. Observations expose short-lived semantic element ids. The model chooses the correct control. The surface adapter converts that choice into ordered locator candidates (role/name, label, visible text). The artifact stores reviewable targeting logic, not model-generated CSS.

# 2. Artifact schema

The artifact is a versioned capability contract, not a macro or transcript. It includes:

- capability identity and version
- target app metadata (vendor, entry URL)
- parameterized goal template
- typed inputs and outputs
- ordered steps with locator candidates and rationale
- success checkpoint text
- allowlist patterns
- discovery provenance (planner, model, run id, llm call count)

Invocation values are parameterized at record time. If discovery types member `12345` for input `member_id`, the saved step stores `{{member_id}}`. Passwords always become `{{operator_password}}`; literals are never persisted.

Validation goes beyond JSON shape: unique step ids, declared templates must reference declared inputs, every output needs an extract step, and checkpoints cannot be empty.

Locator candidates are ordered fallbacks. The web adapter prefers accessible role/name, form labels, then visible text. Positional selectors are intentionally avoided.

# 3. Determinism & error handling

Replay is deterministic in the required sense: given artifact plus inputs, it executes saved steps with `llm_calls = 0`. Navigation and actions are checked against `policy.json` on every run.

Results use three classes:

- `success`: checkpoint verified, outputs extracted
- `business_outcome`: legitimate domain answers such as `MEMBER_NOT_FOUND`
- `failure`: automation errors with step id, expected state, observed context, and a failure screenshot

Transient locator timeouts retry within a bounded budget. Blocking dialogs route through handoff rather than blind dismissal. Member `42424` triggers a session notice dialog; replay detects it and either auto-acknowledges in headless CI mode or pauses for a human in interactive mode.

UI drift is secondary in this environment. Runtime errors are primary. I handle drift through semantic locator fallbacks and explicit failure evidence rather than speculative self-healing.

# 4. Heterogeneity & multi-tenant

The artifact stores abstract actions and target descriptions, not Playwright calls. The `Surface` protocol (`observe`, `build_targets`, `click`, `type`, `extract`, screenshot, handoff) is the seam for legacy web, accessibility-tree desktop automation, or future vision-backed surfaces.

For multi-tenant reuse I would keep one canonical artifact per vendor product version, then apply small reviewed tenant overlays for route prefixes, label aliases, and known dialogs. Compatibility fingerprints built from vendor/version signals and replay success rates would mark pairings that need re-review instead of silently mutating production automation.

I did not build tenant storage, desktop adapters, or worker fleets. The schema leaves room for overlays without a format change.

# 5. Escalation & handoff

When replay detects a blocking dialog or hits an unrecoverable condition, it writes an intervention request (capability, step, reason, URL, screenshot) and changes control ownership.

Automation and the human share the same Playwright page. Pausing means the automation loop stops acting while the session stays open. Resuming means automation continues from the post-human state. Interactive mode uses a terminal prompt as a stand-in operator console. Headless CI uses auto-acknowledge for the demo dialog only.

Manual events are recorded without password values. Pre- and post-handoff screenshots are stored in the run evidence directory.

# 6. Safety

Safety is enforced in code via `policy.json`:

- localhost host allowlist, checked on entry and navigation
- allowed action vocabulary
- risky control patterns flagged conservatively
- blocked patterns stopped outright
- redaction of long numeric ids, dollar amounts, emails, and API-key-shaped strings in persisted logs

Artifacts store templates, not concrete discovery identifiers. Environment secrets stay in `.env`, which is gitignored. `scripts/preflight_submission.py` scans for accidental secret commits before submission.

# 7. Cuts

I deliberately did not build distributed workers, a tenant database, production authentication, real core banking integration, a visual locator engine, or a full co-browsing operator product. Those are represented as seams and documented next steps.

The demo operator console is terminal-based. Business outcome detection uses a small explicit pattern set suitable for the demo. Gemini-style rate-limit handling is omitted because this project standardizes on OpenAI per my available tooling.

With more time I would add: (1) artifact approval lifecycle and replay reliability scoring, (2) tenant override files and compatibility fingerprints, (3) frame and accessibility locator candidate types, and (4) repeated replay stability reporting. I would keep any LLM-assisted replay recovery bounded, policy-checked, and opt-in so production replay stays deterministic by default.

## Final submission step (live discovery)

The assignment requires at least one genuine OpenAI discovery run. Before emailing the repo, run:

```bash
export OPENAI_API_KEY=...
python scripts/run_submission_flow.py
```

That replaces discovery evidence under `evidence/submission/` with a live model run while keeping deterministic replays at `llm_calls: 0`.
