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
from patient.config import llm_configured, llm_settings
from patient.scripted import ScriptedLLM
from patient.tracing import Recorder

LLMMode = Literal["scripted", "real"]

DEFAULT_MODE: LLMMode = "scripted"


def build_llm(config: dict, mode: LLMMode = DEFAULT_MODE):
    """Real client when asked and available, deterministic one otherwise."""
    if mode == "real":
        if not llm_configured():
            raise RuntimeError(
                "--llm real needs LLM_BASE_URL, LLM_API_KEY and LLM_MODEL in .env "
                "(see .env.example). Bedrock: point LLM_BASE_URL at "
                "https://bedrock-runtime.<region>.amazonaws.com/openai/v1"
            )
        from openai import OpenAI

        s = llm_settings()
        return OpenAI(api_key=s["api_key"], base_url=s["base_url"])
    return ScriptedLLM(config=config)


def run_once(
    question: str,
    recorder: Recorder,
    config: dict,
    on_step: Callable[[Step], None] | None = None,
    mode: LLMMode = DEFAULT_MODE,
) -> RunResult:
    agent = PatientAgent(config, llm=build_llm(config, mode), on_step=on_step)
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