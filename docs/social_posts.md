# Two #neatHack posts — DRAFT, not posted

For your review. Each is under 280 characters, each number traces to `evidence/`.

---

## Post 1 — the heal

> Built **Medic** for #neatHack: an agent that reads a failing agent's neatlogs
> trace, patches one config file, and proves the fix on tasks it never saw.
>
> Real heal, real model (`gpt-oss-20b`), measured:
> **12 steps failing → 6 passing.**
>
> It never touched Python.
>
> 🧵

**262 chars.** Evidence: `evidence/real_heal_loop.json`

---

## Post 2 — the capability matrix

> The finding that made me build it: **the same buggy prompt broke one model and
> not three others.**
>
> `gpt-oss-20b` looped 12 steps past its limit.
> `laguna-s-2.1`, `nemotron-3-ultra-free`, `agnes-2.5-flash` all answered
> correctly, 3–5 steps.
>
> Nobody catches that by re-reading the prompt.
>
> 🧵

**247 chars.**

> The finding that made me build it: **the same buggy prompt broke one model and
> not three others.**
>
> `gpt-oss-20b` looped 12 steps past its limit. Three other models answered
> correctly in 3–5 steps.
>
> Nobody catches that by re-reading the prompt.
>
> 🧵

---

## Alternative: the token saving

> The part I didn't expect: Medic doesn't just stop the failure, it makes the
> agent **cheaper**.
>
> 15,478 tokens before the patch. 7,587 after — same task.
>
> **51% fewer.** The fix wasn't "use a smaller model". It was one field in one
> config file.
>
> 🧵

**246 chars.** Evidence: `evidence/real_heal_loop.json`

---

## Notes for you

* **Say which model** in post 1. Naming it is what makes the claim checkable, and
  the capability matrix only lands if post 1 sets it up.
* **Don't claim bugs 1, 2 and 4** reproduce on a real model. They don't. If
  anyone asks, that's the honest answer and it's an interesting one.
* The token-saving post is the strongest standalone hook if the heal post gets no
  traction — it reframes the project as a cost win rather than a debugging tool.
* Suggested thread order: **1 → 2**, so the matrix reads as a follow-up finding
  rather than the pitch.