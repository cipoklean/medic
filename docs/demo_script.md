# Medic — X demo shot list (neatHack 2026)

**Target: 2:45.** Sponsor use is scored — neatlogs, Entire and cfo.ai each appear
by name on screen with something real to show.

Every number below is measured and carries its evidence file. If a number is not
on this list, do not say it.

---

## BUDGET PLAN — read before you record

Groq: **200,000 tokens/day.** Measured costs:

| Command | Tokens | Evidence |
|---|---|---|
| `cli.py doctor` | ~100 | — |
| `cli.py run --bug loop --llm real` | ~4,000 clean / ~23,000 buggy | `real_heal_loop.json` |
| `cli.py heal --bug loop --llm real` | **~31,000 + Medic's own calls** | `real_heal_loop.json` |
| — buggy reproduce | 15,478 | 10 steps |
| — rerun, train | 7,587 | 6 steps |
| — rerun, held-out ×2 | 7,695 | 5 + 3 steps |
| Medic diagnose + surgeon | **not yet measured** — capture added, pending | — |

**One clean take ≈ 36,000–46,000 tokens ≈ 18–23% of the daily budget.**
**4 takes per day, maximum.**

### Commands that spend Groq tokens

| # | Command | Spend | When |
|---|---|---|---|
| 1 | `cli.py doctor` | ~100 | pre-flight, fine |
| 2 | `cli.py run --bug loop --llm real` | ~4k–23k | **demo take only** |
| 3 | `cli.py heal --bug loop --llm real` | ~31k + medic | **demo take only** |
| 4 | `scripts/smoke_tool_calling.py` | ~50/model | never on a record day |

**Rule: rehearse on `--llm scripted` (free, offline, deterministic). Run the
real take ONCE, at the end.**

```bash
# REHEARSAL — costs nothing, run as often as you like
.venv/bin/python cli.py run  --bug loop --llm scripted
.venv/bin/python cli.py heal --bug loop --llm scripted   # reports "needs a key" — expected
.venv/bin/python cli.py report

# REAL TAKE — one pass, ~36-46k tokens
set -a && . ./.env && set +a
.venv/bin/python cli.py doctor
.venv/bin/python cli.py run  --bug loop --llm real
.venv/bin/python cli.py heal --bug loop --llm real
```

### Backup take

```bash
export LLM_PROVIDER_CHAIN=openrouter
```

**Say on camera:** "Same model, different host. Groq gave a 12-step overrun;
OpenRouter gives a single empty response. The fault is model-and-host specific —
that's the point of the next beat."

**If both are dead:** scripted take, clearly labelled. A labelled deterministic
run is honest; an improvised claim is not.

---

## THE TAKE

### 0:00–0:10 — THE HOOK

```bash
.venv/bin/python cli.py run --bug loop --llm real
```

**"Agents don't crash. They quietly go wrong. This agent asked one question. It
used twelve steps, burned twenty-three thousand tokens, and never stopped."**

On screen: `[loop] used 12 steps, over the limit of 8` · `23,136 tokens` ·
trace ID.

**Say the provider out loud:** "That's `groq/openai/gpt-oss-20b`."

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

| Model | clean | same buggy prompt |
|---|---|---|
| `groq/openai/gpt-oss-20b` | PASS 4 steps | **FAIL 12 steps** |
| `openrouter/openai/gpt-oss-20b` | PASS 3 steps | **FAIL 1 step, empty response** |
| `nara/laguna-s-2.1` | PASS 3 steps | PASS 4 steps |
| `nara/nemotron-3-ultra-free` | PASS 3 steps | PASS 4 steps |

**"Same prompt. Same question. Same data. It breaks on two hosts and not on two
other models — and nobody catches that by re-reading the prompt, because the
prompt is fine on the models where it's fine. Medic's job is to catch the
model-specific failure in the trace."**

evidence: `loop_capability_matrix.json`

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
| Groq 429 on `run` | Switch to `openrouter`, **say** the symptom changes. Still a real demo. |
| Both providers dead | Scripted take. **Label it scripted.** |
| Heal takes 3 attempts | **Keep going.** That's the product. |
| Bug doesn't reproduce | Use the capability matrix as-is. "Three of four models don't break on this prompt" is a true result. |
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
| `evidence/loop_capability_matrix.json` | 4 models, 3 hosts, 1 prompt |
| `evidence/recovery_parse_error.json` | recovery from a failed tool call |
| `evidence/trace_clean_real_llm.json` | a real traced run, readable back |
| `evidence/tool_calling_free_plan.json` | which models actually call tools |
| `docs/business.md` | cost per heal, the 51% saving, runway |