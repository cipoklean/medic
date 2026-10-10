"""Verify: re-run the train task, then every held-out task, under hard checks.

Held-out tasks are the whole point. A patch that fixes the train task and
nothing else has overfitted, and an overfitted "self-healing agent" is worse
than no product at all — it is a product that reports false confidence.

Metrics are MEASURED from the recorder: steps, spans, tokens, latency, cost.
Nothing here is estimated except `est_cost_usd`, which is counted tokens times a
documented rate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from checks.checks import Verdict, run_checks
from medic.runner import measured, run_once
from patient.tracing import Recorder, new_run
from tasks.loader import heldout_for, train_task_for

LLMMode = Literal["scripted", "real"]


@dataclass
class TaskOutcome:
    task_id: str
    split: str                 # "train" | "heldout"
    passed: bool
    reason: str
    failure_type: str | None
    steps: int
    total_tokens: int
    latency_ms: float
    trace_id: str
    error: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class VerifyResult:
    train: TaskOutcome | None = None
    heldout: list[TaskOutcome] = field(default_factory=list)

    @property
    def train_passed(self) -> bool:
        return bool(self.train and self.train.passed)

    @property
    def heldout_passed(self) -> bool:
        return bool(self.heldout) and all(o.passed for o in self.heldout)

    @property
    def all_passed(self) -> bool:
        """A heal is only real when the train task AND every held-out task pass."""
        return self.train_passed and self.heldout_passed

    def to_dict(self) -> dict:
        return {
            "train": self.train.to_dict() if self.train else None,
            "heldout": [o.to_dict() for o in self.heldout],
            "train_passed": self.train_passed,
            "heldout_passed": self.heldout_passed,
            "all_passed": self.all_passed,
        }


def _one(task: dict, split: str, config: dict, bug: str, mode: LLMMode, tag: str):
    recorder: Recorder = new_run(
        "patient-agent", tags=[f"bug={bug}", f"split={split}", f"llm={mode}", f"phase={tag}"]
    )
    result = run_once(task["question"], recorder, config, mode=mode)
    verdict: Verdict = run_checks(bug, task, result)
    recorder.write(
        {
            "result": result.to_dict(),
            "bug": bug,
            "task_id": task["id"],
            "split": split,
            "llm_mode": mode,
            "phase": tag,
            "check": verdict.to_dict(),
        }
    )
    m = measured(result, recorder)
    return TaskOutcome(
        task_id=task["id"],
        split=split,
        passed=verdict.passed,
        reason=verdict.reason,
        failure_type=verdict.failure_type,
        steps=m["steps"],
        total_tokens=m["total_tokens"],
        latency_ms=m["latency_ms"],
        trace_id=recorder.run_id,
        error=result.error,
    )


def verify(
    bug: str,
    config: dict,
    mode: LLMMode = "scripted",
    attempt: int = 1,
    include_heldout: bool = True,
) -> VerifyResult:
    out = VerifyResult()

    train = train_task_for(bug)
    if train is None:
        raise ValueError(f"no train task for bug {bug}")
    out.train = _one(train, "train", config, bug, mode, f"verify-a{attempt}")

    if include_heldout:
        for task in heldout_for(bug):
            out.heldout.append(_one(task, "heldout", config, bug, mode, f"verify-a{attempt}"))
    return out