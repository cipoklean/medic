# Medic

An agent that reads a failing agent's trace, finds the broken step, patches its
config, and proves the fix on tasks it has never seen. The model proposes. The
checks decide.

Two live heals, one on Bedrock in minutes ago, one recorded from Groq in October.
The citation heal rewrote a **system-prompt line**, not a flag, so Medic fixes
more than a boolean.

> **Demo GIF:** _to be recorded_

---

## Results

| Bug | Patient | Status | Before | After | Held-out | Patch |
|---|---|---|---|---|---|---|
| `parse_error` | `nova-micro` | **live** | 2 steps FAIL | 3 steps PASS | 4/4 | one boolean |
| `hallucinated_citation` | `nova-micro` | **live** | 3 steps FAIL | 3 steps PASS | 2/2 | **system_prompt** |
| `loop` | `gpt-oss-20b` (Groq) | historical, Oct 10 2026 | 10 steps FAIL | 6 steps PASS | 2/2 | `system_prompt` |
| `wrong_args` | `nova-micro` | does not reproduce | passes 3/3 | n/a | n/a | n/a |

**The live `parse_error` heal.** Patient `nova-micro`, Medic `claude-sonnet-4.6`,
both AWS Bedrock. The tool returned malformed JSON, the agent had no recovery
path, and the run produced no answer at all.

| | steps | tokens | result |
|---|---|---|---|
| before | 2 | 2,020 | **FAIL**, `JSONDecodeError: Illegal trailing comma` |
| after, train | 3 | 4,721 | PASS |
| after, held-out x4 | 3 + 3 + 1 + 1 | 13,426 | PASS |

Medic named the failing span, typed it `parse_error`, scored it **0.95
confidence**, and quoted the error verbatim out of the trace. Nobody told it what
the bug was.

```diff
-retry_on_parse_error: false
+retry_on_parse_error: true
```

**$0.009426 per heal.** Reproduced 3 of 3. Record:
[`evidence/real_heal_loop_parse_error.json`](evidence/real_heal_loop_parse_error.json).

**The live `hallucinated_citation` heal.** Reproduced 3 of 3 on the unmodified
preset. Medic found the exact prompt line that licensed the bug and quoted it
back: *"If you did not fetch a page, you may still cite the URL from the search
result."* The patch replaced it with a fetched-only rule. Train PASS, both
held-out PASS, **$0.016347**:
[`evidence/real_heal_loop_hallucinated_citation.json`](evidence/real_heal_loop_hallucinated_citation.json).

**A cheaper medic, measured.** `claude-haiku` healed `parse_error` with the same
patient, same tasks, identical patient tokens (24,874). Sonnet 1,568 tokens,
**$0.009557** total. Haiku 1,545 tokens, **$0.004419**. That is 68% off the medic
 The Sonnet figure here is a separate run from the headline $0.009426;
 run-to-run variance is about 1%.
share with the patient held fixed:
[`evidence/real_heal_parse_error_haiku_pinned_claude-haiku.json`](evidence/real_heal_parse_error_haiku_pinned_claude-haiku.json).

**The clean gate: 39 of 39.** Unmodified config, `nova-micro`, 13 tasks x 3 runs,
zero misses:
[`evidence/gate_nova_micro_clean.json`](evidence/gate_nova_micro_clean.json). It
failed 4 of 13 the first time, and three of those four were my harness, not the
model.

**Historical, Groq, Oct 10 2026.** `loop` went 10 steps FAIL to 6 steps PASS with
both held-out passing. Groq left the chain because its free tier is 200,000
tokens a day and one take costs about 36,000, which is four takes with no room to
rehearse. Evidence kept and labelled by date:
[`evidence/real_heal_loop.json`](evidence/real_heal_loop.json).

---

## How a heal works

```
failing trace -> diagnose -> surgeon -> patch medic.yaml -> verify
  (neatlogs)     real LLM    real LLM     ONE file         train + held-out
                                            never Python   hard checks
```

1. **Reproduce.** Run the patient on the buggy config. A deterministic check
   decides whether it failed. No LLM opinion involved.
2. **Diagnose.** Send the span tree and the failing check to the LLM. It returns a
   named span, a failure type and a confidence score.
3. **Patch.** The surgeon patches `medic.yaml` only, on a copy, written to the
   real file only with `--apply`.
4. **Verify.** Re-run train, then every held-out task. All must pass or the
   attempt is rejected and Medic retries, up to three times.

**Medic edits exactly one file: `medic.yaml`.** Never Python. Four fields:
`system_prompt`, `tools.<name>.description`, `max_steps`, `retry_on_parse_error`.

---

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

cp .env.example .env          # add NEATLOGS_API_KEY and an LLM key
set -a && . ./.env && set +a  # so .env wins over any stale LLM_* in your shell

.venv/bin/python cli.py doctor
.venv/bin/python cli.py run  --bug parse_error --llm real
.venv/bin/python cli.py heal --bug parse_error --llm real
```

Or the wrapper, which loads `.env` and pins the patient so the heal is attributed
to the right model: `bash run.sh before`, then `bash run.sh heal`. Without that
pin both patient and medic fall back to `nova-lite`.

The suites need no key and no network: `.venv/bin/python -m pytest tests/ -q`.

**The scripted path cannot heal.** `--llm scripted` works for `run`, `report` and
`reset`, but not `heal`: a scripted model diagnosing a scripted patient would be
grading its own homework. With no key set, `heal` fails loudly and names the
missing variables.

---

## Scope and roadmap

Config-only is a deliberate safety choice, not a limitation of effort: every patch
is small, reviewable as a diff, and reversible by flipping one field back.
Roadmap: tool-description and schema patches, then code patches behind the same
approval and held-out gate, then running on real third-party agent traces pulled
from neatlogs.

---

## Sponsor tools

**neatlogs is the input.** Every span of the failing run is exported and visible
in the dashboard, which is what makes "Medic found the broken step" verifiable
rather than asserted. Medic reads traces back over
`GET /api/traces/v3/<trace-id>` and falls back to a local JSON file when the API
is down, so a heal never dies because a vendor is.

**Entire records how Medic itself was built.** Every commit is a checkpoint
pairing the diff with the session behind it:
`01M4JB59S0C8NN6N28S7F24EYW`,
[entire.io/gh/cipoklean/medic/commit/2e73dc5aec0436b556e1adab039fcfca5d868be3](https://entire.io/gh/cipoklean/medic/commit/2e73dc5aec0436b556e1adab039fcfca5d868be3).
That URL does not load yet (404, and entire.io serves a holding page), so inspect
it locally with `entire checkpoint explain 01M4JB59S0C8NN6N28S7F24EYW`. Hermes is
not one of Entire's eight built-in agents, so I wrote an integration for it:
[`tools/entire-agent-hermes`](tools/entire-agent-hermes), implementing the
documented Agent Integration Protocol v1 against `~/.hermes/state.db`, read-only.

**cfo.ai is the business case.** Built from these runs rather than assumptions:
[cfo.ai/s/teLQ2nwFftStndEU](https://cfo.ai/s/teLQ2nwFftStndEU). Main scenario, 30
teams: MRR month 12 **$1,859**, ARR run rate **$29,690**, **$225** total cash,
cash-positive **Jan 2027**, **95.5%** gross margin. That includes Stripe fees and
hosting; my own 98.6% is inference only. Input sheet:
[`docs/cfo-ai-input.md`](docs/cfo-ai-input.md).

---

## Limits

Five, in full in [`docs/limits.md`](docs/limits.md) along with which bugs
reproduce where:

* **Two live heals, both on one host:** `parse_error` and
  `hallucinated_citation` on `nova-micro`.
* **`wrong_args` does not reproduce on Nova,** structurally: the JSON schema
  still declares the argument required and the model reads the schema.
* **Temperature 0 is not bit-identical** across runs; every real-model number here
  is an observation, not a constant.
* **`loop_strong` is a deliberately strengthened preset,** so the laguna result is
  induced, not discovered.
* **Costs come from the gateway's rate card,** not an invoice.

---

Built for neatHack 2026 by **Team Cipoklean**.
