# Medic — X demo shot list (neatHack 2026)

**Target: 2:45.** Three beats, in this order. Every number carries its evidence
file; if a number is not on this list, do not say it.

---

## THE THREE BEATS

| # | Beat | Evidence |
|---|---|---|
| 1 | **Live** — `parse_error` healed on Bedrock nova-micro, Medic on Sonnet | `real_heal_loop_parse_error.json` |
| 2 | **Recorded** — `loop` healed on Groq gpt-oss-20b, labelled "Groq, Oct 10" | `real_heal_loop.json` |
| 3 | **Why hard checks matter** — a real model caught two wrong expectations a green suite hid; clean gate 39/39 | `gate_nova_micro_clean.json` |

---

## PRE-FLIGHT

```bash
set -a && . ./.env && set +a
export LLM_MODEL_LITELLM_PATIENT=nova-micro     # patient = nova-micro
# medic stays claude-sonnet-4.6 (the role default)

.venv/bin/python cli.py doctor                  # ~100 tokens
.venv/bin/python cli.py report                  # free, offline
```

**One take costs ~$0.009** (measured: 16,938 tokens, patient $0.0012 + medic
$0.0080). Rehearse as often as you like.

**Check before recording** — a stale server makes every live check lie:

```bash
ss -ltnp | grep :8000     # kill anything holding the port
```

---

## THE TAKE

### 0:00–0:10 — THE HOOK

```bash
.venv/bin/python cli.py run --bug parse_error --llm real
```

**"Agents don't crash — they quietly go wrong. Actually, sometimes they do
crash, and that's worse. This agent fetched a page, the tool returned malformed
JSON, and the run simply died. No answer. No error anyone saw."**

On screen: `[parse_error] run ended on an unhandled parse error: JSONDecodeError:
Illegal trailing comma before end of object` · trace ID.

**Say the provider:** "That's `nova-micro` on AWS Bedrock, through our LiteLLM
gateway."

---

### 0:10–0:30 — neatlogs (SPONSOR 1)

Open the dashboard. Show the span tree, and point at the failing span.

**"That's not a log line — a span tree. Every tool call, every token count, in
order. And there it is: `fetch_page`, red."**

Then the read-back:

```bash
curl -s -H "x-api-key: $NEATLOGS_API_KEY" \
  https://app.neatlogs.com/api/traces/v3/<TRACE_ID> | head -c 400
```

**"Medic reads this back through the API — not a screenshot. Every span, with
parent IDs. If neatlogs is down it falls back to a local file, so a heal never
dies because a vendor is down."**

Sponsor word: **neatlogs.** · evidence: `trace_clean_real_llm.json`

---

### 0:30–1:05 — THE HEAL (BEAT 1, LIVE)

```bash
.venv/bin/python cli.py heal --bug parse_error --llm real
```

**Diagnosis** — point at each field as it appears:

**"It named the failing span. `failure_type: parse_error`. Confidence 0.95. And
the evidence — it quoted the error verbatim out of the trace. Nobody told it what
the bug was."**

**Diff** — one line:

```diff
-retry_on_parse_error: false
+retry_on_parse_error: true
```

**"It can only touch four fields in one file. It picked one boolean. It did not
touch Python. It did not touch the tools."**

**Medic's own trace** (magenta panel):

**"Those are Medic's own calls — the diagnosis and the patch. 1,392 tokens in,
204 out. Measured, not estimated."**

**Say the provider:** "Medic reasoned on `claude-sonnet-4.6`, also on Bedrock."

**Rerun + held-out:**

**"The train task it was given — three steps, and it answers. And these two
tasks it has never seen. New questions. It passes both."**

**Cost, on screen:**

| | tokens | cost |
|---|---|---|
| Medic on Sonnet | 1,596 | $0.0080 |
| Patient on nova-micro | 15,342 | $0.0012 |
| **Total** | **16,938** | **$0.0091** |

**"Nine tenths of a cent. And the medic is 87% of that — the reasoning is the
product, not the patient runs."**

---

### 1:05–1:25 — RECORDED HEAL (BEAT 2)

Show `evidence/real_heal_loop.json`. Say the label out loud.

**"A second bug class, healed on a different model. This is `loop` — the agent
kept searching past its step limit. Twelve steps failing, six passing, two
held-out tasks passing."**

**"This ran on Groq's `gpt-oss-20b`, on the tenth of October. Groq left the
chain — its free tier is 200,000 tokens a day and one take costs forty thousand,
so you get four takes and no room to rehearse. The evidence is kept and labelled
by date."**

evidence: `real_heal_loop.json`

---

### 1:25–1:50 — WHY HARD CHECKS MATTER (BEAT 3)

**"Here's what I didn't expect. We gated the whole thing first — clean config,
thirteen tasks, three runs each. Thirty-nine runs. It failed four of them."**

**"And three of those four failures were OUR harness, not the model."**

On screen, the three:

* `parse-error-gadgets` expected **$10.00** for `$169.98 − $79.99`. The answer is
  **$89.99**. The scripted LLM returned `169.98-(79.99*2)` to match it — both
  halves of the test agreed, and both were wrong.
* The search snippets **leaked every answer**, so the agent never fetched the
  page — and a bug living inside `fetch_page` could never fire.
* The citation rule was never stated in the config, then the model was failed
  for not following it.

**"A green suite hid an arithmetic error for as long as it ran. A real model
caught it in nine runs. So every expected answer is now re-derived from its own
fixture — and that test caught a second wrong expectation the first time it
ran."**

**Clean gate, 39/39:**
`evidence/gate_nova_micro_clean.json`

---

### 1:50–2:05 — CAPABILITY MATRIX

| Route | clean | same buggy prompt |
|---|---|---|
| `groq/gpt-oss-20b` — direct, Oct 10 | PASS 4 | **FAIL 12 steps** |
| `gpt-oss-20b` — OpenRouter pinned to Groq | PASS 4 | PASS 7 steps |
| `nara/laguna-s-2.1` | PASS 3–5 | PASS 4 steps |
| `nova-micro` — Bedrock | PASS 3/3 | PASS 3/3 |

**"Same prompt. Same question. Same weights — routed to the same upstream. Twelve
steps on one route, seven on another. The route is part of the system under test.
Nobody catches that by re-reading the prompt."**

evidence: `loop_capability_matrix.json`

---

### 2:05–2:25 — Entire (SPONSOR 2)

```bash
entire checkpoint list
entire checkpoint explain 01M4JB59S0C8NN6N28S7F24EYW --short
entire graph search --query "how does the patient agent loop call a tool" --repo . --top-k 3
```

**"Every commit is a checkpoint — the diff plus the session behind it. Hermes
isn't one of Entire's eight supported agents, so we wrote an integration for it.
It reads real session data out of SQLite, read-only."**

Show `tools/entire-agent-hermes`. Cut to `entire graph search` returning
`PatientAgent.run`.

Sponsor word: **Entire.** · checkpoint: `01M4JB59S0C8NN6N28S7F24EYW`

---

### 2:25–2:40 — cfo.ai (SPONSOR 3)

Open the plan: **https://cfo.ai/s/teLQ2nwFftStndEU**

**"The business model is in cfo.ai, built from these runs — not from
assumptions."**

Point at the numbers:

* **MRR month 12: $1,859** · **ARR run rate Dec 2027: $29,690**
* **95.5% gross margin** — that's cfo.ai's own figure, and it includes Stripe fees
  and hosting
* **$225 total cash required** · **first cash-positive: January 2027**
* **$0.009426 per heal**, measured

**"And the margin — ninety-five and a half percent. That's with payment fees and
hosting already in it. Our own inference-only number is ninety-eight point six;
the difference is Stripe and a server. I'd rather show you the smaller number."**

Sponsor word: **cfo.ai.**

### 2:40–2:45 — CLOSE

**"Point Medic at your agent's config and your own hard checks. The model
proposes. The checks decide. Built on neatlogs, with an Entire integration we had
to write ourselves."**

---

## IF IT GOES WRONG ON CAMERA

| Symptom | Do this |
|---|---|
| Gateway 429 | Wait — the limiter backs off. Don't switch mid-take. |
| 402 insufficient credits | Stop. That's a balance problem, not a demo problem. |
| Heal takes 2 attempts | **Keep going.** Say "attempt two — the first patch didn't generalise." |
| Bug doesn't reproduce | It reproduced 3/3. If it still doesn't, use the gate as the beat: "39 clean runs, 0 misses." |
| Diff panel wraps | Zoom out, or skip to the cost table — the numbers are the payload. |

## DO NOT SAY

* `wrong_args` or `loop` reproduce on Nova — **they don't**, and the reasons are
  in the README.
* A temperature-0 run is deterministic — measured 3 steps then 4.
* "Medic heals everything" — one heal, one bug class, one host.
* Any number not in this document.
* Any estimate. The cost table has none.
* **98.6% as the gross margin.** It is inference-only. The plan's number is
  **95.5%** and that is the one to say out loud.

## Assets

| File | What it proves |
|---|---|
| `evidence/real_heal_loop_parse_error.json` | the live heal, train + held-out + control |
| `evidence/repro_parse_error_nova_micro.json` | 3/3 reproduction, `parse_err_seen=True` |
| `evidence/gate_nova_micro_clean.json` | 39/39 clean passes |
| `evidence/gateway_pricing.json` | the real rate card |
| `evidence/real_heal_loop.json` | loop heal, "Groq, Oct 10" |
| `evidence/loop_capability_matrix.json` | 5 routes, 1 prompt |
| `evidence/gateway_tool_calling_smoke.json` | all 7 gateway models verified |
| `docs/business.md` | cost per heal, the model dial, runway |
