# cfo.ai, Medic business plan

Sponsor: **cfo.ai**. The input sheet is
[`cfo-ai-input.md`](cfo-ai-input.md), paste that in, not this file.

---

## Export

<!-- Paste the cfo.ai share/export link here once the plan is built. -->

**Plan URL:** https://cfo.ai/s/teLQ2nwFftStndEU

**Built:** 2026-10-10 · main scenario, 30 teams

---

## Screenshots

Drop them in `docs/assets/` and reference them below, so the video and the README
can pull the same images.

| Frame | File | Shows |
|---|---|---|
| Pricing tiers | `docs/assets/cfo-pricing.png` | the three tiers and their rationale |
| Unit economics | `docs/assets/cfo-unit-cost.png` | $0.009426/heal, margin under 1% inference |
| Margin by tier | `docs/assets/cfo-margin.png` | 95.5% at month 12 (incl. fees + hosting) |
| 12-month revenue | `docs/assets/cfo-revenue.png` | conservative / base / optimistic |
| Runway | `docs/assets/cfo-runway.png` | burn by phase, breakeven at ~3 teams |

---

## The numbers to put on screen in the video

From the built cfo.ai plan, main scenario (30 teams):

1. **95.5% gross margin** at month 12, the plan's own figure, and the one to
   quote. It includes Stripe fees and hosting.
2. **MRR month 12 (Sep 2027): $1,859** · **ARR run rate Dec 2027: $29,690**
3. **$0.009426 per heal**, measured, not estimated
4. **$225 total cash required** · **first cash-positive month: Jan 2027**

**On the two margin numbers, do not mix them up:**

* **95.5%** is the cfo.ai plan's gross margin. It is the real one, because it
  includes Stripe fees and hosting. Quote this.
* **98.6%** is our *inference-only* margin, from the measured heal. It is what the
  margin would be if tokens were the only cost. It is not the plan's number.

The gap between them is Stripe and hosting, and that gap is the honest part.

**Do not lead with the 107× medic-model spread.** Only Sonnet has ever served a
Medic call; haiku and nova-micro are rate-card arithmetic, not results. It is a
price ratio and belongs in the sheet as an open question, "does haiku hold 0.95
confidence?", not on screen as a finding.

---

## What is measured vs assumed

Everything in the input sheet is labelled, but the short version:

**MEASURED** (evidence file exists):
cost per heal, the rate card, the medic-model cost dial, diagnosis confidence,
four held-out tasks passing, 39/39 clean gate.

**ASSUMED** (challenge these):
customer counts, conversion rate, seats per team, heals per team per month,
hosting and neatlogs fixed costs, founder compensation of $0.

The measured core is deliberately small and hard. The assumptions are the model.

---

## Status

- [x] Input sheet pasted into cfo.ai
- [x] Export link added above
- [x] Plan numbers recorded (main scenario, 30 teams)
- [ ] Screenshots captured to `docs/assets/`
- [ ] Numbers reconciled against `docs/business.md` §4 to 5

> **Two margin figures, deliberately kept separate.** cfo.ai reports **95.5%**
> gross margin at month 12, which includes Stripe fees and hosting, that is the
> number to quote anywhere externally. Our own **98.6%** is inference-only. Both
> are correct; they answer different questions.
