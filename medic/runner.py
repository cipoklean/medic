"""Run the patient agent once, under a given config, and record everything.

One entry point for every caller — cli.py run, verify.py, and the bug-2
recovery probe — so a number reported in one place is produced the same way
everywhere else.
"""
from __future__ import annotations

from typing import Callable

from patient.agent import PatientAgent
from patient.config import llm_configured
from patient.scripted import ScriptedLLM
from patient.tracing import Recorder


def build_llm(config: dict):
    """Real client when credentials exist, deterministic scripted one otherwise.

    The scripted client is given the SAME config the agent gets, so it behaves
    the way that configuration tells it to behave — the offline run is a real
    run of a literal agent, not a canned answer.
    """
    if llm_configured():
        from openai import OpenAI

        from patient.config import llm_settings

        s = llm_settings()
        return OpenAI(api_key=s["api_key"], base_url=s["base_url"])
    return ScriptedLLM(config=config)


def run_once(
    question: str,
    recorder: Recorder,
    config: dict,
    on_step: Callable[[object], None] | None = None,
) -> object:
    agent = PatientAgent(config, llm=build_llm(config), on_step=on_step)
    return agent.run(question, recorder)


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