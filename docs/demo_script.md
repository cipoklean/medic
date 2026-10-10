# Medic — X demo shot list (neatHack 2026)

**Target: 2:45.** Sponsor use is scored — neatlogs, Entire and cfo.ai each appear
by name on screen with something real to show.

Every number below is measured and carries its evidence file. If a number is not
on this list, do not say it.

---

## BUDGET PLAN — read before you record

**The take runs on `nara/laguna-s-2.1`** (free tier, 7M tokens/day). Groq left
the chain on Oct 10 — see "Historical evidence" below. Measured costs:

| Command | Tokens | Evidence |
|---|---|---|
| `cli.py doctor` | ~100 | — |
| clean run (the hook) | ~5,000 | `repro_loop_strong_laguna.json` |
| buggy run, `loop_strong` | **92,000–180,000** | `repro_loop_strong_laguna.json` |
| — 37–38 of those steps are `web_search` | | |
| rerun after the patch | measured in `real_heal_loop_loop_strong.json` | |
| Medic diagnose + surgeon | measured, see the magenta panel | |

**A buggy run is 20–36× the cost of a healthy one** (~5,000 tokens). That ratio
is the demo's second punchline, alongside the token saving.

NaraRouter's free tier is 7M tokens/day, so a take costs ~2% of it. Rehearse
freely.

### Commands that spend Groq tokens

| # | Command | Spend | When |
|---|---|---|---|
| 1 | `cli.py doctor` | ~100 | pre-flight |
| 2 | `cli.py run --bug loop_strong --llm real` | 90k–180k | **take only** |
| 3 | `cli.py heal --bug loop_strong --llm real` | + patch + verify | **take only** |
| 4 | `scripts/smoke_tool_calling.py` | ~50/model | never on a record day |

**Rule: rehearse on `--llm scripted` (free, offline, deterministic). Run the
real take ONCE, at the end.**

```bash
# REHEARSAL — costs nothing, run as often as you like
.venv/bin/python cli.py run  --bug loop --llm scripted
.venv/bin/python cli.py heal --bug loop --llm scripted   # reports "needs a key" — expected
.venv/bin/python cli.py report

# REAL TAKE — one pass
set -a && . ./.env && set +a
export LLM_PROVIDER_CHAIN=nara
.venv/bin/python cli.py doctor
.venv/bin/python cli.py run  --bug loop_strong --llm real
.venv/bin/python cli.py heal --bug loop_strong --llm real
```

### Backup take

```bash
export LLM_PROVIDER_CHAIN=nara
LLM_MODEL_NARA=nemotron-3-ultra-free      # or agnes-2.5-flash
```

Both are verified tool-calling and verified on the full patient loop. Say which
model served the run.

**If NaraRouter is down:** scripted take, clearly labelled. A labelled
deterministic run is honest; an improvised claim is not.

**Do not rehearse on OpenRouter.** Its credit balance is low — a single run can
return `402 insufficient credits`. Cost per take would be ~$0.003, but the
balance is the constraint, not the price.

---

## THE TAKE

### 0:00–0:10 — THE HOOK

```bash
.venv/bin/python cli.py run --bug loop_strong --llm real
```

**"Agents don't crash. They quietly go wrong. This agent asked one question. It
used forty steps — its limit was eight — and burned over ninety thousand tokens
looking for the same price."**

On screen: `[loop] used 40 steps, over the limit of 8` · trace ID.

**Say the provider out loud:** "That's `nara/laguna-s-2.1`."

**If you must disclose the preset:** "I strengthened the prompt so it
misbehaves on this model — it's labelled in the repo as `loop_strong`."

### Historical evidence — only if asked

Twelve steps / 23,136 tokens on `groq/openai/gpt-oss-20b`, **Oct 10**. Groq left
the chain because its free tier allowed four takes a day. Say "Groq, Oct 10" and
move on.

---

### 0:10–0:30 — neatlogs (SPONSOR 1)

Open the dashboard. Show the span tree.

**"That's not a log line — a span tree. Every tool call, every token count, in
order."**

Then the read-back, which is the part judges don't expect:

```bash
curl -s -H "x-api-key: $NEATLOGS_API_KEY" \
  https://app.neatlogs.com/api/traces/v3/<TRACE_ID> | head -c 400
```

**"Medic reads this back through the API — not a screenshot. Every span, with
parent IDs. And if neatlogs is down it falls back to a local file, so a heal
never dies because a vendor is down."**

Sponsor word on camera: **neatlogs.** · evidence: `trace_clean_real_llm.json`

---

### 0:30–1:00 — DIAGNOSIS AND DIFF

```bash
.venv/bin/python cli.py heal --bug loop --llm real
```

**Diagnosis** (name the span): "It read the trace and named the broken step —
`span ba760cf318f943b1`, confidence 0.92 — *'the system_prompt instructs the
agent to keep searching until multiple independent confirmations are found.'*"

**Diff** (one field): "It can only touch four fields in one file. It picked
`system_prompt`. It did not touch Python. It did not touch the tools."

**Medic's own trace** (magenta panel): "Those are Medic's own calls — the
diagnosis and the patch. Measured, not estimated."

**Say the provider:** "Medic's own reasoning also runs on
`groq/openai/gpt-oss-20b`."

---

### 1:00–1:20 — APPROVAL AND THE RERUN

**"The patch is applied to a copy. It only reaches `medic.yaml` after the checks
pass. Watch the train task it was given—"**

Verification table, first row: **"—six steps. Was twelve."**

Then the two rows that matter:

**"And these two tasks it has never seen. It saw exactly one failing task. These
are new questions. It passes both."**

If the heal needs more than one attempt, **keep rolling and say so**: "It's
attempt two — the first patch didn't generalise. That's the held-out set doing
its job."

---

### 1:20–1:45 — CAPABILITY MATRIX (the beat that makes it a product)

| Route | clean | same buggy prompt |
|---|---|---|
| `groq/openai/gpt-oss-20b` — Groq direct, Oct 10 | PASS 4 | **FAIL 12 steps** |
| `openai/gpt-oss-20b` — same weights, OpenRouter routed to Groq | PASS 4 | PASS 7 steps |
| `nara/laguna-s-2.1` | PASS 3–5 | PASS 4 steps |
| `nara/nemotron-3-ultra-free` | PASS 3 | PASS 4 steps |
| `nara/agnes-2.5-flash` | PASS 4 | PASS 5 steps |
| `nara/laguna-s-2.1` — **strengthened preset** | PASS 4–5 | **FAIL 40 steps** |

**"Same prompt. Same question. Same weights — routed to the same upstream — and
two different outcomes. Twelve steps on one route, seven on another. Nobody
catches that by re-reading the prompt. Medic's job is to catch the
model-specific failure in the trace."**

evidence: `loop_capability_matrix.json`

**Optional, if time:** "And when the prompt is strengthened enough, the
well-behaved model breaks too — 40 steps, 38 of them searches."


---

### 1:45–2:15 — Entire (SPONSOR 2)

```bash
entire checkpoint list
entire checkpoint explain 01M4JB59S0C8NN6N28S7F24EYW --short
entire graph search --query "how does the patient agent loop call a tool" --repo . --top-k 3
```

**"Every commit is a checkpoint — the diff plus the session behind it. And Hermes
isn't one of Entire's eight supported agents. So we wrote an integration for it."**

Show `tools/entire-agent-hermes`:

**"It reads real session data out of SQLite, read-only, and reports true token
counts."**

Cut to `entire graph search` returning `PatientAgent.run`.

Sponsor word: **Entire.** · checkpoint: `01M4JB59S0C8NN6N28S7F24EYW`

---

### 2:15–2:35 — cfo.ai (SPONSOR 3)

Open `docs/business.md`.

**"The business model is in cfo.ai, built from these runs — not from
assumptions."**

Point at the table:

* **30,760 tokens** per heal → **$0.113** at our rate table
* **51% fewer tokens** after the patch (15,478 → 7,587) — measured on a task the
  patch never saw
* **6 heals/day** on a free tier — the real constraint

**"Medic doesn't just stop the failure. It makes the agent cheaper."**

Sponsor word: **cfo.ai.**

---

### 2:35–2:45 — CLOSE

**"Point Medic at your agent's config and your own hard checks. The model
proposes. The checks decide. Built on neatlogs, with an Entire integration we had
to write ourselves."**

---

## IF IT GOES WRONG ON CAMERA

| Symptom | Do this |
|---|---|
| NaraRouter 429 | Switch model to `nemotron-3-ultra-free`, **say** which model. Both reproduce with `loop_strong`. |
| NaraRouter down | Scripted take. **Label it scripted.** |
| Heal takes 3 attempts | **Keep going.** That's the product. |
| Bug doesn't reproduce | It reproduced 2/2 with `loop_strong`. If it still doesn't, the matrix is your beat: "four routes, one prompt, different outcomes" is true and still the point. |
| Diff panel wraps badly | Zoom out, or skip to the verification table — the numbers are the payload. |

## DO NOT SAY

* Bugs 1, 2, 4 reproduce on a real model — **they don't.** None was tuned to.
* A real model at temperature 0 is deterministic — measured 3 steps then 4.
* "Medic heals everything" — one heal, one model, one host.
* Any number not in this document.

## Assets

| File | What it proves |
|---|---|
| `evidence/real_heal_loop.json` | the real heal, before/after, held-out included |
| `evidence/loop_capability_matrix.json` | 5 rows, 4 routes, 1 prompt |
| `evidence/repro_loop_strong_laguna.json` | the strengthened preset, 2/2 reproducible |
| `evidence/repro_openrouter_via_groq.json` | same weights, different route, different outcome |
| `evidence/recovery_parse_error.json` | recovery from a failed tool call |
| `evidence/trace_clean_real_llm.json` | a real traced run, readable back |
| `evidence/tool_calling_free_plan.json` | which models actually call tools |
| `docs/business.md` | cost per heal, the 51% saving, runway |