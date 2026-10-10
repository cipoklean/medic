# Medic

I built Medic because agents rarely crash. They quietly start failing, and
nobody notices until a customer does.

Medic reads a failing agent's trace, finds the broken step, patches one config
file, runs the agent again, and proves the fix with hard checks, including on
tasks it has never seen. The model proposes. The checks decide.

Built for neatHack 2026 by **cipoklean**.

---

## 60-second quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

cp .env.example .env          # add NEATLOGS_API_KEY and an LLM key
set -a && . ./.env && set +a  # so .env wins over any stale LLM_* in your shell

.venv/bin/python cli.py doctor
.venv/bin/python cli.py run  --bug parse_error --llm real
.venv/bin/python cli.py heal --bug parse_error --llm real
```

Or use the wrapper, which loads `.env` and pins the patient to `nova-micro` so
the heal is attributed to the right model:

```bash
bash run.sh before    # the failing run
bash run.sh heal      # diagnose, diff, verify, verdict
```

Without `LLM_MODEL_LITELLM_PATIENT` set, the patient falls back to the role
default (`nova-lite`) and Medic also runs on `nova-lite` rather than Sonnet. The
heal still works, but the costs below are measured with the patient pinned.

You will see a red failing run, a diagnosis naming the broken span, a one-line
diff, a green re-run, a held-out results table, and the cost of the repair.

No Streamlit. No web server. The agent's tools never touch the network.

**The scripted path cannot heal.** `--llm scripted` works for `run`, `report` and
`reset`, but not for `heal`. Medic's diagnose and surgeon steps always use the
real LLM, because a scripted model diagnosing a scripted patient would be
grading its own homework. With no key set, `heal` fails loudly and names the
missing variables.

---

## How a heal works

```
failing trace -> diagnose -> surgeon -> patch medic.yaml -> verify
  (neatlogs)     real LLM    real LLM     ONE file         train + held-out
                                            never Python   hard checks, no LLM
```

1. **Reproduce.** Run the patient on the buggy config. A deterministic check
   decides whether it actually failed. No LLM opinion involved.
2. **Diagnose.** Send the span tree and the failing check to the LLM. It returns
   a structured diagnosis with a named span and a confidence score.
3. **Patch.** The surgeon writes a patch to `medic.yaml` only. The patch goes to
   a copy and reaches the real file only with `--apply`.
4. **Verify.** Re-run the train task, then every held-out task. All of them must
   pass, or the attempt is rejected and Medic tries again, up to three times.

**Medic edits exactly one file: `medic.yaml`.** Never Python.

| Field | Typical fix |
|---|---|
| `system_prompt` | restore a stop rule, require fetched evidence |
| `tools.<name>.description` | state the argument format with an example |
| `max_steps` | cap a runaway loop |
| `retry_on_parse_error` | let the agent survive a malformed tool result |

---

## Results

Every number below came from a real run and was read back from that run's own
recorder. None is estimated.

### The live heal: `parse_error` on Bedrock

Patient `nova-micro`, Medic `claude-sonnet-4.6`, both on AWS Bedrock.

| | steps | tokens | result |
|---|---|---|---|
| before | 2 | 2,020 | **FAIL**, `JSONDecodeError: Illegal trailing comma` |
| after, train | 3 | 4,721 | PASS |
| after, held-out x2 (page-only) | 3 + 3 | 9,532 | PASS |
| after, held-out x2 (original) | 1 + 1 | 3,894 | PASS |
| clean control | 3 | 4,707 | PASS |

It reproduced 3 out of 3 on the train task. Medic named the failing span, typed
it `parse_error`, scored it **0.95 confidence**, and quoted the error verbatim
out of the trace. Nobody told it what the bug was. The patch was one boolean:

```diff
-retry_on_parse_error: false
+retry_on_parse_error: true
```

**Cost per heal, measured:** `$0.009426`. Medic on Sonnet is $0.007511 of that,
the patient runs on nova-micro are $0.001915.

Full record: [`evidence/real_heal_loop_parse_error.json`](evidence/real_heal_loop_parse_error.json).

### The clean gate: 39 of 39

Unmodified `medic.yaml`, `nova-micro`, all 13 tasks x 3 runs. Zero misses:
[`evidence/gate_nova_micro_clean.json`](evidence/gate_nova_micro_clean.json).

This is what every claim above rests on. It failed 4 of 13 the first time, and
**three of those four were my harness, not the model.**

### Recorded, not live: `loop` on Groq, historical (Oct 10 2026)

| | steps | tokens | result |
|---|---|---|---|
| before | 10 | 15,478 | **FAIL**, over the limit of 8 |
| after, train | 6 | 7,587 | PASS |
| after, held-out x2 | 5 + 3 | 7,695 | PASS |

Diagnosed at 0.92 confidence and patched with an explicit stop rule:
[`evidence/real_heal_loop.json`](evidence/real_heal_loop.json).

**This is a historical result from 2026-10-10, not a live claim.** Groq left the
provider chain because its free tier is 200,000 tokens a day and one take costs
about 36,000, which is four takes and no room to rehearse. The evidence is kept
and labelled by date so the run stays reproducible:
[`evidence/real_heal_loop.json`](evidence/real_heal_loop.json).

---

## Which bugs reproduce where

| Bug | `groq/gpt-oss-20b` | `nova-micro` (Bedrock) | `laguna-s-2.1` |
|---|---|---|---|
| `parse_error` | not tested | **FAIL 3/3, healed live** | not tested |
| `loop` | **FAIL, 12 steps** | PASS | PASS, needs `loop_strong` |
| `wrong_args` | FAIL | **PASS 3/3** | PASS |
| `hallucinated_citation` | not tested | PASS | PASS |

**`wrong_args` does not reproduce on Nova, and the reason is structural.** The
preset only weakens the tool description, but the JSON schema still declares
`expression` as required, and nova-micro reads the schema and complies. I probed
it across all three wrong_args tasks and got 0 of 3:
[`scripts/probe_wrong_args.py`](scripts/probe_wrong_args.py).

---

## Two things a real model caught that my tests missed

**A green suite hid an arithmetic error for as long as it ran.**
`parse-error-gadgets` expected $10.00 for `$169.98 - $79.99`. The answer is
$89.99. The scripted LLM returned `169.98-(79.99*2)` to match the wrong number,
so both halves of the test agreed with each other and both were wrong. A real
model computed 89.99 and the check failed it.

Every `expected_answer` is now re-derived from its fixture by
[`tests/test_expectations.py`](tests/test_expectations.py), which caught a second
wrong expectation on its first run.

**The search snippets leaked every answer.** That made `fetch_page` optional, so
a bug living inside `fetch_page` could never fire. `parse_error` first showed 0
of 9 with no parse error in any trace. Snippets now carry no figures, and a test
enforces it.

---

## Sponsor tools

### neatlogs

Every span of the failing run is exported and visible in the dashboard, which is
what makes "Medic found the broken step" verifiable rather than asserted.

Instrumented with `neatlogs.init()` and `neatlogs.wrap(client)`, span kinds
`WORKFLOW`, `LLM`, `TOOL`. Medic reads traces back over
`GET /api/traces/v3/<trace-id>` and falls back to a local JSON file when the API
is unavailable, so a heal never dies because a vendor is down. `cli.py doctor`
wires in `neatlogs doctor --local` and `--probe`.

### Entire

Every commit is a checkpoint pairing the diff with the session behind it.

* Checkpoint: `01M4JB59S0C8NN6N28S7F24EYW`, covering 14 commits up to `dccff63`
* Checkpoint URL: https://entire.io/gh/cipoklean/medic/commit/dccff63f1ae86461fe87a50e60eb7b37191e2f06

**That URL does not load yet.** Checked anonymously on 2026-10-10: it returns
404, and entire.io itself serves a holding page reading "A new developer platform
is coming". The old checkpoint URL returns 500. So the web viewer is not live for
anyone, logged in or not. The checkpoint is real and inspectable locally:

```bash
entire checkpoint explain 01M4JB59S0C8NN6N28S7F24EYW
entire checkpoint list
```

Hermes is not one of Entire's eight built-in agents, so I wrote an integration
for it: [`tools/entire-agent-hermes`](tools/entire-agent-hermes). It implements
the documented Agent Integration Protocol v1 and reads real session data from
`~/.hermes/state.db`, opened read-only.

### cfo.ai

Business plan: **https://cfo.ai/s/teLQ2nwFftStndEU**

Main scenario, 30 teams:

| | |
|---|---|
| MRR, month 12 (Sep 2027) | $1,859 |
| ARR run rate, Dec 2027 | $29,690 |
| Total cash required | $225 |
| First cash-positive month | Jan 2027 |
| Gross margin at month 12 | **95.5%** |

95.5% is the number to quote. It is cfo.ai's own figure and it includes Stripe
fees and hosting. My own 98.6% is inference only, what the margin would be if
tokens were the only cost. The gap between them is fees and a server.

Input sheet: [`docs/cfo-ai-input.md`](docs/cfo-ai-input.md).

---

## Honest limits

* **One heal, one bug class, one host.** Medic healed `parse_error` on
  `nova-micro`. That is the whole live claim.
* **A real model at temperature 0 is not bit-identical.** Two runs of the same
  clean config on `nara/laguna-s-2.1` took 3 and 4 steps. Every real-model figure
  here is an observation from a small number of runs. That probe ran on an earlier
  provider, and the script has since been removed; the number stands as recorded
  in [`evidence/loop_capability_matrix.json`](evidence/loop_capability_matrix.json).
* **`loop_strong` is a deliberately strengthened preset**, built so
  `nara/laguna-s-2.1` reproduced the loop bug. The original `loop.yaml` does not
  reproduce on that model. This is an **earlier-provider result**: the probe
  script was removed in the cleanup pass, and
  [`evidence/repro_loop_strong_laguna.json`](evidence/repro_loop_strong_laguna.json)
  is what backs it. Both presets stay in the repo so the difference is
  inspectable.
* **The medic cost dial is priced, not proven.** Only Sonnet has ever served a
  Medic call. `claude-haiku` and `nova-micro` are rate-card arithmetic, not
  results, and nobody has checked whether a smaller model diagnoses as
  accurately.
* **The original held-out pair does not test this bug.** Both state their figures
  in the question, so they never fetch a page and never meet the bug. The two
  page-only tasks exist because of that gap.
* **Cost figures come from the gateway's own rate card**, not an invoice.
* The offline suites prove the machinery. Only a real run proves a heal.

---

Built by **Team Cipoklean**.
