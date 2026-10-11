# Medic, limits and findings

Relocated from the README so the front page could lead with what works. Nothing
here is new: every number and claim is the same one the README carried.

## Which bugs reproduce where

| Bug | `nova-micro` (Bedrock) | `groq/gpt-oss-20b` | `nara/laguna-s-2.1` |
|---|---|---|---|
| `parse_error` | **FAIL 3/3, healed live** | not tested | not tested |
| `hallucinated_citation` | **FAIL 3/3, healed live** | not tested | not tested |
| `loop` | PASS | **FAIL, 12 steps** | PASS, needs `loop_strong` |
| `wrong_args` | **PASS 3/3** | FAIL | PASS |

`wrong_args` does **not** reproduce on Nova, and the reason is structural: the
preset only weakens the tool description, but the JSON schema still declares
`expression` as required, and nova-micro reads the schema and complies (0 of 3,
[`scripts/probe_wrong_args.py`](scripts/probe_wrong_args.py)). `hallucinated_citation`
fails 3/3 on `nova-micro` and passes on `nova-lite`: same prompt, same fixtures,
different model.

## Two bugs a real model caught in my own harness

**A green suite hid an arithmetic error for as long as it ran.**
`parse-error-gadgets` expected $10.00 for `$169.98 - $79.99`. The answer is $89.99.
The scripted LLM returned `169.98-(79.99*2)` to match it, so both halves of the
test agreed and both were wrong. A real model computed 89.99 and the check failed
it. Every `expected_answer` is now re-derived from its fixture by
[`tests/test_expectations.py`](tests/test_expectations.py), which caught a second
wrong expectation on its first run.

**The search snippets leaked every answer.** That made `fetch_page` optional, so a
bug inside `fetch_page` could never fire: `parse_error` first showed 0 of 9 with
no parse error in any trace. Snippets now carry no figures, enforced by a test.

---

## Honest limits, in full

* **Two live heals, both on one host:** `parse_error` and
  `hallucinated_citation` on `nova-micro`. That is the whole live claim.
* **A real model at temperature 0 is not bit-identical.** Two runs of the same
  clean config on `nara/laguna-s-2.1` took 3 and 4 steps. Earlier-provider result;
  the script was removed in cleanup, the number stands in
  [`evidence/loop_capability_matrix.json`](evidence/loop_capability_matrix.json).
* **`loop_strong` is a deliberately strengthened preset**, built so `laguna-s-2.1`
  reproduced. The original `loop.yaml` does not reproduce there. Earlier-provider
  result, backed by
  [`evidence/repro_loop_strong_laguna.json`](evidence/repro_loop_strong_laguna.json).
* **The medic cost dial is measured, with the patient held fixed.** Sonnet
  $0.009557 and Haiku $0.004419 per heal, same patient, same tasks. A frontier
  model has not been tried.
* **The original held-out pair does not test `parse_error`.** Both state their
  figures in the question, so they never fetch a page and never meet the bug; the
  two page-only tasks exist for that gap. Cost figures come from the gateway's own
  rate card, not an invoice.
* The offline suites prove the machinery. Only a real run proves a heal.

## Evidence index

| Claim | File |
|---|---|
| live heal, `parse_error`, Sonnet | `evidence/real_heal_loop_parse_error.json` |
| live heal, `hallucinated_citation`, Sonnet | `evidence/real_heal_loop_hallucinated_citation.json` |
| same heal on Haiku, patient held fixed | `evidence/real_heal_parse_error_haiku_pinned_claude-haiku.json` |
| first Haiku run, patient was nova-lite so totals are not comparable | `evidence/real_heal_parse_error_haiku_nova-lite_unpinned.json` |
| 3/3 reproduction, parse_error | `evidence/repro_parse_error_nova_micro.json` |
| 3/3 reproduction, hallucinated_citation | `evidence/repro_citation_nova_micro.json` |
| 39/39 clean gate | `evidence/gate_nova_micro_clean.json` |
| model-by-model reproduction | `evidence/loop_capability_matrix.json` |
| earlier-provider loop_strong result | `evidence/repro_loop_strong_laguna.json` |
| historical Groq loop heal, Oct 10 2026 | `evidence/real_heal_loop.json` |
| gateway rate card | `evidence/gateway_pricing.json` |
| every gateway model's tool calling | `evidence/gateway_tool_calling_smoke.json` |
