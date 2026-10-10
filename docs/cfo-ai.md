# cfo.ai — Medic business plan

Sponsor: **cfo.ai**. The input sheet is
[`cfo-ai-input.md`](cfo-ai-input.md) — paste that in, not this file.

---

## Export

<!-- Paste the cfo.ai share/export link here once the plan is built. -->

**Plan URL:** _pending_

**Built:** _pending_

---

## Screenshots

Drop them in `docs/assets/` and reference them below, so the video and the README
can pull the same images.

| Frame | File | Shows |
|---|---|---|
| Pricing tiers | `docs/assets/cfo-pricing.png` | the three tiers and their rationale |
| Unit economics | `docs/assets/cfo-unit-cost.png` | $0.009426/heal, margin under 1% inference |
| Margin by tier | `docs/assets/cfo-margin.png` | ~97–98.6% gross margin |
| 12-month revenue | `docs/assets/cfo-revenue.png` | conservative / base / optimistic |
| Runway | `docs/assets/cfo-runway.png` | burn by phase, breakeven at ~3 teams |

---

## The numbers to put on screen in the video

Lead with the margin — it is the only one that is both measured and flattering.

1. **98.6% gross margin** — MEASURED, from a heal that actually ran end to end
2. **$0.009426 per heal** — measured, not estimated; inference is under 1% of
   revenue at every tier
3. **80% of that cost is the medic's reasoning** — the priced product is the
   diagnosis, not the patient runs
4. **~3 paying teams to breakeven** — at $49/mo against $150/mo burn

**Do not lead with the 107× medic-model spread.** Only Sonnet has ever served a
Medic call; haiku and nova-micro are rate-card arithmetic, not results. It is a
price ratio and belongs in the sheet as an open question — "does haiku hold 0.95
confidence?" — not on screen as a finding.

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

- [ ] Input sheet pasted into cfo.ai
- [ ] Export link added above
- [ ] Screenshots captured to `docs/assets/`
- [ ] Numbers reconciled against `docs/business.md` §4

> **Known discrepancy to fix while building the plan:** `docs/business.md` §5
> still quotes inference at **$0.11–0.17/heal**, from the earlier Groq-based
> measurement. The current measured figure is **$0.009426** — 12–18× lower. Use
> the measured number; §5 needs updating to match.
