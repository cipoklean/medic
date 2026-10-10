"""The ONE LLM call Medic makes, for diagnose and surgeon.

Always the real model. A scripted model diagnosing a scripted patient would be
grading its own homework, so there is deliberately no scripted fallback here:
if credentials are missing, these steps fail loudly rather than pretending.

Every call is traced to neatlogs under workflow_name="medic" so the judge's
dashboard shows the patient run and the repair run side by side.
"""
from __future__ import annotations

import json
import os
import time
import re
from typing import Any

from patient.tracing import init_neatlogs, neatlogs_active


class MedicLLMUnavailable(RuntimeError):
    """Raised when no provider is configured at all (see providers.NoProviderConfigured)."""


def _client():
    """First provider in the chain that is configured.

    Failover happens per call in ask_json(), not here: which provider served a
    given request depends on when it runs, and a run that silently mixes
    providers mid-heal is exactly the thing the evidence must not hide.
    """
    from medic import providers as prov

    client, provider = prov.build_client()
    return client, provider


def ensure_traced() -> None:
    init_neatlogs("medic", tags=["medic-repair"])


def ask_json(
    system: str,
    user: str,
    recorder=None,
    span_name: str = "medic_llm",
    max_tokens: int | None = None,
    budget_retries: int = 2,
    rate_limit_retries: int = 6,
) -> tuple[dict, dict]:
    """Returns (parsed_json, usage_metrics). Usage is measured, never guessed.

    `max_tokens` must allow for REASONING tokens. openai/gpt-oss-20b spends
    ~73 of 87 completion tokens thinking on a trivial reply; a large span-tree
    prompt pushes its reasoning well past 1200, and the provider then rejects
    the request with `json_validate_failed: max completion tokens reached
    before generating a valid document` — an error that looks like a bad prompt
    but is really a truncated budget.

    A truncation is retried with a larger budget before giving up, because one
    heuristic ceiling is wrong for every prompt and every model.
    """
    from medic import providers as prov
    from medic.ratelimit import limiter_for

    client, provider = _client()
    ensure_traced()
    ceiling = max_tokens or int(os.environ.get("MEDIC_LLM_MAX_TOKENS", "8000"))

    # Budget exhaustion doubles the token ceiling; a rate limit just waits.
    # They need separate budgets: a heal can be rate-limited many times in one
    # minute and should survive it, while doubling max_tokens past a truncation
    # twice is pointless.
    last_err: Exception | None = None
    budget_attempts = 0
    for attempt in range(rate_limit_retries + 1):
        limit = ceiling * (2 ** budget_attempts)
        try:
            # Pace THIS process. Free plans are 15 req/min and a heal is a burst.
            limiter_for(provider.name).acquire()
            span_cm = (
                recorder.span("LLM", span_name, {"system": system[:200], "user": user[:400]})
                if recorder
                else _null_span()
            )
            with span_cm as span:
                resp = client.chat.completions.create(
                    model=provider.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0,
                    response_format={"type": "json_object"},
                    max_tokens=limit,
                )
                content = resp.choices[0].message.content or ""
                usage = getattr(resp, "usage", None)
                p_tok = getattr(usage, "prompt_tokens", 0) or 0
                c_tok = getattr(usage, "completion_tokens", 0) or 0
                reasoning = 0
                details = getattr(usage, "completion_tokens_details", None)
                if details is not None:
                    reasoning = getattr(details, "reasoning_tokens", 0) or 0
                if span is not None:
                    # Record WHO served this call. An evidence file that cannot
                    # say which provider answered is not evidence.
                    span["provider"] = provider.label()
                    span["prompt_tokens"] = p_tok
                    span["completion_tokens"] = c_tok
                    span["total_tokens"] = p_tok + c_tok
                    span["output"] = content[:2000]

            metrics = {
                "provider": provider.name,
                "provider_label": provider.label(),
                "model": provider.model,
                "prompt_tokens": p_tok,
                "completion_tokens": c_tok,
                "reasoning_tokens": reasoning,
                "total_tokens": p_tok + c_tok,
                "max_tokens_budget": limit,
            }
            return parse_json(content), metrics
        except Exception as exc:
            last_err = exc
            if _is_model_unsupported(exc):
                # A reachable provider whose current model rejects the request
                # (NaraRouter's jev and exo-stealh both do on a tools array).
                # Rotating models beats abandoning a working provider.
                nxt_model = prov.next_model(provider)
                if nxt_model is not None:
                    print(f"[medic] {provider.label()} cannot serve this request; "
                          f"rotating to {nxt_model.label()}")
                    provider = nxt_model
                    client, _ = prov.build_client(preferred=nxt_model.name)
                    budget_attempts = 0
                    continue
            if _is_daily_limit(exc):
                nxt = prov.next_provider(provider)
                if nxt is not None:
                    # A daily budget is not transient, but a SECOND provider is
                    # exactly the answer to it. Fail over and keep going.
                    print(f"[medic] {provider.label()} daily budget exhausted; "
                          f"failing over to {nxt.label()}")
                    client, provider = prov.build_client(preferred=nxt.name)
                    continue
                raise RuntimeError(_daily_limit_message(exc)) from exc
            if _is_rate_limited(exc):
                # Groq enforces a per-MINUTE tokens budget. A heal makes many
                # calls in a burst (diagnose, surgeon, then verify on train +
                # every held-out task), so hitting this is routine, not fatal.
                # Retry with the delay the provider states, bounded.
                wait = _retry_after(exc, attempt)
                # A per-MINUTE budget needs a real wait; a per-second one does
                # not. Floor it at the limiter's own interval so we never retry
                # faster than the rate we just enforced.
                time.sleep(max(min(wait, 60.0), 60.0 / max(1, limiter_for(provider.name).max_calls)))
                continue
            if _is_budget_error(exc):
                budget_attempts += 1
                if budget_attempts > budget_retries:
                    raise
                continue
            raise

    raise last_err if last_err else RuntimeError("ask_json failed with no error recorded")


def _is_model_unsupported(exc: Exception) -> bool:
    """The provider answered but this model cannot serve the request."""
    text = str(exc).lower()
    return "400" in text and ("does not exist" in text or "rejected this request" in text)


def _is_daily_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return "tokens per day" in text or "(tpd)" in text


def _parse_go_duration(text: str) -> float | None:
    """Parse a Go duration such as '12m30.816s' into MINUTES."""
    import re as _re

    text = text.strip()
    m = _re.match(r"^(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?$", text)
    if not m:
        try:
            return float(text) / 60.0
        except ValueError:
            return None
    h, mi, sec = (float(g) if g else 0.0 for g in m.groups())
    return h * 60.0 + mi + sec / 60.0


def _daily_limit_message(exc: Exception) -> str:
    """Turn a raw 429 into an instruction the operator can act on."""
    import re as _re

    m = _re.search(r"tokens per day \(TPD\): Limit (\d+), Used (\d+)", str(exc))
    # Greedy on the number, then swallow a Go-style unit: 'try again in 12m30.816s'
    # otherwise captures just '12' and renders a 12-minute wait as 12 seconds.
    wait = _re.search(r"try again in ([0-9.]+(?:h\d+m)?(?:m\d+(?:\.\d+)?s)?(?:\d+(?:\.\d+)?s)?)", str(exc))
    parts = [
        "PROVIDER DAILY TOKEN BUDGET EXHAUSTED — this is not a transient error.",
        "Retrying will not help until the daily window resets.",
    ]
    if m:
        limit, used = int(m.group(1)), int(m.group(2))
        parts.append(f"Limit {limit:,} tokens/day, {used:,} used ({used / limit:.1%}).")
    if wait:
        # Groq writes durations like "12m30.816s" or "1.529999999s". A naive
        # float() on "12m30.816" is a ValueError, and reading only the leading
        # number turns 12 minutes into 12 seconds — which is the sort of small
        # wrong number that makes a wait look instantaneous.
        mins = _parse_go_duration(wait.group(1))
        if mins is not None:
            secs = mins * 60.0
            if secs < 90:
                parts.append(f"Resets in about {secs:.0f} seconds.")
            elif mins < 90:
                parts.append(f"Resets in about {mins:.0f} minutes.")
            else:
                parts.append(f"Resets in about {mins / 60:.1f} hours.")

    parts.append("Options: wait for the reset, switch provider via LLM_BASE_URL / "
                 "LLM_API_KEY, or raise the Groq tier.")
    return "\n  ".join(parts)


def _is_rate_limited(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "rate limit" in text or "429" in text or "rate_limit_exceeded" in text


def _retry_after(exc: Exception, attempt: int) -> float:
    """Use the provider's stated delay when it gives one; else exponential."""
    match = re.search(
        r"try again in ([0-9.]+(?:h\d+m)?(?:m\d+(?:\.\d+)?s)?(?:\d+(?:\.\d+)?s)?)",
        str(exc),
    )
    if match:
        try:
            return float(match.group(1)) + 0.5
        except ValueError:
            pass
    return min(2.0 * (2 ** attempt), 20.0)


def _is_budget_error(exc: Exception) -> bool:
    """Only budget exhaustion is worth retrying; a bad prompt is not."""
    text = f"{type(exc).__name__}: {exc}".lower()
    return "max completion tokens" in text or "json_validate_failed" in text


def parse_json(text: str) -> dict:
    """Tolerant JSON extraction.

    Models wrap JSON in prose or fences even when told not to. Falling back to
    a regex keeps a whole heal alive over a formatting quirk — but a genuine
    malformed response still raises, because silently returning {} would make
    the next step invent a patch out of nothing.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{.*\}", text, re.S)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"model did not return JSON: {text[:200]}")


class _null_span:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def render(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)