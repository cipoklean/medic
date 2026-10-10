# Medic — cfo.ai input sheet

Paste-ready. **Every number is either MEASURED (with its evidence file) or marked
ASSUMPTION.** Nothing is estimated and left unlabelled.

---

## 1. Product and customer

**Product:** Medic reads a failing AI agent's trace, diagnoses the broken step,
patches one config file, and *proves* the fix on tasks it has never seen. The
model proposes; deterministic hard checks decide.

**Who pays:** engineering teams already running AI agents in production — the
people who get paged when an agent quietly starts failing. Not hobbyists: the
free CLI serves them.

**What is actually being bought:** not the patch. The patch is often one boolean.
What is bought is the **held-out proof** — evidence that a config change fixes the
task you saw *and* does not break tasks you did not. That is what stops a
plausible "fix" from shipping.

---

## 2. Pricing — three tiers

| Tier | Price | Rationale |
|---|---|---|
| **Free CLI** | $0 | Open source, your own provider keys, unlimited local heals. Earns trust and surfaces bugs. Deliberately unmetered — it is the distribution channel. |
| **Hosted, per healed trace** | **$19/heal**, or **$49/mo for 20** | A heal is genuinely variable, and billing on the thing delivered is easier to justify than headcount. $49/mo caps a team's exposure while covering ~20 heals. |
| **Team** | **$99/seat/mo** | Shared check library, regression runs over your task set on every config change, role-based trace history. For teams who want the suite, not just the repair. |

**Why per-heal leads:** heal volume tracks agent count *and* flakiness, so it
scales with value received. Per-seat is retained for the regression suite, which
is a different product.

---

## 3. Unit cost per heal — MEASURED

Source: `evidence/real_heal_loop_parse_error.json`. Patient `nova-micro`, Medic
`claude-sonnet-4.6`, both on AWS Bedrock via a LiteLLM gateway. Rates from the
gateway's own `/model/info` endpoint (`evidence/gateway_pricing.json`).

| Component | Tokens | Cost |
|---|---|---|
| Medic (diagnose + surgeon) on Sonnet | 1,568 | **$0.007511** |
| Patient verification runs on nova-micro | 24,874 | **$0.001915** |
| **Inference cost per heal** | **26,442** | **$0.009426** |

**Measured, not estimated.** This covers train + four held-out tasks + clean
control — the full verification, not just the suggestion.

### The medic model is a cost dial — PRICED, not yet run

| Medic model | Cost/heal (medic share) | Has it actually healed anything? |
|---|---|---|
| claude-sonnet-4.6 | **$0.007511** | **Yes — the measured heal in this sheet** |
| claude-haiku | $0.002653 | No |
| nova-micro | $0.000074 | No |

**Only Sonnet has ever served a Medic call.** The rows below it are arithmetic on
the gateway's rate card, not results: nobody has yet checked whether a cheaper
model diagnoses as accurately. The 107× spread is therefore a *price ratio*, and
it is the reason a cheaper tier is worth testing — not evidence that one works.

The open question a pilot should answer: **does claude-haiku hold 0.95 confidence
on the same trace?** If yes, the medic cost falls to $0.0027 and tiered
auto-healing becomes real rather than theoretical.

### Monthly fixed costs

| Item | Cost | Basis |
|---|---|---|
| Hosting (1 small VM + Postgres + object storage) | **$40/mo** | ASSUMPTION — single Oracle/AWS small instance, trace + report storage |
| neatlogs (trace ingest, hosted tier) | **$0–50/mo** | ASSUMPTION — depends on trace volume; their free tier covers build-stage volume |
| Domain, email, misc | **$10/mo** | ASSUMPTION |
| **Total fixed** | **$50–100/mo** | |

---

## 4. Gross margin per tier — MEASURED cost, ASSUMED volume

Inference is **$0.009426/heal measured**. Allocations below are assumptions.

| Tier | Price | Variable cost/heal | Gross margin |
|---|---|---|---|
| Free CLI | $0 | $0 (user's own keys) | n/a — acquisition cost |
| Hosted, single heal | $19 | $0.0094 inference + $0.50 hosting | **~97%** |
| Hosted, $49/mo for 20 | $49 | $0.188 inference (20 × $0.0094) + $0.50 hosting | **~98.6%** (inference-only; cfo.ai reports 95.5% with fees) |
| Team, $99/seat/mo | $99 | $0.0094/heal × assumed 20 heals + $0.50 | **~98%** |

**Inference-only gross margin ≈ 98.6%, measured.** Inference is **under 1% of
revenue** at every tier, from a heal that was actually run end to end — not
modelled.

**Note for the built plan:** cfo.ai reports **95.5%** gross margin at month 12,
because it adds Stripe fees and hosting on top of inference. **95.5% is the number
to quote externally**; 98.6% is what the margin would be if tokens were the only
cost. Plan: https://cfo.ai/s/teLQ2nwFftStndEU

**The cost structure is the business case:** the product is verification and
history, not tokens. A competitor can copy the suggestion step; copying the
verification harness means re-deriving every hard check, and every check is
bug-specific.

*Note:* these margins assume Medic's inference is billed to us. On the Team tier
a customer may supply their own keys, which raises margin further — ASSUMPTION,
not modelled.

---

## 5. Twelve-month revenue scenarios

**Customer counts are ASSUMPTIONS throughout.** Only the per-heal cost and price
points are measured. Solo founder, **$0 raised**.

| | Conservative | Base | Optimistic |
|---|---|---|---|
| Paying teams, month 12 | **8** | **30** | **90** |
| Avg seats/team | 1.5 | 2.0 | 3.0 |
| Heals/team/mo (month 12) | 12 | 20 | 30 |
| Avg revenue/team/mo | $49 | $62 (blended) | $85 (blended) |
| **MRR, month 12** | **$392** | **$1,860** | **$7,650** |
| **ARR exit rate** | **~$4,700** | **~$22,300** | **~$91,800** |

**Ramp shape (ASSUMPTION):** months 1–3 build and open-source (revenue $0),
months 4–6 first 3–5 design partners, months 7–9 self-serve signup, months 10–12
the team tier and CI integration.

**Conversion assumption:** 2–4% of free-CLI monthly actives convert to a paid
tier. Untested — this is the single biggest unknown in the model.

---

## 6. Monthly burn and runway — solo founder, $0 raised

| Phase | Months | Spend/mo | Note |
|---|---|---|---|
| Ship | 1–3 | **$50–100** | own provider keys, own time. Effectively free. |
| Prove | 4–6 | **$150–300** | design-partner inference + hosting |
| Grow | 7–9 | **$300–600** | hosting + conference talk |
| Scale | 10–12 | **$600–1,200** | more integrations, part-time helper |

**Founder compensation: $0** throughout — solo, unfunded, living on savings.
That is the assumption that makes the runway work, and it is the one most likely
to break first.

**Runway:** at $50–100/mo the pre-revenue phase is funded by **essentially
nothing** — a personal card covers it for years. Cash-flow breakeven arrives when
MRR exceeds ~$150/mo, i.e. **~3 paying teams at $49**. In the base case that is
month 5–7; conservative, month 8–10.

**Twelve-month cash need: ~$3,000–6,000 total**, of which most is optional
(conference talk, part-time help). The business does not need capital to reach
proof; it needs capital to skip the solo phase.

---

## 7. What would kill this

Stated plainly, because a plan that cannot fail is not a plan.

* **Teams patch config themselves.** If reading a failing trace is already enough
  for a competent engineer, Medic is a toy. Mitigation: the value is the held-out
  proof, not the suggestion.
* **Nobody pays for verification.** The entire model rests on this. It is
  untested and is the first thing a pilot should measure.
* **A platform ships it.** If neatlogs or a CI vendor bundles auto-patching with
  verification, the wedge narrows to "bring your own agent and your own checks" —
  which is already the stated adoption path, so the business survives the platform
  eating the bundled version.
* **Frontier-model default.** A frontier medic model would put a heal nearer
  $1.50 (ASSUMPTION, not measured). Per-heal pricing absorbs that; per-seat alone
  would not.
* **Conversion stays at zero.** Free CLI users may simply never convert. No
  mitigation beyond making the hosted tier obviously worth $49.

---

## 8. Evidence backing every measured number

| Claim | File |
|---|---|
| Cost per heal $0.009426 | `evidence/real_heal_loop_parse_error.json` |
| Rate card (Sonnet $3.30/$16.50 per M) | `evidence/gateway_pricing.json` |
| Held-out verification works (4 tasks) | `evidence/page_only_heldout.json` |
| Diagnosis accuracy 0.95 confidence | `evidence/real_heal_loop_parse_error.json` |
| Bugs are model-specific | `evidence/loop_capability_matrix.json` |
| 39/39 clean gate | `evidence/gate_nova_micro_clean.json` |

**Every ASSUMPTION in this sheet is labelled.** The measured core is small and
hard: one heal, its cost, its accuracy, and its verification. Everything about
customers, conversion and burn is assumption and should be challenged as such.

**One further distinction worth stating:** the cost dial in §3 is priced, not
proven. Sonnet is the only model that has served a Medic call; haiku and
nova-micro are rate-card arithmetic. A plan that presents a price as a result is
the same error this project keeps catching in its own tests.
