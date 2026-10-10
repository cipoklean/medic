# Medic — business model draft inputs for cfo.ai

> These are **inputs**, not a finished plan. Every number is measured from a real
> run in `evidence/`; anything unmeasured is labelled as such. Nothing here is
> invented to fill a field.

## 1. The problem

Teams running agents in production already pay for observability — they see the
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

Teams running agents in production — specifically the person who owns the
failure: a small eng/AI team with agents in production who have traces but no
verification loop.

Best first wedge: agents that are **config-driven** (prompt, tool descriptions,
caps, retry flags in a YAML or JSON config file), because that is exactly the
surface Medic can safely edit. Agents that require code changes are explicitly
out of scope — Medic will refuse to patch a field it was not given.

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
so a hosted team of 20 running constant heals is only ~$10–15/month of inference
at current rates. The margin is in the verification and history, not the tokens.

## 4. Cost per heal — MEASURED

From `evidence/real_heal_loop.json` (bug `loop`, `openai/gpt-oss-20b`, temperature 0):

| Component | Tokens |
|---|---|
| Patient run, before (fails, 10 steps) | 15,478 |
| Patient run, after — train | 7,587 |
| Patient run, after — held-out ×2 | 7,695 |
| **Patient total per heal** | **30,760** |
| Medic's own diagnose + surgeon | **not captured** by that run — see below |

Cost at our rate table (`patient/tracing.py`: $3/M input, $15/M output):

* before-run alone: **$0.0568**
* full heal, patient runs only: **~$0.113**

**Honest gaps in this number:**

* Medic's own diagnose and surgeon tokens were **not captured** in the run that
  produced the evidence — the CLI did not print them. Adding a diagnosis over a
  15-span trace plus a patch is plausibly 5–15k tokens (that span tree is the bulk
  of the prompt), so a realistic full-heal figure is **$0.13–$0.17**. This is an
  **estimate** and is labelled as one.
* gpt-oss-20b is a small hosted model. A frontier model would be materially more
  per heal, probably 5–15× — which is why per-healed-trace pricing scales
  naturally with model choice.
* The rate table is ours, not a provider invoice.

**Provider constraint worth pricing against:** Groq's free tier is
**200,000 tokens/day**. At ~30k tokens per heal that is **~6 heals/day** on the
free tier — measured, not theoretical. A hosted product would use a paid tier or a
smaller model; the free CLI keeps provider keys with the user precisely so this
cost stays with them.

## 5. Unit economics sketch (illustrative, not measured)

Assumptions, stated so they can be challenged:

* 20 heals/team/month, all on one provider tier.
* Inference at 30k tokens/heal → $0.11–0.17/heal → **$2–3.40/team/month**.
* Hosting and storage of traces and reports: assumed $0.50/team/month.
* Gross margin ≈ **85–95%** at $49/mo.

The cost structure is unusually favourable: **the expensive part of the product
is verification (running train + held-out tasks), not model inference.** That is
also what makes it defensible — a cheaper competitor can copy the suggestion
step, but copying the verification harness means re-deriving every hard check, and
every check is bug-specific.

## 6. Twelve-month runway sketch

Illustrative, to be modelled properly in cfo.ai. Assumes a solo founder and a
part-time helper from month 4.

| Phase | Months | Focus | Approx. spend |
|---|---|---|---|
| Ship | 1–3 | bugs 1–4 healed on a real model, README + GIF, public repo, first Entire + neatlogs case study | near zero (own keys) |
| Prove | 4–6 | 10 design partners, hosted beta, first paying teams, regression suite | ~$300/mo inference |
| Grow | 7–9 | self-serve signup, docs, integrations for more agent frameworks, first conference talk | ~$900/mo |
| Scale | 10–12 | per-seat team tier, CI integration, second agent integration | ~$2,000/mo |

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
* **Provider cost.** 30k tokens/heal is cheap, but a frontier-model default
  would put a heal at ~$1.50. Per-healed-trace pricing absorbs that; per-seat
  alone would not.
* **A platform fixes it.** If neatlogs or a CI vendor ships auto-patching with
  verification built in, the wedge narrows to "bring your own agent and your own
  checks" — which is the stated path to using Medic, so the business survives the
  platform eating the bundled version.

## 8. Evidence backing this document

| Claim | Source |
|---|---|
| 30,760 tokens per heal; before/after step counts | `evidence/real_heal_loop.json` |
| real model reproduces the loop bug (12 steps vs limit 8) | `evidence/real_llm_reproduction.json` |
| recovery from a failed tool call, one boolean | `evidence/recovery_parse_error.json` |
| clean run on a real model, traced and readable | `evidence/trace_clean_real_llm.json` |
| every commit is an Entire checkpoint | git log + Entire CLI |
| 200,000 tokens/day provider limit | Groq 429 response during a real run |