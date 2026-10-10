# Medic

I built Medic because agents rarely crash. They quietly start failing, and
nobody notices until a customer does.

Medic reads a failing agent's trace, finds the broken step, patches one config
file, runs the agent again, and proves the fix with hard checks, including on
tasks it has never seen. The model proposes. The checks decide.

Built for neatHack 2026 by **cipoklean**.

> **Demo GIF:** _to be recorded_

---

## Results at a glance

| Bug | Patient | Status | Before | After | Held-out |
|---|---|---|---|---|---|
| `parse_error` | `nova-micro` (Bedrock) | **live** | 2 steps, FAIL | 3 steps, PASS | 4/4 |
| `hallucinated_citation` | `nova-micro` (Bedrock) | **live** | 3 steps, FAIL | 3 steps, PASS | 2/2 |
| `loop` | `gpt-oss-20b` (Groq) | historical, Oct 10 2026 | 10 steps, FAIL | 6 steps, PASS | 2/2 |
| `wrong_args` | `nova-micro` | does not reproduce | passes 3/3 | n/a | n/a |

Both live heals ran with Medic on `claude-sonnet-4.6`, Bedrock. A third heal on
`claude-haiku` is recorded separately and is cheaper.

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

Or use the wrapper, which loads `.env` and pins the patient to `nova-micro` so the
heal is attributed to the right model: `bash run.sh before` then `bash run.sh heal`.
Without `LLM_MODEL_LITELLM_PATIENT` set the patient falls back to `nova-lite` and
Medic runs on `nova-lite` too. The heal still works, but the costs below are
measured with the patient pinned.

The suites need no key and no network:

```bash
.venv/bin/python -m pytest tests/ -q
```

No Streamlit. No web server. The agent's tools never touch the network.

**The scripted path cannot heal.** `--llm scripted` works for `run`, `report` and
`reset`, but not `heal`: a scripted model diagnosing a scripted patient would be
grading its own homework. With no key set, `heal` fails loudly and names the
missing variables.

---

## How a heal works

```
failing trace -> diagnose -> surgeon -> patch medic.yaml -> verify
  (neatlogs)     real LLM    real LLM     ONE file         train + held-out
                                            never Python   hard checks
```

1. **Reproduce.** Run the patient on the buggy config. A deterministic check
   decides whether it failed. No LLM opinion involved.
2. **Diagnose.** Send the span tree and the failing check to the LLM. It returns
   a structured diagnosis with a named span and a confidence score.
3. **Patch.** The surgeon patches `medic.yaml` only, on a copy, written to the
   real file only with `--apply`.
4. **Verify.** Re-run train, then every held-out task. All must pass or the
   attempt is rejected and Medic retries, up to three times.

**Medic edits exactly one file: `medic.yaml`.** Never Python. Four fields:
`system_prompt` (restore a stop rule, require fetched evidence),
`tools.<name>.description` (state the argument format with an example),
`max_steps` (cap a runaway loop), `retry_on_parse_error` (survive a malformed
tool result).

---

## Results

Every number below came from a real run and was read back from that run's own
recorder. None is estimated.

### The live heal: `parse_error` on Bedrock

Patient `nova-micro`, Medic `claude-sonnet-4.6`, both Bedrock.

| | steps | tokens | result |
|---|---|---|---|
| before | 2 | 2,020 | **FAIL**, `JSONDecodeError: Illegal trailing comma` |
| after, train | 3 | 4,721 | PASS |
| after, held-out x4 | 3 + 3 + 1 + 1 | 13,426 | PASS |

It reproduced 3 out of 3. Medic named the failing span, typed it `parse_error`,
scored it **0.95 confidence**, and quoted the error verbatim out of the trace.
Nobody told it what the bug was. The patch was one boolean:

```diff
-retry_on_parse_error: false
+retry_on_parse_error: true
```

**Cost per heal, measured: `$0.009426`** (Medic $0.007511, patient $0.001915).
Record: [`evidence/real_heal_loop_parse_error.json`](evidence/real_heal_loop_parse_error.json).

### Two more measured results

**`hallucinated_citation`, also live.** Reproduced 3 out of 3 on the unmodified
preset. Medic found the exact prompt line that licensed the bug and quoted it
back: *"If you did not fetch a page, you may still cite the URL from the search
result."* The patch replaced that with a rule that only fetched URLs may be cited.
Train PASS, both held-out PASS, **$0.016347**:
[`evidence/real_heal_loop_hallucinated_citation.json`](evidence/real_heal_loop_hallucinated_citation.json).

**The same heal on a cheaper medic.** `claude-haiku` healed `parse_error` too:
same 0.95 confidence, same one-field patch, all four held-out passing,
**$0.005619** against Sonnet's $0.009426. The medic model is a measured cost dial,
not a rate-card guess:
[`evidence/real_heal_parse_error_haiku.json`](evidence/real_heal_parse_error_haiku.json).

### The clean gate: 39 of 39

Unmodified `medic.yaml`, `nova-micro`, 13 tasks x 3 runs, zero misses:
[`evidence/gate_nova_micro_clean.json`](evidence/gate_nova_micro_clean.json).

This is what every claim above rests on. It failed 4 of 13 the first time, and
**three of those four were my harness, not the model.**

### Recorded, not live: `loop` on Groq, historical (Oct 10 2026)

| | steps | tokens | result |
|---|---|---|---|
| before | 10 | 15,478 | **FAIL**, over the limit of 8 |
| after, train | 6 | 7,587 | PASS |
| after, held-out x2 | 5 + 3 | 7,695 | PASS |

Diagnosed at 0.92 confidence, patched with an explicit stop rule.

**Historical result from 2026-10-10, not a live claim.** Groq left the chain
because its free tier is 200,000 tokens a day and one take costs about 36,000,
which is four takes with no room to rehearse. Evidence kept and labelled by date:
[`evidence/real_heal_loop.json`](evidence/real_heal_loop.json).

---

### Model-specific failures

`wrong_args` does **not** reproduce on Nova, and the reason is structural: the
preset only weakens the tool description, but the JSON schema still declares
`expression` as required, and nova-micro reads the schema and complies. 0 of 3
across all three tasks: [`scripts/probe_wrong_args.py`](scripts/probe_wrong_args.py).

`hallucinated_citation` fails 3/3 on `nova-micro` and passes on `nova-lite`. Same
prompt, same fixtures, different model, different outcome.

## Two bugs a real model caught in my own harness

**A green suite hid an arithmetic error for as long as it ran.**
`parse-error-gadgets` expected $10.00 for `$169.98 - $79.99`. The answer is
$89.99. The scripted LLM returned `169.98-(79.99*2)` to match it, so both halves
of the test agreed and both were wrong. A real model computed 89.99 and the check
failed it. Every `expected_answer` is now re-derived from its fixture by
[`tests/test_expectations.py`](tests/test_expectations.py), which caught a second
wrong expectation on its first run.

**The search snippets leaked every answer.** That made `fetch_page` optional, so a
bug inside `fetch_page` could never fire: `parse_error` first showed 0 of 9 with
no parse error in any trace. Snippets now carry no figures, enforced by a test.

---

## Sponsor tools

### neatlogs

Every span of the failing run is exported and visible in the dashboard, which is
what makes "Medic found the broken step" verifiable rather than asserted.

Instrumented with `neatlogs.init()` and `neatlogs.wrap(client)`, span kinds
`WORKFLOW`, `LLM`, `TOOL`. Medic reads traces back over
`GET /api/traces/v3/<trace-id>` and falls back to a local JSON file when the API
is down, so a heal never dies because a vendor is. `cli.py doctor` wires in
`neatlogs doctor --local` and `--probe`.

### Entire

Every commit is a checkpoint pairing the diff with the session behind it.

* Checkpoint: `01M4JB59S0C8NN6N28S7F24EYW`, covering 14 commits up to `dccff63`
* Checkpoint URL: https://entire.io/gh/cipoklean/medic/commit/dccff63f1ae86461fe87a50e60eb7b37191e2f06

**That URL does not load yet** (404, and entire.io serves a holding page). The web
viewer is not live for anyone. The checkpoint is real and inspectable locally with
`entire checkpoint explain 01M4JB59S0C8NN6N28S7F24EYW` or `entire checkpoint list`.

Hermes is not one of Entire's eight built-in agents, so I wrote an integration for
it: [`tools/entire-agent-hermes`](tools/entire-agent-hermes). It implements the
documented Agent Integration Protocol v1 and reads session data from
`~/.hermes/state.db`, read-only.

### cfo.ai

Business plan: **https://cfo.ai/s/teLQ2nwFftStndEU**

Main scenario, 30 teams: **MRR month 12 $1,859**, **ARR run rate $29,690**,
**$225 total cash**, **cash-positive Jan 2027**, **95.5% gross margin**.

95.5% is the number to quote: cfo.ai's own figure, including Stripe fees and
hosting. My 98.6% is inference only. Input sheet:
[`docs/cfo-ai-input.md`](docs/cfo-ai-input.md).

---

## Honest limits

* **Two live heals, both on one host.** `parse_error` and
  `hallucinated_citation`, both on `nova-micro`. That is the whole live claim.
* **A real model at temperature 0 is not bit-identical.** Two runs of the same
  clean config on `nara/laguna-s-2.1` took 3 and 4 steps. Earlier-provider result;
  the script was removed in cleanup, the number stands in
  [`evidence/loop_capability_matrix.json`](evidence/loop_capability_matrix.json).
* **`loop_strong` is a deliberately strengthened preset**, built so `laguna-s-2.1`
  reproduced. The original `loop.yaml` does not reproduce there. Earlier-provider
  result, backed by
  [`evidence/repro_loop_strong_laguna.json`](evidence/repro_loop_strong_laguna.json).
* **The medic cost dial is now measured, not priced.** Sonnet and Haiku have both
  healed `parse_error`. Sonnet $0.009426, Haiku $0.005619. A frontier model has
  not been tried.
* **The original held-out pair does not test `parse_error`.** Both state their
  figures in the question, so they never fetch a page and never meet the bug. The
  two page-only tasks exist because of that gap.
* **Cost figures come from the gateway's own rate card**, not an invoice.
* The offline suites prove the machinery. Only a real run proves a heal.

---

Built by **Team Cipoklean**.
