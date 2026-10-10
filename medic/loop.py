"""The heal loop: reproduce -> diagnose -> patch -> verify, up to 3 attempts.

Each FAILED attempt feeds the new trace plus the failing check back into
diagnose, so attempt 2 knows what attempt 1 tried and why it did not work.

A heal counts only when the train task AND every held-out task pass. Stopping
on the train task alone is how a self-healing tool learns to overfit.

The patch is applied to a COPY and written to medic.yaml only after verification
passes (or when the caller passes apply_patch=True). A rejected or failing patch
never becomes the new baseline — a config that is still broken is not progress,
and carrying it forward makes the next attempt diagnose the wrong thing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

import yaml

from bugs.inject import MEDIC_YAML, apply_bug, current_config, reset_bug
from checks.checks import run_checks
from medic import diagnose as diag_mod
from medic import surgeon as surg_mod
from medic.runner import measured, run_once
from medic.trace_source import Trace, load_trace
from medic.verify import VerifyResult, verify
from patient.tracing import new_run
from tasks.loader import train_task_for

LLMMode = Literal["scripted", "real"]
MAX_ATTEMPTS = 3


@dataclass
class Attempt:
    number: int
    diagnosis: dict | None = None
    patch: dict | None = None
    diff: str | None = None
    verify: dict | None = None
    refused: str | None = None
    error: str | None = None
    llm_metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "attempt": self.number,
            "diagnosis": self.diagnosis,
            "patch": self.patch,
            "refused": self.refused,
            "error": self.error,
            "llm": self.llm_metrics,
            "verify": self.verify,
        }


@dataclass
class HealResult:
    bug: str
    healed: bool
    attempts: list[Attempt] = field(default_factory=list)
    baseline: dict | None = None
    final: dict | None = None
    trace_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "bug": self.bug,
            "healed": self.healed,
            "attempts": [a.to_dict() for a in self.attempts],
            "trace_id": self.trace_id,
        }


def _write(config: dict) -> None:
    MEDIC_YAML.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))


def _reproduce(bug: str, config: dict, mode: LLMMode):
    task = train_task_for(bug)
    if task is None:
        raise ValueError(f"no train task for bug {bug}")
    recorder = new_run("patient-agent", tags=[f"bug={bug}", "phase=before", f"llm={mode}"])
    result = run_once(task["question"], recorder, config, mode=mode)
    recorder.write({"result": result.to_dict(), "bug": bug, "task_id": task["id"],
                    "split": "train", "llm_mode": mode, "phase": "before"})
    return recorder.run_id, result, run_checks(bug, task, result), measured(result, recorder)


def heal(
    bug: str | None = None,
    trace_id: str | None = None,
    apply_patch: bool = False,
    console=None,
    mode: LLMMode = "scripted",
    max_attempts: int = MAX_ATTEMPTS,
    on_event: Callable[[str, dict], None] | None = None,
) -> HealResult:
    def emit(event: str, payload: dict) -> None:
        if on_event:
            on_event(event, payload)

    if bug is None:
        raise ValueError(
            "pass --bug: a bare trace id cannot be verified without knowing which "
            "hard check applies to it"
        )

    reset_bug(bug)
    config = apply_bug(bug, write=False)

    emit("header", {"bug": bug, "mode": mode})

    tid, result, verdict, metrics = _reproduce(bug, config, mode)
    emit("before_run", {"trace_id": tid, "verdict": verdict.to_dict(), "metrics": metrics})

    if verdict.passed:
        # Nothing to heal. Say so rather than inventing a patch.
        emit("already_green", {"metrics": metrics})
        return HealResult(bug=bug, healed=True, baseline=metrics, trace_id=tid)

    out = HealResult(bug=bug, healed=False, baseline=metrics, trace_id=tid)

    for attempt_no in range(1, max_attempts + 1):
        emit("attempt_start", {"attempt": attempt_no})
        att = Attempt(number=attempt_no)

        trace: Trace | None = load_trace(trace_id or tid)
        if trace is None:
            att.error = "could not load the failing trace"
            out.attempts.append(att)
            emit("attempt_end", {"attempt": att})
            break

        # ── diagnose ──
        try:
            diag, usage = diag_mod.diagnose(trace, verdict, config)
            att.diagnosis = diag.to_dict()
            att.llm_metrics = usage
            emit("diagnosis", {"attempt": attempt_no, "diagnosis": diag.to_dict()})
        except Exception as exc:
            att.error = f"diagnose failed: {type(exc).__name__}: {exc}"
            out.attempts.append(att)
            emit("attempt_end", {"attempt": att})
            # Surface WHY. A "needs a human" verdict that actually means
            # "the API key is missing" wastes demo time and hides a blocker.
            emit("fatal", {"reason": att.error, "attempts": out.attempts})
            break

        # ── patch ──
        try:
            patch, _ = surg_mod.propose(diag, config, verdict)
            att.patch = {"field": patch.field, "new_value": patch.new_value,
                         "rationale": patch.rationale}
        except Exception as exc:
            # Real LLM refused or misfired: fall back to the deterministic fix
            # so the demo still heals, but SAY that is what happened.
            fallback = surg_mod.deterministic_patch(diag.failure_type, config)
            if fallback is None:
                att.refused = f"surgeon refused and no deterministic fix: {exc}"
                out.attempts.append(att)
                emit("attempt_end", {"attempt": att})
                break
            att.refused = f"LLM patch unavailable ({type(exc).__name__}); used deterministic fix"
            att.patch = {"field": fallback.field, "new_value": fallback.new_value,
                         "rationale": fallback.rationale}
            patch = fallback
            emit("fallback", {"attempt": attempt_no, "reason": att.refused})

        patched = surg_mod.apply_patch(config, patch)
        att.diff = surg_mod.diff(config, patched)
        emit("diff", {"attempt": attempt_no, "diff": att.diff, "patch": att.patch})

        # ── verify (train + held-out) ──
        vr: VerifyResult = verify(bug, patched, mode=mode, attempt=attempt_no)
        att.verify = vr.to_dict()
        emit("verify", {"attempt": attempt_no, "verify": vr.to_dict()})
        out.attempts.append(att)

        if vr.all_passed:
            config = patched
            if apply_patch:
                _write(config)
            out.healed = True
            out.final = config
            emit("healed", {"attempt": attempt_no, "config": config})
            break

        # Carry the patched config forward ONLY if the train task improved;
        # otherwise keep diagnosing the original failure.
        if vr.train and vr.train.passed:
            config = patched

        # Re-reproduce so the next diagnose sees the CURRENT failure.
        tid, result, verdict, metrics = _reproduce(bug, config, mode)
        out.trace_id = tid
        emit("retry_reproduce", {"attempt": attempt_no, "verdict": verdict.to_dict(),
                                 "metrics": metrics})

    if not out.healed:
        _write(current_config())  # leave medic.yaml clean if nothing healed
    out.final = out.final or config
    return out