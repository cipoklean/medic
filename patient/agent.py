"""The patient agent — a small tool-calling loop.

Everything it is allowed to change lives in medic.yaml. There is no other
knob: no prompt constants here, no step cap here, no retry policy here. If a
bug lives in behaviour, its fix must live in that file or it is not fixable by
Medic — which is the point.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import yaml

from .config import ROOT, llm_settings
from .tools import dispatch, tool_definitions

MEDIC_YAML = ROOT / "medic.yaml"


def load_config(path=None) -> dict:
    with open(path or MEDIC_YAML) as fh:
        return yaml.safe_load(fh) or {}


@dataclass
class Step:
    index: int
    tool_name: str
    args: dict
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class RunResult:
    run_id: str
    question: str
    answer: str = ""
    steps: list[Step] = field(default_factory=list)
    stopped_because: str = "final_answer"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    trace_path: str = ""
    neatlogs_active: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "question": self.question,
            "answer": self.answer,
            "steps": [s.__dict__ for s in self.steps],
            "stopped_because": self.stopped_because,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "trace_path": self.trace_path,
            "neatlogs_active": self.neatlogs_active,
            "error": self.error,
        }


class PatientAgent:
    def __init__(self, config: dict, llm=None, on_step: Callable[[Step], None] | None = None,
                 max_steps_override: int | None = None,
                 token_ceiling: int | None = None):
        self.config = config
        self.max_steps = max_steps_override or int(config.get("max_steps", 8))
        # A per-run cost guard, SEPARATE from max_steps. A step ceiling alone let
        # a laguna run burn 180,000 tokens inside 40 steps - expensive, and a
        # probe that runs ten minutes before it reports anything at all.
        # MEDIC_TOKEN_CEILING (default 30000) bounds what a probe can cost.
        # Hitting it still proves the runaway: an agent that has not finished
        # after 30k tokens is not going to.
        self.token_ceiling = token_ceiling or int(
            os.environ.get("MEDIC_TOKEN_CEILING", "30000")
        )
        self.retry_on_parse_error = bool(config.get("retry_on_parse_error", False))
        self.descriptions = {
            name: (spec or {}).get("description", "")
            for name, spec in (config.get("tools") or {}).items()
        }
        self._llm = llm
        self.on_step = on_step

    # ── the LLM seam ────────────────────────────────────────────────────
    def _model_name(self) -> str:
        """Which model are we actually calling?

        Read from the resolved provider rather than from llm_settings(), so a
        fallback chain cannot leave the agent asking provider A for a model name
        that belongs to provider B.
        """
        from medic.providers import build_client

        try:
            _, provider = build_client()
            return provider.model
        except Exception:
            return llm_settings()["model"]

    def _max_tokens(self) -> int:
        """Cap the per-call completion budget so a run stays affordable.

        MEDIC_MAX_TOKENS (default 16384) — measured safe on OpenRouter: unset,
        OpenRouter reserves 65,536 and rejects on insufficient credit; 16,384
        runs fine and costs $0.000021 per small call.
        """
        try:
            return int(os.environ.get("MEDIC_MAX_TOKENS", "16384"))
        except ValueError:
            return 16384

    def _provider_routing(self) -> dict | None:
        """Upstream pinning, when the resolved provider configures it.

        Without this the patient ignores LLM_ROUTE_* entirely, so a run could
        be measured on the wrong upstream while the routing header says
        otherwise.
        """
        try:
            from medic.providers import build_client

            _, provider = build_client()
            return provider.routing()
        except Exception:
            return None

    def _client(self):
        """An injected client wins; otherwise build a real one.

        Bedrock's OpenAI-compatible endpoint is reachable with the same client
        by pointing base_url at bedrock-runtime.<region>.amazonaws.com/openai/v1.
        """
        if self._llm is not None:
            return self._llm
        from openai import OpenAI

        s = llm_settings()
        if not (s["api_key"] and s["base_url"] and s["model"]):
            raise RuntimeError(
                "LLM_BASE_URL / LLM_API_KEY / LLM_MODEL must be set in .env "
                "(see .env.example), or inject a client for an offline run."
            )
        return OpenAI(api_key=s["api_key"], base_url=s["base_url"])

    def _wrap(self, client):
        """neatlogs.wrap if available — makes every LLM call a span for free."""
        try:
            import neatlogs

            from .tracing import neatlogs_active

            if neatlogs_active():
                return neatlogs.wrap(client)
        except Exception:
            pass
        return client

    # ── main loop ───────────────────────────────────────────────────────
    def run(self, question: str, recorder) -> RunResult:
        from .tracing import neatlogs_active

        client = self._wrap(self._client())
        result = RunResult(run_id=recorder.run_id, question=question)
        messages: list[dict] = [
            {"role": "system", "content": self.config.get("system_prompt", "")},
            {"role": "user", "content": question},
        ]
        tools = tool_definitions(self.descriptions)
        model = self._model_name()

        empty_retries = 0
        with recorder.span("WORKFLOW", "patient_run", question):
            while True:
                # Two independent ceilings. A step ceiling alone lets a cheap
                # model burn 180,000 tokens inside 40 steps, which is both a
                # money problem and a way for a probe to run for ten minutes
                # before it tells you anything. MEDIC_TOKEN_CEILING makes the
                # cost of a probe bounded and predictable, and stopping there
                # still proves the runaway: an agent that has not finished
                # after 30,000 tokens is not going to.
                used = result.prompt_tokens + result.completion_tokens
                if len(result.steps) >= self.max_steps:
                    result.stopped_because = "max_steps"
                    result.answer = (
                        "I could not complete this within my step budget."
                    )
                    break
                if used >= self.token_ceiling:
                    result.stopped_because = "token_ceiling"
                    result.answer = (
                        "I could not complete this within my token budget."
                    )
                    recorder.span("GUARD", "token_ceiling_stop", {
                        "tokens_used": used,
                        "ceiling": self.token_ceiling,
                        "steps": len(result.steps),
                    })
                    break

                with recorder.span("LLM", f"llm_call_{len(result.steps) + 1}",
                                   {"messages": len(messages)}) as llm_span:
                    routing = self._provider_routing()
                    resp = client.chat.completions.create(
                        model=model,
                        # Providers that bill against the model's advertised
                        # max_completion_tokens reject a request that reserves
                        # more than the account can afford: OpenRouter returned
                        # 402 'requested up to 65536 tokens, can only afford
                        # 22685' when max_tokens was left unset. Capping it
                        # keeps a run affordable; the agent never needed more.
                        max_tokens=self._max_tokens(),
                        **({"extra_body": {"provider": routing}} if routing else {}),
                        messages=messages,
                        tools=tools,
                        temperature=0,
                        seed=7,
                    )
                    usage = getattr(resp, "usage", None)
                    p_tok = getattr(usage, "prompt_tokens", 0) or 0
                    c_tok = getattr(usage, "completion_tokens", 0) or 0
                    llm_span["prompt_tokens"] = p_tok
                    llm_span["completion_tokens"] = c_tok
                    llm_span["total_tokens"] = p_tok + c_tok
                    llm_span["output"] = resp.choices[0].message.model_dump()
                    result.prompt_tokens += p_tok
                    result.completion_tokens += c_tok

                msg = resp.choices[0].message
                messages.append(msg.model_dump(exclude_none=True))

                if not msg.tool_calls:
                    # An empty response is not an answer. Observed on
                    # openrouter/openai/gpt-oss-20b: turn 2 returned neither
                    # content nor tool calls, and recording that as
                    # stopped_because=final_answer with answer="" made a real
                    # model failure look like a legitimate (empty) conclusion.
                    # It is now distinguished, so the check that catches it
                    # reports the true cause.
                    result.answer = msg.content or ""
                    if not result.answer.strip():
                        # Observed on openrouter/openai/gpt-oss-20b: a turn with
                        # no content and no tool call. One retry recovers it, and
                        # a demo should not hinge on a one-off model quirk.
                        if empty_retries < 1 and len(result.steps) < self.max_steps:
                            empty_retries += 1
                            messages.append(
                                {"role": "user", "content":
                                 "Your last message was empty. Continue and give "
                                 "the final answer."}
                            )
                            continue
                        result.stopped_because = "empty_response"
                        result.error = (
                            "the model returned neither content nor a tool call"
                            + (f" (after {empty_retries} retry)" if empty_retries else "")
                        )
                    else:
                        result.stopped_because = "final_answer"
                    break

                for call in msg.tool_calls:
                    name = call.function.name
                    idx = len(result.steps) + 1
                    started = time.time()
                    step = Step(index=idx, tool_name=name, args={})
                    with recorder.span("TOOL", name, tool_name=name) as tool_span:
                        tool_span["input"] = {"name": name, "raw_arguments": call.function.arguments}
                        try:
                            step.args = json.loads(call.function.arguments or "{}")
                        except json.JSONDecodeError as exc:
                            step.error = f"tool arguments were not valid JSON: {exc}"
                            tool_span["error"] = step.error
                            if self.retry_on_parse_error:
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": (
                                            f"Your arguments for {name} were not valid JSON. "
                                            "Emit a single valid JSON object."
                                        ),
                                    }
                                )
                            else:
                                # The bug-2 failure mode: no recovery, no
                                # clarification — the run must not raise out.
                                result.error = step.error
                                result.stopped_because = "parse_error"
                                step.duration_ms = round((time.time() - started) * 1000, 2)
                                result.steps.append(step)
                                if self.on_step:
                                    self.on_step(step)
                                result.answer = ""
                                return result
                            step.duration_ms = round((time.time() - started) * 1000, 2)
                            result.steps.append(step)
                            if self.on_step:
                                self.on_step(step)
                            continue

                        tool_span["input"] = {"name": name, "args": step.args}
                        try:
                            step.output = dispatch(name, step.args)
                            # A tool that returns a string is claiming to be
                            # JSON. If the caller must parse it, it had better
                            # be parseable — this is where bug 2 surfaces.
                            if isinstance(step.output, str):
                                step.output = json.loads(step.output)
                            tool_span["output"] = step.output
                        except Exception as exc:
                            step.error = f"{type(exc).__name__}: {exc}"
                            tool_span["error"] = step.error
                            if not self.retry_on_parse_error:
                                result.error = step.error
                                result.stopped_because = "parse_error"
                                step.duration_ms = round((time.time() - started) * 1000, 2)
                                result.steps.append(step)
                                if self.on_step:
                                    self.on_step(step)
                                result.answer = ""
                                return result

                    step.duration_ms = round((time.time() - started) * 1000, 2)
                    result.steps.append(step)
                    if self.on_step:
                        self.on_step(step)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": json.dumps(step.output, default=str),
                        }
                    )

        result.neatlogs_active = neatlogs_active()
        return result


def run_patient(question: str, recorder, config: dict | None = None) -> RunResult:
    agent = PatientAgent(config or load_config())
    return agent.run(question, recorder)