"""Diagnose: spans + the failing hard check -> a structured Diagnosis.

The LLM proposes; this module's job is to make the proposal VALID and BOUNDED.
A `failing_span_id` that does not exist in the trace is rejected rather than
passed downstream, because a diagnosis pointing at a span that is not there
sends the surgeon to edit the wrong field.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from medic import llm
from medic.trace_source import Trace

FailureType = Literal[
    "wrong_args", "parse_error", "loop", "hallucinated_citation", "other"
]

SYSTEM = """You are the diagnostic half of Medic, a self-healing agent tool.

You are given:
1. A compact span tree from the failing agent run (each span is
   [KIND] name, its args, its output, and any error).
2. The deterministic check that failed, with its machine failure_type and the
   human reason.
3. The agent's current configuration.

Identify the SINGLE span whose behaviour caused the failure and name the root
cause in the agent's CONFIGURATION, because that is the only thing Medic is
allowed to change. Never propose a code change.

Return ONLY a JSON object:
{
  "failing_span_id": "<span id from the tree, exactly as written>",
  "failure_type": "wrong_args|parse_error|loop|hallucinated_citation|other",
  "evidence": "<the exact span input/output that proves it, quoted>",
  "root_cause": "<one sentence: what in the config permits this behaviour>",
  "confidence": <number 0.0-1.0>
}

The failure_type must match the check's failure_type unless the check is
demonstrably wrong, in which case say so in evidence and use "other"."""


class Diagnosis(BaseModel):
    failing_span_id: str
    failure_type: FailureType
    evidence: str
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    def to_dict(self) -> dict:
        return self.model_dump()


def _prompt(trace: Trace, verdict, config: dict) -> str:
    return f"""FAILING RUN
run_id: {trace.run_id}
source: {trace.source}
question: {trace.result.get('question', '(unknown)')}

FAILING CHECK (deterministic, no LLM involved)
failure_type: {verdict.failure_type}
reason: {verdict.reason}
details:
{chr(10).join('- ' + d for d in verdict.details) or '- (none)'}

SPAN TREE
{trace.to_compact_tree()}

CURRENT CONFIG (the only thing Medic may change)
{llm.render(config)}
"""


def diagnose(trace: Trace, verdict, config: dict, recorder=None) -> tuple[Diagnosis, dict]:
    """Returns (diagnosis, measured_usage). Raises on a malformed proposal."""
    data, usage = llm.ask_json(
        SYSTEM, _prompt(trace, verdict, config), recorder, span_name="medic_diagnose"
    )
    diag = Diagnosis(**data)

    if trace.find(diag.failing_span_id) is None:
        # Keep the model's reasoning, but anchor it to a real span. An
        # invented id would send the surgeon to patch the wrong field.
        anchor = _anchor_span(trace, verdict)
        diag = diag.model_copy(update={"failing_span_id": anchor or diag.failing_span_id})

    return diag, usage


def _anchor_span(trace: Trace, verdict) -> str | None:
    """Pick the span the check is really about."""
    if verdict.failure_type == "parse_error":
        bad = trace.errors()
        if bad:
            return bad[0].span_id
    tools = trace.tool_spans()
    if tools:
        return tools[-1].span_id
    return trace.spans[-1].span_id if trace.spans else None