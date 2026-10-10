"""One entry point for running the patient, for every caller.

The LLM mode is explicit, never inferred, because the honest answer to "was
this run scripted or real?" has to be a fact rather than a guess:

  mode="scripted" (default) -> patient/scripted.py, deterministic, offline.
                               Reproducible; the backbone of tests and the
                               backup demo.
  mode="real"               -> the OpenAI-compatible client from env
                               (LLM_BASE_URL / LLM_API_KEY / LLM_MODEL), which
                               covers Bedrock, OpenRouter, NaraRouter and
                               OpenAI by changing one variable.

Medic's own diagnose/surgeon steps ALWAYS use the real LLM — a scripted model
diagnosing a scripted patient would be grading its own homework. Only the
patient may be scripted, and only when asked.
"""
from __future__ import annotations

from typing import Callable, Literal

from patient.agent import PatientAgent, RunResult, Step
from patient.scripted import ScriptedLLM
from patient.tracing import Recorder

LLMMode = Literal["scripted", "real"]

DEFAULT_MODE: LLMMode = "scripted"


def build_llm(config: dict, mode: LLMMode = DEFAULT_MODE):
    """Real client when asked and available, deterministic one otherwise."""
    if mode == "real":
        # Same provider chain Medic itself uses, so the patient and the
        # diagnosis can never come from two different providers by accident.
        from medic.providers import build_client

        client, provider = build_client(role="patient")
        print(f"[medic] patient llm: {provider.label()}")
        return client
    return ScriptedLLM(config=config)


def run_once(
    question: str,
    recorder: Recorder,
    config: dict,
    on_step: Callable[[Step], None] | None = None,
    mode: LLMMode = DEFAULT_MODE,
    max_steps: int | None = None,
) -> RunResult:
    """Run the patient once.

    The LLM client is wrapped so every request passes the provider's rate
    limiter. The patient loop is the BURSTEST part of a heal - a looping agent
    can issue a dozen calls in seconds - so throttling only the diagnose and
    surgeon calls would leave the worst case unprotected.
    """
    client = build_llm(config, mode)
    if mode == "real":
        client = _throttled(client)
    agent = PatientAgent(config, llm=client, on_step=on_step,
                         max_steps_override=max_steps)
    return agent.run(question, recorder)


def _throttled(client):
    """Wrap chat.completions.create with the provider's rate limit."""
    from medic import providers as prov
    from medic.ratelimit import limiter_for

    try:
        _, provider = prov.build_client()
        limiter = limiter_for(provider.name)
    except Exception:
        return client

    original = client.chat.completions.create

    def create(*args, **kwargs):
        limiter.acquire()
        return original(*args, **kwargs)

    client.chat.completions.create = create
    return client


def measured(result, recorder: Recorder) -> dict:
    """Measured numbers only. Nothing here is estimated except est_cost_usd,
    which is derived from counted tokens and a documented rate table."""
    metrics = recorder.metrics()
    return {
        "run_id": result.run_id,
        "passed_answer": bool(result.answer.strip()),
        "steps": len(result.steps),
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.prompt_tokens + result.completion_tokens,
        "spans": metrics["spans"],
        "errors": metrics["errors"],
        "latency_ms": metrics["latency_ms"],
        "est_cost_usd": recorder.est_cost_usd(),
        "stopped_because": result.stopped_because,
        "error": result.error,
    }