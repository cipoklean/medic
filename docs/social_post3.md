# Post 3 — the live heal (DRAFT, not posted)

**Under 280 characters, per your constraint.**

---

## The post

> Medic healed a real agent today. A tool returned malformed JSON and the run
> **died** — no answer at all.
>
> It read the trace, named the fault at **0.95** confidence, and changed **one
> boolean**.
>
> 2 steps FAIL → 3 steps PASS. **$0.009**.
>
> 🧵

**Character count: 238.** ✅

---

## Numbers used, and where each comes from

| Claim | Evidence |
|---|---|
| run died, no answer | `real_heal_loop_parse_error.json` → `before.answer` empty |
| 0.95 confidence | `attempts[0].diagnosis.confidence` |
| one boolean | `diff`: `retry_on_parse_error: false → true` |
| 2 steps → 3 steps | `before.metrics.steps=2`, `verify.train.steps=3` |
| $0.009 | measured, no estimate (see below) |
| held-out | 4 tasks, all passed — **not in the post body**, see note |

**Cost breakdown if a reply asks:**

```
Medic on Sonnet        1,568 tok  $0.007511
Patient on nova-micro 24,874 tok  $0.001915
TOTAL                 26,442 tok  $0.009426
```

---

## Note on the held-out claim

You asked for the held-out result in the post. It doesn't fit in 280 with
everything else, and **four held-out tasks passing is stronger than the character
budget suggests** — so it belongs in the thread, not the top post.

**Suggested reply #1 (the held-out detail):**

> And the part I care about most: it passed **four tasks it had never seen.**
>
> Two of them don't contain the answer anywhere in the question — you have to
> fetch a page to get the figure, and the page is where the broken JSON lives.
>
> So those two genuinely test the fix.

**267 characters.**

---

## Alternative framings

**If you want the cost angle to lead** (237 chars):

> The part I didn't expect: the repair reasoning is **80% of the cost**.
>
> $0.009 to heal. The medic is $0.0075 of that; the patient runs are $0.0019.
>
> The medic model is a **dial**, not a fixed cost — 107× between nova-micro and
> Sonnet.
>
> 🧵

**If you want the harness finding to lead** (249 chars) — this is the strongest
hook and pairs with post 3's thread:

> A green test suite hid an arithmetic error for as long as it ran.
>
> It expected **$10.00** for `169.98 − 79.99`. The answer is **$89.99** — and the
> stub that "verified" it returned `169.98-(79.99*2)` to match.
>
> A real model caught it in nine runs.
>
> 🧵

---

## Suggested order

**Post 3 → reply with the held-out detail → optional second post with the cost or
harness framing.** The heal is the news; the harness finding is the follow-up that
makes people trust the heal.

## Do not say

* Any cost figure that isn't `$0.009426` total, `$0.007511` medic, `$0.001915`
  patient.
* "It heals everything" — one bug class, one host.
* That the original held-out pair tested the fix — they didn't, and the two new
  page-only tasks exist precisely because of that.