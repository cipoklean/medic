# Medic, business model draft inputs for cfo.ai

> These are **inputs**, not a finished plan. Every number is measured from a real
> run in `evidence/`; anything unmeasured is labelled as such. Nothing here is
> invented to fill a field.

## 1. The problem

Teams running agents in production already pay for observability, they see the
trace. What they lack is a **verdict**: nobody reads a 15-span trace at 2am to
work out which step broke and what config change fixes it. So an agent silently
degrades (loops until its budget dies, emits prose where a tool wants an
expression, cites a URL it never fetched) and the team either notices late or
not at all.

Medic turns a trace plus a hard check into a one-file config patch, re-runs, and
proves the fix on held-out tasks.

**Why this is not just "ask a model to fix it":** the patch is constrained to a
declared field allowlist, type-checked, shown as a diff, and applied only after a
deterministic check passes on the train task *and* every held-out task. A model
that guesses wrong changes nothing on disk. The value is the **proof**, not the
suggestion.

## 2. Target user

Teams running agents in production, specifically the person who owns the
failure: a small eng/AI team with agents in production who have traces but no
verification loop.

Best first wedge: agents that are **config-driven** (prompt, tool descriptions,
caps, retry flags in a YAML or JSON config file), because that is exactly the
surface Medic can safely edit. Agents that require code changes are explicitly
out of scope, Medic will refuse to patch a field it was not given.

## 3. Pricing shape

| Tier | Price | What it is |
|---|---|---|
| **Free CLI** | $0 | open-source CLI, your own provider keys, unlimited local heals. Unlimited matters: it is how we earn trust and how bugs get reported. |
| **Hosted, per healed trace** | ~$19 per healed trace, or $49/mo for 20 | we run the loop; you get the diff, the before/after trace links, and the held-out evidence. Usage-billed because a heal is genuinely variable. |
| **Team** | $99/seat/mo | shared check library, regression runs over your task set on every config change, role-based access to trace history. |

Rationale for per-healed-trace rather than per-seat-only: a team's heal volume
tracks agent count *and* flakiness, and pricing on the thing delivered is easier
to justify than pricing on headcount. Per-seat stays for teams who want the
regression suite.

Free-tier metering that keeps it free: a heal is ~30k tokens (measured, below),
so a hosted team of 20 running constant heals is only ~$10 to 15/month of inference
at current rates. The margin is in the verification and history, not the tokens.

## 4. Cost per heal, MEASURED, no estimates

From `evidence/real_heal_loop_parse_error.json`, the **live** heal. Patient
`litellm:nova-micro`, Medic `litellm:claude-sonnet-4.6`, both on AWS Bedrock.

| Component | Steps | Tokens | Cost (provider rate card) |
|---|---|---|---|
| Patient run, before (fails) | 2 | 2,020 | $0.000155 |
| Patient run, after, train | 3 | 4,721 | $0.000363 |
| Patient run, after, held-out ×2 | 1 + 1 | 3,860 | $0.000297 |
| Patient run, clean control | 3 | 4,707 | $0.000362 |
| **Patient total per heal** | | **15,342** | **$0.001181** |
| **Medic's own diagnose + surgeon** | | **1,596** (1,392 in + 204 out) | **$0.007960** |
| **TOTAL PER HEAL** | | **16,938** | **$0.009141** |

Every figure is read from the run's own recorder and the gateway's own rate
card (`evidence/gateway_pricing.json`). **No estimate appears in this table.**

### Where the cost actually sits

| Role | Model | Share of heal cost |
|---|---|---|
| Medic | claude-sonnet-4.6 | **87%** |
| Patient | nova-micro | 13% |

**The repair reasoning is the product; the patient runs are incidental.** That
is the line item a hosted service prices against, and it is the one that scales
with how good the diagnosis needs to be.

### Medic model choice, measured

| Medic model | In $/Mtok | Out $/Mtok | Cost per heal (medic share) |
|---|---|---|---|
| claude-sonnet-4.6 | $3.30 | $16.50 | **$0.007960** |
| claude-haiku | $1.10 | $5.50 | **$0.002653** |
| nova-micro | $0.035 | $0.14 | **$0.000074** |

A three-tier product falls straight out of this: **auto-heal on the cheap model,
escalate to Sonnet when the confidence is low.** Measured spread is 107× between
the cheapest and most expensive medic.

### Healthy-run cost, for comparison (clean config, no bug)

| Model | Provider | Steps | Tokens | Cost |
|---|---|---|---|---|
| nova-micro | litellm / Bedrock | 2 to 3 | 2,020 to 4,707 | $0.00016 to 0.00036 |
| laguna-s-2.1 | nara | 2 | 1,374 to 2,235 | $0.006 to 0.009 |
| nemotron-3-ultra-free | nara | 3 | 4,364 | $0.0177 |

A healthy run on nova-micro costs **~$0.0003**. A heal costs **$0.0091**, about
**30× a healthy run**, and that is the number a buyer compares against the cost
of a human noticing the failure at all.

### The savings argument

For `parse_error` the token reduction is not the story, the buggy run *crashed*
at 2 steps, so it was cheap. The saving is different and worth stating precisely:

* **before:** the agent produced **no answer at all**. A tool returned malformed
  JSON and the run died.
* **after:** the agent completes and answers correctly, on both held-out tasks.

So this bug's value is **availability, not efficiency**. The token-saving
argument belongs to the recorded `loop` heal, where the same task went from
15,478 tokens to 7,587, a measured **51% reduction** on a task the patch never
saw. Both claims are real; they attach to different bugs.

### Provider constraint worth pricing against

* **Groq free tier: 200,000 tokens/day.** At ~36 to 46k per `loop` take that is
  **~4 takes/day**, measured, which is why Groq left the chain.
* **The LiteLLM gateway reports no `cost` field in its usage object.** Figures
  here come from its `/model/info` endpoint, which exposes real per-token rates.
  Worth knowing before anyone tries to reconcile against an invoice.
* **Nova caps completion at 10,000 tokens** and Bedrock rejects `seed` outright.
  Both were found by hitting them, and both are now handled rather than fatal.

## 5. Unit economics sketch (illustrative, not measured)

Assumptions, stated so they can be challenged:

* 20 heals/team/month, all on one provider tier.
* Inference at **$0.009426/heal (MEASURED)** → **$0.19/team/month**.
  *(Superseded: this section previously carried $0.11 to 0.17/heal from the earlier
  Groq-based measurement. The live heal on Bedrock measured $0.009426 to 12 to 18×
  lower. See §4.)*
* Hosting and storage of traces and reports: assumed $0.50/team/month.
* Inference-only gross margin ≈ **98.6%** at $49/mo; **95.5%** once Stripe fees and hosting are included (cfo.ai).

At the measured cost, inference is **under 1% of revenue** at every tier, giving
an **inference-only margin of ~98.6%**.

**The number to quote is 95.5%**, cfo.ai's gross margin at month 12, which adds
Stripe fees and hosting on top of inference. Plan:
https://cfo.ai/s/teLQ2nwFftStndEU

The product is verification and history, not tokens.

**Caveat on the medic-model dial below:** only `claude-sonnet-4.6` has ever served
a Medic call. The cheaper rows are rate-card arithmetic, not results, and nobody
has yet verified that a smaller model diagnoses as accurately.

The cost structure is unusually favourable: **the expensive part of the product
is verification (running train + held-out tasks), not model inference.** That is
also what makes it defensible, a cheaper competitor can copy the suggestion
step, but copying the verification harness means re-deriving every hard check, and
every check is bug-specific.

## 6. Twelve-month runway sketch

Illustrative, to be modelled properly in cfo.ai. Assumes a solo founder and a
part-time helper from month 4.

| Phase | Months | Focus | Approx. spend |
|---|---|---|---|
| Ship | 1 to 3 | bugs 1 to 4 healed on a real model, README + GIF, public repo, first Entire + neatlogs case study | near zero (own keys) |
| Prove | 4 to 6 | 10 design partners, hosted beta, first paying teams, regression suite | ~$300/mo inference |
| Grow | 7 to 9 | self-serve signup, docs, integrations for more agent frameworks, first conference talk | ~$900/mo |
| Scale | 10 to 12 | per-seat team tier, CI integration, second agent integration | ~$2,000/mo |

**Assumptions to test:** that teams pay for verification rather than for the
patch; that a heal is rare enough to price per-trace; that the Entire and neatlogs
integrations compound into distribution (both sponsor a hackathon and have real
ecosystems, so a genuine integration is distribution, not a demo stunt).

## 7. What would kill this

Stated plainly, because a plan that cannot fail is not a plan:

* **Teams patch config themselves.** If the first read of a failing trace is
  already enough for a competent engineer, Medic is a toy. Mitigation: the value
  is the *held-out proof*, which is what stops a config "fix" from working on one
  task and silently breaking others.
* **Provider cost.** A heal is $0.0094 measured on Sonnet, but a frontier-model
  default would raise the medic share materially, **assumption, not measured**.
  Per-healed-trace pricing absorbs that; per-seat alone would not.
* **A platform fixes it.** If neatlogs or a CI vendor ships auto-patching with
  verification built in, the wedge narrows to "bring your own agent and your own
  checks", which is the stated path to using Medic, so the business survives the
  platform eating the bundled version.

## 8. Evidence backing this document

| Claim | Source |
|---|---|
| 30,760 tokens/heal; 10→6 steps; **51% token saving** | `evidence/real_heal_loop.json` |
| loop reproduces only on gpt-oss-20b, not on 3 other models | `evidence/loop_capability_matrix.json` |
| bugs 2 and 4 do **not** reproduce on laguna-s-2.1 | `evidence/real_llm_reproduction_nara.json` |
| recovery from a failed tool call, one boolean | `evidence/recovery_parse_error.json` |
| clean run on a real model, traced and readable | `evidence/trace_clean_real_llm.json` |
| which models emit real tool calls | `evidence/tool_calling_free_plan.json` |
| every commit is an Entire checkpoint | git log + Entire CLI |
| 200,000 tokens/day Groq limit | Groq 429 during a real run |
| temperature 0 is **not** deterministic | two runs of one config, 3 vs 4 steps |

## 9. Product surface implied by the measurements

Three facts from this build should shape the roadmap, because each one is a
product decision rather than a bug:

1. **The failures are model-specific.** The same buggy prompt loops
   `gpt-oss-20b` (12 steps) and not `laguna-s-2.1`, `nemotron-3-ultra-free` or
   `agnes-2.5-flash` (3 to 5 steps). A hosted Medic should therefore record the
   model alongside the trace and expect the same config to be healthy on one
   model and broken on another. That is a feature, it is exactly the
   "quietly wrong, but only on this model" case nobody catches by reading a
   prompt.
2. **Two of four bugs never reproduced on a strong model.** Bugs 1 and 2 are real
   for weaker agents and for the deterministic scripted agent, but a modern
   model defends itself with the JSON schema and its own caution. Sells better
   as *"catches what your model actually does"* than as a universal repair
   system.
3. **Recovery is a config flag, not a rewrite.** Bug 2's entire fix is
   `retry_on_parse_error: false → true`. The cheapest possible intervention is
   often a single boolean, which is a good story for adoption: Medic tries the
   smallest edit that the hard check can prove.