"""HARD CHECKS. No LLM is consulted, ever.

"Green" means these pass. An LLM's opinion is never the verdict — that is the
entire product claim, so a check that asks a model whether it did well would
destroy it.

Each check returns a Verdict with a machine-readable `failure_type` that feeds
Medic's diagnosis, plus a human `reason`. Both matter: the LLM reads the reason,
the loop branches on the type.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import jsonschema

from patient.tools import TOOL_SCHEMAS, cited_urls_in

VALID_TOOLS = set(TOOL_SCHEMAS)


@dataclass
class Verdict:
    passed: bool
    reason: str = ""
    details: list[str] = field(default_factory=list)
    failure_type: str | None = None
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "details": self.details,
            "failure_type": self.failure_type,
            "metrics": self.metrics,
        }


# ── shared primitives ────────────────────────────────────────────────────

def _numbers_in(text: str) -> set[float]:
    """Numbers in an answer, normalised. $28,250.00 and 28250 both -> 28250.0."""
    out: set[float] = set()
    for raw in re.findall(r"-?\$?[\d,]*\.?\d+", text or ""):
        cleaned = raw.replace("$", "").replace(",", "").strip()
        if not cleaned or cleaned in {"-", "."}:
            continue
        try:
            out.add(round(float(cleaned), 2))
        except ValueError:
            continue
    return out


def _schema_violations(result) -> list[str]:
    """Validate EVERY tool call against its JSON schema.

    This is the deterministic half of bug 1: a prose argument to calculator is
    a schema violation whether or not the model later apologises for it.
    """
    problems: list[str] = []
    for step in result.steps:
        schema = TOOL_SCHEMAS.get(step.tool_name)
        if schema is None:
            problems.append(f"unknown tool called: {step.tool_name}")
            continue
        try:
            jsonschema.validate(step.args, schema)
        except jsonschema.ValidationError as exc:
            where = "/".join(str(p) for p in exc.absolute_path) or "(root)"
            problems.append(
                f"step {step.index} {step.tool_name}: {where}: {exc.message}"
            )
    return problems


def _fetched_urls(result) -> set[str]:
    """URLs actually returned by a SUCCESSFUL fetch_page in this run."""
    urls: set[str] = set()
    for step in result.steps:
        if step.tool_name == "fetch_page" and not step.error:
            payload = step.output if isinstance(step.output, dict) else {}
            if payload.get("found"):
                urls.add(str(payload.get("url", "")).rstrip("/"))
    return urls


# ── per-bug checks ───────────────────────────────────────────────────────

def check_wrong_args(task: dict, result) -> Verdict:
    """Every tool call schema-valid AND the final answer is the known value."""
    metrics = {"steps": len(result.steps), "tool_calls": len(result.steps)}

    violations = _schema_violations(result)
    if violations:
        return Verdict(
            passed=False,
            reason=f"{len(violations)} tool call(s) did not match their JSON schema",
            details=violations,
            failure_type="wrong_args",
            metrics=metrics,
        )

    expected = float(task["expected_answer"])
    got = _numbers_in(result.answer)
    if not result.answer.strip():
        return Verdict(
            passed=False,
            reason="run produced no final answer",
            details=["the agent stopped without answering"],
            failure_type="wrong_args",
            metrics=metrics,
        )
    if round(expected, 2) not in got:
        return Verdict(
            passed=False,
            reason=f"final answer does not contain the known value {expected:,.2f}",
            details=[f"answer was: {result.answer[:200]}"],
            failure_type="wrong_args",
            metrics=metrics,
        )

    return Verdict(
        passed=True,
        reason=f"all {len(result.steps)} tool calls schema-valid and answer == {expected:,.2f}",
        metrics={**metrics, "expected": expected},
    )


def check_parse_error(task: dict, result) -> Verdict:
    """No unhandled parse exception escaped, and the answer is still right."""
    metrics = {"steps": len(result.steps), "tool_calls": len(result.steps)}

    escaped = (result.error or "")
    if escaped and result.stopped_because == "parse_error":
        return Verdict(
            passed=False,
            reason=f"run ended on an unhandled parse error: {escaped}",
            details=[
                "no retry was attempted (retry_on_parse_error is false)",
                "a tool returned unparseable JSON and the agent had no recovery path",
            ],
            failure_type="parse_error",
            metrics=metrics,
        )

    expected = float(task["expected_answer"])
    got = _numbers_in(result.answer)
    if round(expected, 2) not in got:
        return Verdict(
            passed=False,
            reason=f"run did not recover to the known value {expected:,.2f}",
            details=[f"answer was: {(result.answer or '(none)')[:200]}"],
            failure_type="parse_error",
            metrics=metrics,
        )

    return Verdict(
        passed=True,
        reason=f"survived the malformed payload and still answered {expected:,.2f}",
        metrics={**metrics, "expected": expected, "recovered": bool(escaped)},
    )


def _called_with_bad_args(result) -> bool:
    """Did any tool call pass prose where an expression was required?

    Evidence for the diagnosis, not a gate: a wrong number plus a prose argument
    points squarely at the tool DESCRIPTION rather than at anything else in the
    config, which is the difference between a one-line fix and a guess.
    """
    import re

    for step in getattr(result, "steps", []) or []:
        args = (getattr(step, "arguments", None) or {})
        expr = str(args.get("expression", "")).strip()
        if expr and not re.fullmatch(r"[0-9eE+\-*/().,%\s]+", expr):
            return True
    return False


def check_loop(task: dict, result) -> Verdict:
    """Finishes within max_steps_allowed WITH a final answer."""
    limit = int(task["max_steps_allowed"])
    metrics = {
        "steps": len(result.steps),
        "max_steps_allowed": limit,
        "total_tokens": result.prompt_tokens + result.completion_tokens,
        "stopped_because": result.stopped_because,
    }

    # Hitting the TOKEN ceiling is the same failure as blowing the step limit:
    # the agent is still searching and has not finished. It must be reported as
    # the loop it is, with its own reason, because "used N steps" would be a
    # misreading when the guard that fired was the cost one.
    if result.stopped_because == "token_ceiling":
        used = result.prompt_tokens + result.completion_tokens
        return Verdict(
            passed=False,
            reason=(
                f"burned {used:,} tokens across {len(result.steps)} steps and "
                f"still had not finished - stopped by the token ceiling, not by "
                f"finishing"
            ),
            details=[
                f"step limit {limit}, token ceiling hit at {used:,}",
                "an agent that has not answered after this much spend is not going to",
            ],
            failure_type="loop",
            metrics=metrics,
        )

    if not result.answer.strip():
        # An empty response is a DIFFERENT fault from a loop, and calling it
        # "never produced a final answer" hides the cause. The loop check is
        # the one that runs on this task, so it has to name what happened.
        if result.stopped_because == "empty_response":
            return Verdict(
                passed=False,
                reason="the model returned neither content nor a tool call",
                details=[
                    "observed on openrouter/openai/gpt-oss-20b on turn 2",
                    "this is not a looping agent - the run ended immediately",
                ],
                failure_type="other",
                metrics=metrics,
            )
        return Verdict(
            passed=False,
            reason="agent never produced a final answer",
            details=[f"stopped because: {result.stopped_because}"],
            failure_type="loop",
            metrics=metrics,
        )
    if len(result.steps) > limit:
        return Verdict(
            passed=False,
            reason=f"used {len(result.steps)} steps, over the limit of {limit}",
            details=[f"stopped because: {result.stopped_because}"],
            failure_type="loop",
            metrics=metrics,
        )

    expected = float(task["expected_answer"])
    if round(expected, 2) not in _numbers_in(result.answer):
        # NOT a loop. The agent finished inside its budget and produced a wrong
        # number, which is the wrong_args fault. Labelling this "loop" would
        # send Medic to patch max_steps or add a stop rule — a confident fix to
        # a problem that was never there, on a run that would then still fail.
        #
        # The loop check runs on this task, so it has to name the real cause.
        tool_bad = _called_with_bad_args(result)
        return Verdict(
            passed=False,
            reason=(
                f"finished in {len(result.steps)} steps (under the limit of "
                f"{limit}) but answered wrong ({expected:,.2f} expected)"
            ),
            details=[
                f"answer was: {result.answer[:200]}",
                "this is not a runaway — the agent stopped on its own",
                "a wrong number from a bounded run is a wrong-args fault"
                + ("; a tool was called with a non-expression argument" if tool_bad else ""),
            ],
            failure_type="wrong_args",
            metrics=metrics,
        )

    return Verdict(
        passed=True,
        reason=f"answered in {len(result.steps)} steps (limit {limit})",
        metrics={**metrics, "expected": expected},
    )


def check_hallucinated_citation(task: dict, result) -> Verdict:
    """Every cited URL must appear in a fetch_page result FROM THIS RUN."""
    metrics = {"steps": len(result.steps)}

    cited = cited_urls_in(result.answer or "")
    fetched = _fetched_urls(result)
    metrics["cited"] = len(cited)
    metrics["fetched"] = len(fetched)

    invented = sorted(cited - fetched)
    if invented:
        return Verdict(
            passed=False,
            reason=f"{len(invented)} cited URL(s) were never fetched",
            details=[f"cited but not fetched: {u}" for u in invented],
            failure_type="hallucinated_citation",
            metrics=metrics,
        )

    return Verdict(
        passed=True,
        reason=f"all {len(cited)} cited URL(s) came from fetch_page in this run",
        metrics=metrics,
    )


CHECKS = {
    "wrong_args": check_wrong_args,
    "parse_error": check_parse_error,
    "loop": check_loop,
    "hallucinated_citation": check_hallucinated_citation,
}


def run_checks(bug: str, task: dict, result) -> Verdict:
    fn = CHECKS.get(bug)
    if fn is None:
        return Verdict(passed=False, reason=f"no check implemented for bug {bug!r}")
    try:
        return fn(task, result)
    except Exception as exc:  # a broken check must not read as a green run
        return Verdict(
            passed=False,
            reason=f"the CHECK ITSELF raised {type(exc).__name__}: {exc}",
            failure_type="other",
        )


def to_json(verdict: Verdict) -> str:
    return json.dumps(verdict.to_dict(), indent=2)