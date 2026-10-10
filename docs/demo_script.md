# Demo shot list — Medic (neatHack 2026)

2 minutes, 4 beats. Every number below is measured and lives in `evidence/`.
Nothing here needs a claim I can't point at.

## Before you record

```bash
cd ~/medic
set -a && . ./.env && set +a        # .env must win over any stale LLM_* in the shell
.venv/bin/python cli.py doctor      # all green
```

**Check your provider budget first.** Groq is 200,000 tokens/day and one
runaway patient run costs ~23,000. OpenRouter is a paid slug. Run
`cli.py doctor` and look at the chain line before you hit record.

**Have the scripted backup ready** (labelled as scripted if you use it):

```bash
.venv/bin/python cli.py run --bug loop --llm scripted
```

---

## Beat 1 — "Agents don't crash. They quietly go wrong." (0:00–0:20)

Show the failing run:

```bash
.venv/bin/python cli.py run --bug loop --llm real
```

**Say:** "Same agent, same question. It goes looking for sources and never
stops — 12 steps against a limit of 8."

**On screen:** red panel, `[loop] used 12 steps, over the limit of 8`, plus
`12 steps · 23,136 tokens · $0.086`.

**Then** the neatlogs trace link. Say the model by name: this is
`groq/openai/gpt-oss-20b`.

---

## Beat 2 — The same prompt, four models (0:20–0:35)

The capability matrix on screen. **This is the beat that makes it a product and
not a toy.**

| Model | clean | same buggy prompt |
|---|---|---|
| `groq/openai/gpt-oss-20b` | PASS 4 steps | **FAIL 12 steps** |
| `openrouter/openai/gpt-oss-20b` | PASS 3 steps | **FAIL 1 step, empty response** |
| `nara/laguna-s-2.1` | PASS 3 steps | PASS 4 steps |
| `nara/nemotron-3-ultra-free` | PASS 3 steps | PASS 4 steps |

**Say:** "Identical prompt, identical task. It breaks on two hosts and not on
two other models. Nobody catches that by re-reading the prompt — it looks
fine, and it *is* fine, on the models where it's fine. Medic's job is to catch
the model-specific failure in the trace."

Evidence: `evidence/loop_capability_matrix.json`.

---

## Beat 3 — The heal (0:35–1:30)

```bash
.venv/bin/python cli.py heal --bug loop --llm real
```

**On screen, in order:** header → red failing run with its cost → diagnosis
panel → coloured diff → verification table → green **HEALED**.

**Point at while it runs:**

* **Diagnosis** — the model named span `ba760cf318f943b1`, confidence 0.92:
  *"The system_prompt instructs the agent to keep searching until multiple
  independent confirmations are found, causing it to exceed the step limit."*
* **Diff** — one field. `system_prompt`. Nothing else. Medic never touched
  Python.
* **Verification** — the table that matters:

  | split | task | result | steps |
  |---|---|---|---|
  | train | loop-widgets | PASS | 6 |
  | held-out | loop-solar | PASS | 5 |
  | held-out | loop-gadgets | PASS | 3 |

**Say:** "Two of those tasks were never shown to the model during diagnosis. It
only ever saw the failing one."

---

## Beat 4 — Close (1:30–2:00)

Two numbers, both measured:

**51% fewer tokens.** 15,478 before → 7,587 after, on the same task. Medic
doesn't just stop the failure, it makes the agent cheaper.

**The recovery case.** `retry_on_parse_error: false → true`. One boolean. The
cheapest possible fix is often the smallest one:

```bash
.venv/bin/python scripts/probe_recovery.py
```

**Say:** "Point Medic at your agent's `medic.yaml` and your own hard checks.
The model proposes. The checks decide. Built on neatlogs, with an Entire
integration for Hermes."

---

## If something goes wrong on camera

| Symptom | Say this, do this |
|---|---|
| Groq 429 (daily) | Switch `LLM_PROVIDER_CHAIN=openrouter` and **say** the fault changes to an empty response. Same bug, different symptom — still a real demonstration. |
| Provider key rejected | Fall back to the scripted run. Say plainly: "this is the deterministic agent, same code path, no model." |
| Heal needs 2+ attempts | **Keep rolling.** Attempts 2–3 are the product working. Held-out catching a fix that only worked on the train task is the demo. |
| Nothing reproduces | Use Beat 2 as-is — "three of four models don't break on this prompt" is a true and interesting result, not a failure. |

## Do not claim

* That bugs 1, 2 and 4 reproduce on a real model. They don't — none was tuned
  to. They're demonstrated with the scripted agent.
* That a real model at temperature 0 is deterministic. Measured: same config,
  3 steps then 4.
* That Medic heals everything. One real heal, on one model, one host.
* Any number you can't find in `evidence/`.

## Assets

| File | What it proves |
|---|---|
| `evidence/real_heal_loop.json` | the real heal, before/after, held-out included |
| `evidence/loop_capability_matrix.json` | 4 models, 2 hosts, 1 prompt |
| `evidence/recovery_parse_error.json` | recovery from a failed tool call |
| `evidence/trace_clean_real_llm.json` | a real traced run, readable back |
| `evidence/tool_calling_free_plan.json` | which models actually call tools |
| `docs/business.md` | cost per heal, the 51% saving, runway |

## Sponsor moments (say the names out loud)

* **neatlogs** — "every span you just saw is in the trace. Medic reads that
  trace back through `/api/traces/v3` and falls back to a local file if the
  API is down."
* **Entire** — "every commit is a checkpoint. And Hermes isn't one of Entire's
  eight supported agents, so we wrote an integration for it" — cut to
  `tools/entire-agent-hermes` if there's time, otherwise just say it.
* **cfo.ai** — "the business model is in `docs/business.md`, built from these
  measured numbers."