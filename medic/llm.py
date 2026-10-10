"""The ONE LLM call Medic makes, for diagnose and surgeon.

Always the real model. A scripted model diagnosing a scripted patient would be
grading its own homework, so there is deliberately no scripted fallback here:
if credentials are missing, these steps fail loudly rather than pretending.

Every call is traced to neatlogs under workflow_name="medic" so the judge's
dashboard shows the patient run and the repair run side by side.
"""
from __future__ import annotations

import json
import re
from typing import Any

from patient.config import llm_configured, llm_settings
from patient.tracing import init_neatlogs, neatlogs_active


class MedicLLMUnavailable(RuntimeError):
    pass


def _client():
    if not llm_configured():
        raise MedicLLMUnavailable(
            "Medic's diagnose and surgeon steps require a real model: set "
            "LLM_BASE_URL, LLM_API_KEY and LLM_MODEL in .env. There is no scripted "
            "fallback by design — a model that diagnoses the agent would be "
            "grading its own work."
        )
    from openai import OpenAI

    s = llm_settings()
    client = OpenAI(api_key=s["api_key"], base_url=s["base_url"])
    try:
        import neatlogs

        if neatlogs_active():
            client = neatlogs.wrap(client)
    except Exception:
        pass
    return client


def ensure_traced() -> None:
    init_neatlogs("medic", tags=["medic-repair"])


def ask_json(
    system: str,
    user: str,
    recorder=None,
    span_name: str = "medic_llm",
    max_tokens: int = 1200,
) -> tuple[dict, dict]:
    """Returns (parsed_json, usage_metrics). Usage is measured, never guessed."""
    client = _client()
    s = llm_settings()
    ensure_traced()

    span_cm = (
        recorder.span("LLM", span_name, {"system": system[:200], "user": user[:400]})
        if recorder
        else _null_span()
    )
    with span_cm as span:
        resp = client.chat.completions.create(
            model=s["model"],
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        p_tok = getattr(usage, "prompt_tokens", 0) or 0
        c_tok = getattr(usage, "completion_tokens", 0) or 0
        if span is not None:
            span["prompt_tokens"] = p_tok
            span["completion_tokens"] = c_tok
            span["total_tokens"] = p_tok + c_tok
            span["output"] = content[:2000]

    metrics = {
        "model": s["model"],
        "prompt_tokens": p_tok,
        "completion_tokens": c_tok,
        "total_tokens": p_tok + c_tok,
    }
    return parse_json(content), metrics


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