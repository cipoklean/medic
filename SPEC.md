# Medic — build spec (David's build prompt, condensed to reference)

> Full state of the build lives in `AGENT.md`. This file is the *scope* reference.

## Pitch
"Agents don't crash — they quietly go wrong. Medic reads a failing agent's neatlogs trace,
finds the broken step, patches the agent's config, re-runs it, and proves the fix with hard
checks — including on tasks it never saw."

Event: neatHack 2026 (neatlogs). Demo video on X: Mon Oct 12 2026, 2:30–7:25 PM WAT.
Backup demo video: Sunday night.

## Non-negotiable rules
1. Python 3.11+ (neatlogs needs ≥3.10, <3.14).
2. **No Streamlit.** UI = polished Rich terminal CLI (live panels, colored diffs, spinners, streamed
   steps). Optional later: one FastAPI page streaming over SSE to plain HTML.
3. **Medic only edits `medic.yaml`** (system prompt, tool descriptions, max_steps, retry flag).
   Never edits Python code.
4. **"Green" = hard, non-LLM checks pass.** An LLM opinion is never the verdict.
5. **Deterministic runs**: temperature=0, fixed seed where supported, tools run against
   cached/mocked fixtures, not the live web.
6. **Every number shown is measured** and reported per bug (tokens, steps, cost, pass/fail).
7. Secrets only in `.env` (gitignored). Ship `.env.example`.
8. Stream every step to the screen — no dead air while the LLM thinks.

## Stack
neatlogs Python SDK · OpenAI-compatible LLM via `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL` ·
rich · pyyaml · pydantic · jsonschema · typer · httpx.

## The four bugs and their hard checks

| # | Bug preset | Hard check (no LLM) |
|---|---|---|
| 1 | Wrong arguments — vague `calculator` description → model passes prose | every tool call validates against its JSON schema AND final answer equals the known value |
| 2 | Malformed JSON — a fixture tool returns slightly broken JSON, `retry_on_parse_error: false` | run completes with no unhandled parse exception and answer is correct |
| 3 | Infinite loop — prompt lacks a stop rule, `max_steps` high | finishes in ≤ N steps with a final answer |
| 4 | Hallucinated citations — prompt invites "cite sources" without requiring fetched evidence | every URL cited appears in a `fetch_page` result from that run |

Build order 1→2→3→4. **Bug 4's check is built first** and dropped if time runs short.

## Phase plan
- **Phase 1** (Fri night): skeleton, `.env`, neatlogs doctor, patient agent, dual tracing, one clean
  run visible in both neatlogs and `runs/`. Test the trace read API. → CHECKPOINT 1
- **Phase 2** (Sat): bug presets 1–3 + checks + tasks (1 train + 2–3 held-out each).
  → CHECKPOINT 2
- **Phase 3** (Sat night–Sun): diagnose, surgeon, verify, loop. → CHECKPOINT 3
- **Phase 4** (Sun): bug 4 (check first), Rich polish, `report`. → CHECKPOINT 4
- **Phase 5** (Sun night): README (problem, demo, quickstart, mermaid architecture, honest
  limitations), backup demo. → CHECKPOINT 5
- Optional: FastAPI SSE page.

## Definition of done
`heal` fixes bugs 1–3 (4 if built) and passes held-out tasks deterministically, twice in a row ·
before/after traces visible in neatlogs tagged by bug and attempt · `report` prints measured
numbers per bug · a stranger can run `python cli.py heal --bug loop` in under 5 minutes ·
no secrets committed.

## Demo script (2 min)
1. "Agents don't crash, they quietly go wrong." Failing run + red check + neatlogs trace.
2. `heal --bug loop`: diagnosis names the bad span, diff appears, rerun green, held-out pass,
   real numbers.
3. Fast second bug (wrong args).
4. "Point Medic at your agent's medic.yaml and your own checks. Built on neatlogs."