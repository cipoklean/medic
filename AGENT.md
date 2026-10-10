# AGENT.md — Medic (neatHack 2026) — COLD-START HANDOFF

Single source of truth for any agent (or human) picking this repo up with **zero** context.
**Read this file first. Then continue from NEXT STEPS — not from your assumptions.**
If a section conflicts with what is on disk, **reality wins**: fix this file in the same commit.

Companion: `SPEC.md` holds David's full build prompt (phases, rules, bug table).
The spec is authoritative on *scope*; this file is authoritative on *state*.

---

## 1. WHAT MEDIC IS

A self-healing agent for neatHack. An agent silently goes wrong → Medic reads the failing
agent's **neatlogs** trace, finds the broken step, patches **one file** (`medic.yaml`), re-runs,
and proves the fix with **hard, deterministic checks — including on held-out tasks it never saw**.

**Core principle: the model proposes; deterministic code decides.**
"Green" = hard checks pass. An LLM opinion is never the verdict.

**Event:** neatHack 2026 (hosted by neatlogs).
**Demo video on X:** Mon **Oct 12 2026**, 2:30–7:25 PM WAT (7:00–11:55 PM IST). Backup video: Sunday night.
**Stack:** Python 3.13 (neatlogs needs ≥3.10, **<3.14**), neatlogs SDK, Rich CLI, Typer, OpenAI-compatible LLM.

**Non-negotiables (from the spec):**
- No Streamlit. Ever. UI = polished Rich terminal CLI.
- **Medic edits exactly one file: `medic.yaml`** (system_prompt, tool descriptions, max_steps, retry flag). It never edits Python.
- Deterministic runs: temperature=0, seed=7, fixture-backed tools, no live web.
- Every number shown is **measured** (tokens, steps, cost, pass/fail). No invented percentages.
- Secrets only in `.env` (gitignored). Ship `.env.example`.
- Stream every step to screen — no dead air.

---

## 2. CURRENT STATUS

**Phase 1 COMPLETE and verified by real execution.** Phases 2–5 not started.

| Phase | State |
|---|---|
| 1. Skeleton + env + patient agent + dual tracing | ✅ **verified by running** |
| 2. Bug presets 1–3 + hard checks + tasks | ⬜ not started |
| 3. diagnose / surgeon / verify / loop | ⬜ stubbed (raise NotImplementedError) |
| 4. Bug 4 + Rich polish + report | ⬜ stubbed |
| 5. README + backup demo | ⬜ |

**What works NOW (all by actual run, not by reading code):**
- `python cli.py doctor` → env table, Python 3.13.15, `neatlogs doctor --local` PASS, LLM ping.
- Patient agent loop runs end-to-end on a scripted client: WORKFLOW → LLM → TOOL → … → final answer,
  **8 spans**, written to `runs/<run_id>.json`.
- Dual tracing works; local recorder is independent of neatlogs (verified with neatlogs NOT initialised).
- `calculator` is AST-whitelisted: `__import__('os').system('ls')` → rejected ("Call not allowed"). No eval().
- `medic.yaml` present and is the sole patch target. Clean baseline at `bugs/presets/clean.yaml`.
- Fixture corpus: 5 search fixtures + 6 page fixtures (HTML), all offline.

**Verified in Phase 1 (both doctor modes run for real):**
- `neatlogs doctor --local --json` → `first_failure: null`, 4 spans, envelope valid, exit 0. **PASS.**
- `neatlogs doctor --probe --json` → `first_failure: CREDENTIAL_MISSING`, exit 3, remediation `SET_CREDENTIAL`.
  This is the *expected* failure with no ingest key and is the gate the key unlocks — it POSTs a real trace
  and reads it back. Do not treat it as a defect; re-run it once `NEATLOGS_API_KEY` is set.

**Blockers / needed from David:**
- `NEATLOGS_API_KEY` (ingest) — not yet set. Without it, no trace reaches the dashboard.
- `NEATLOGS_TOKEN` + `NEATLOGS_PROJECT_ID` (a **service-account** read token) — see §3.
- LLM choice: David chose **AWS Bedrock** (hackathon credits). Needs region + credentials.

**NEXT STEPS (start #1 immediately):**
1. **David:** put `NEATLOGS_API_KEY` + `NEATLOGS_TOKEN` + `NEATLOGS_PROJECT_ID` in `~/medic/.env`; put Bedrock creds (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `AWS_REGION`) there too. Then run `.venv/bin/python cli.py doctor` — it must go all-green.
2. **One live clean run:** with the ingest key set, run the patient once and confirm the trace ID appears in the neatlogs dashboard. Then test the READ path (§3) against that real trace ID.
3. **Phase 2:** write `bugs/inject.py` + `bugs/presets/{wrong_args,parse_error,loop}.yaml`, `checks/checks.py` (hard checks 1–3), `tasks/train.yaml` + `tasks/heldout.yaml`. Make `python cli.py run --bug X` show a correct red FAIL for each.
4. Only after 1–3 are green: Phase 3 (diagnose → surgeon → verify → loop), then bug 4 (check first), README.

---

## 3. neatlogs — THE FACTS THAT DECIDE THE ARCHITECTURE

Read these before writing any trace code; they are not guessable.

- **Two DIFFERENT credentials, and the obvious one does not work.**
  - `NEATLOGS_API_KEY` = **SDK ingest** key. It **writes** traces only.
  - The Public API **read** endpoint needs a **service-account Bearer token** (`NEATLOGS_TOKEN`)
    **plus** an `x-project-id` header. An ingest credential **cannot** read. (Confirmed in
    their own auth docs: "Ingest credentials do not authorize Public API reads.")
  - This is why `medic/trace_source.py` MUST fall back to `runs/<id>.json`. That fallback is not
    a nicety — it is the reason the demo survives without a service account.
- **Base URL:** `https://app.neatlogs.com/api/v1/public` (US) or `https://eu.app.neatlogs.com/...` (EU).
  Example read: `GET /api/v1/public/traces?limit=5` with `Authorization: Bearer <token>` + `x-project-id`.
  Response shape: `{"data": {"traces": [...], "page": {...}}, "success": true, "requestId": ...}`.
  (The spec's `GET /api/traces/v3/:traceId` is a **different, dashboard-internal** route — prefer the
  documented public endpoint.)
- **The SDK route is stable and needs no read token:** `neatlogs.init(api_key=..., workflow_name=...)`,
  `neatlogs.flush()`, `neatlogs.shutdown()`; span kinds `WORKFLOW | AGENT | CHAIN | TOOL | RETRIEVER |
  EMBEDDING | GUARDRAIL | MCP_TOOL` (anything else → `ValueError`). Verified installed: **neatlogs 1.4.26**.
- `python -m neatlogs doctor --local --json` → JSON with `first_failure`; PASS means the local envelope is valid.

---

## 4. HOW TO RUN

Repo root: `~/medic`. Interpreter: `~/medic/.venv/bin/python` (Python 3.13.15, provisioned via `uv`).

```bash
cd ~/medic
.venv/bin/python cli.py doctor          # env + neatlogs doctor + LLM ping
.venv/bin/python cli.py run --bug loop  # inject bug, run patient, show hard check (Phase 2)
.venv/bin/python cli.py heal --bug loop # full heal loop (Phase 3)
.venv/bin/python cli.py report          # measured before/after table (Phase 4)
.venv/bin/python cli.py reset           # restore clean medic.yaml
```

Required env vars — **names only; values live in `.env`, never in this file** (see `.env.example`):
`NEATLOGS_API_KEY`, `NEATLOGS_TOKEN`, `NEATLOGS_PROJECT_ID`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`.

---

## 5. ARCHITECTURE MAP

```
medic/
  medic.yaml              # THE ONLY FILE MEDIC PATCHES (prompt, tool descs, max_steps, retry)
  requirements.txt        # neatlogs[openai]==1.4.26, openai, rich, typer, pydantic, pyyaml...
  cli.py                  # Typer + Rich entrypoint: doctor/run/heal/report/reset
  patient/                # the agent being healed
    config.py             # .env loader + llm_settings(); injects nothing at import time
    tracing.py            # DUAL tracer: neatlogs + local runs/<id>.json Recorder
    tools.py              # web_search/fetch_page/calculator, FIXTURE-BACKED, AST-safe calc
    agent.py              # the tool-calling loop; reads ALL knobs from medic.yaml
    scripted.py           # deterministic offline LLM (plumbing proof + reproducible bugs)
  fixtures/               # search/*.json + pages/*.html  (the ONLY "web" the agent can see)
  runs/                   # local JSON traces + reports (gitignored except runs/samples/)
  bugs/inject.py          # applies a bug preset to medic.yaml   (Phase 2)
  checks/checks.py        # HARD pass/fail per bug, zero LLM      (Phase 2)
  tasks/{train,heldout}.yaml                                     (Phase 2)
  medic/
    trace_source.py       # neatlogs read API first -> runs/<id>.json fallback, one Trace model
    diagnose.py           # spans + failed check -> structured Diagnosis (pydantic)
    surgeon.py            # diagnosis -> structured Patch to medic.yaml
    verify.py             # rerun train+heldout, hard checks, measured metrics
    loop.py               # up to 3 attempts: diagnose -> patch -> verify
  scripts/                # one-off verification probes (never ship secrets or keys here)
```

**Key flows:**
- **Tracing** — `patient/tracing.py`. `init_neatlogs(workflow, tags)` is idempotent and NEVER raises
  (a tracing outage must not kill a run). `Recorder.span(kind, name, tool_name=…)` mirrors every span to
  BOTH neatlogs and the local list; `rec.write()` persists `runs/<id>.json`; `rec.metrics()` / `est_cost_usd()`
  return measured numbers.
- **Patient loop** — `patient/agent.py`. Builds an OpenAI-compatible client, `neatlogs.wrap()`s it, loops up to
  `medic.yaml:max_steps`, emits `LLM` + `TOOL` spans, streams each step via `on_step`. `retry_on_parse_error`
  gates whether a malformed tool payload ends the run or asks the model to retry.

---

## 6. DECISIONS LOG (append only)

- **2026-10-09 — Python 3.13.15 in `~/medic/.venv` via `uv`, not the system 3.14.7.** neatlogs declares
  `>=3.10,<3.14`; the VM's default Python is 3.14.7. Why: the cap is hard. Rejected: downgrading the VM.
- **2026-10-09 — Two neatlogs credentials (ingest key + service-account read token), and `trace_source.py`
  must fall back to local JSON.** The SDK ingest key cannot read the Public API; the documented read route is
  the versioned `/api/v1/public` with Bearer + `x-project-id`. Why: the product explicitly separates ingest
  from read, and a demo that dies when a token is missing is not a demo. Rejected: assuming one key does both.
- **2026-10-09 — Bedrock as the LLM, reached via its OpenAI-compatible endpoint** (`base_url =
  https://bedrock-runtime.<region>.amazonaws.com/openai/v1`), not a Bedrock-native SDK. Why: one OpenAI-shaped
  client covers Bedrock/OpenAI/OpenRouter/NaraRouter with only env changes; `neatlogs.wrap()` already
  understands the OpenAI surface. Rejected: a separate boto3 client path (more code, same trace, harder to swap).
- **2026-10-09 — Built `patient/scripted.py`, a deterministic offline LLM, as a first-class component.**
  Why: (a) proves the plumbing with no key/network, (b) makes every bug *reproducible*, which "heal it twice
  in a row" (definition of done) requires. The real LLM is injected wherever this one is. Rejected: relying on
  a live model to demo determinism.

---

## 7. GOTCHAS AND LEARNINGS (append only)

- **`medic.yaml` is currently the clean baseline.** Bug injection must START from clean and layer a preset on
  top (see `bugs/inject.py` in Phase 2) — never "undo by editing the buggy file", which drifts.
- **The `LLM` client is constructed lazily inside the agent, not at import.** Building an `OpenAI()` at import
  time makes every offline test explode with a credentials error before a test can even start.
- **`PatientAgent` must honour an injected client** (`llm=` param). A first draft ignored the injection and
  always built a real client — caught the first time an offline plumbing test ran.
- **Calculator must not use `eval()`.** It uses an AST whitelist (numbers + arithmetic operators only);
  `__import__('os')...` is rejected. This is both a safety property and a demo talking point.
- **Terminal `cd` is unreliable in this session** (a persisted cwd points at a deleted dir; `cd` fails with
  exit 126). Always pass an explicit `workdir=` / `cd /home/ubuntu/medic &&` — never rely on a bare `cd`.
- **`neatlogs` span kinds are a closed set** (8 kinds); passing anything else raises `ValueError`.

---

## 8. ACTIVITY LOG (append only — newest at the bottom)

### 2026-10-09 — Phase 1: skeleton, patient agent, dual tracing (verified)
- Did: provisioned Python 3.13.15 venv via uv; installed neatlogs 1.4.26 + deps; wrote `.env.example`
  (documenting the two-credential neatlogs split + Bedrock), `.gitignore`, `requirements.txt`, `medic.yaml`
  (clean baseline), `patient/{config,tracing,tools,agent,scripted}.py`, `cli.py` (doctor/run/reset wired;
  heal/report stubbed), fixture corpus (5 search JSON + 6 HTML pages), `bugs/presets/clean.yaml`.
- Files: as listed in §5.
- Commands: `uv python install 3.13`; `uv venv --python 3.13 .venv`; `uv pip install …`; `python -m neatlogs
  doctor --local --json` → `first_failure: null`, 4 spans, envelope valid; offline plumbing run → 8 spans
  (WORKFLOW, LLM/TOOL ×4), trace written to `runs/*.json`; `python cli.py doctor` → env table + doctor PASS.
- Result: **works.** One real bug found by running: `PatientAgent` ignored its injected `llm` param and always
  constructed a live `OpenAI()` — fixed to honour injection (offline determinism depends on it). Researched the
  neatlogs docs and recorded the decisive fact: **ingest key ≠ read token.**
- Next: David adds the keys to `.env` and we do one live clean run + read-path test (§3); then Phase 2 presets/checks/tasks.
### 2026-10-09 — CHECKPOINT 1 reported
- Did: ran both neatlogs doctor modes for real; local PASS, probe CREDENTIAL_MISSING (expected, no key yet).
  Updated AGENT.md §2 with both results. No code change.
- Commands: `neatlogs doctor --local --json` (exit 0, first_failure null); `neatlogs doctor --probe --json`
  (exit 3, CREDENTIAL_MISSING / SET_CREDENTIAL).
- Result: checkpoint reached. Waiting on David for NEATLOGS_API_KEY + read token + Bedrock creds.
- Next: keys in .env -> live clean run + read-path test -> Phase 2.
