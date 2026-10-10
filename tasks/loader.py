"""Task loading.

Tasks are a YAML multi-document stream; each doc is one task. `train.yaml` is the
single task a bug is diagnosed against; `heldout.yaml` holds the unseen ones.

The held-out tasks are loadable but must never be handed to diagnose/surgeon —
a fix that only works on the train task has overfitted, and overfitting is the
one failure mode this project cannot have.
"""
from __future__ import annotations

from typing import Iterator

import yaml

from patient.config import ROOT

TRAIN = ROOT / "tasks" / "train.yaml"
HELDOUT = ROOT / "tasks" / "heldout.yaml"

BUGS = ["wrong_args", "parse_error", "loop", "hallucinated_citation"]


def _load_all(path) -> list[dict]:
    with open(path) as fh:
        return [doc for doc in yaml.safe_load_all(fh) if doc]


def all_tasks() -> list[dict]:
    return _load_all(TRAIN) + _load_all(HELDOUT)


def tasks_for(bug: str, split: str = "train") -> list[dict]:
    path = TRAIN if split == "train" else HELDOUT
    return [t for t in _load_all(path) if t.get("bug") == bug]


def train_task_for(bug: str, preset: str | None = None) -> dict | None:
    """The train task for a bug.

    `preset` selects a strengthened VARIANT of the same bug: a task may carry
    `preset: loop_strong`, and it still runs the `loop` hard check. That keeps
    the variant a presentation choice rather than a new bug to justify.
    """
    found = tasks_for(bug, "train")
    if preset:
        for task in found:
            if task.get("preset") == preset:
                return task
    return found[0] if found else None


def heldout_for(bug: str) -> list[dict]:
    return tasks_for(bug, "heldout")


def validate() -> list[str]:
    """Structural check of both files. A malformed task file must fail loudly
    here rather than as a confusing hard-check failure three phases later."""
    problems: list[str] = []
    required = {"id", "bug", "question", "expected_answer", "max_steps_allowed"}
    seen: set[str] = set()

    for path, split in ((TRAIN, "train"), (HELDOUT, "heldout")):
        if not path.exists():
            problems.append(f"missing {split} file: {path}")
            continue
        for i, task in enumerate(_load_all(path), 1):
            missing = required - set(task)
            if missing:
                problems.append(f"{path.name} doc {i}: missing {sorted(missing)}")
                continue
            if task["bug"] not in BUGS:
                problems.append(f"{path.name} doc {i}: unknown bug {task['bug']!r}")
            if task["id"] in seen:
                problems.append(f"{path.name} doc {i}: duplicate id {task['id']!r}")
            seen.add(task["id"])
            if not isinstance(task["max_steps_allowed"], int):
                problems.append(f"{path.name} doc {i}: max_steps_allowed must be an int")

    for bug in BUGS:
        if not tasks_for(bug, "train"):
            problems.append(f"no TRAIN task for bug {bug}")
        if len(heldout_for(bug)) < 2:
            problems.append(
                f"bug {bug} has {len(heldout_for(bug))} held-out task(s); spec wants 2-3"
            )
    return problems


if __name__ == "__main__":
    issues = validate()
    if issues:
        for p in issues:
            print(f"PROBLEM: {p}")
        raise SystemExit(1)
    print(f"tasks OK: {len(all_tasks())} total")
    for bug in BUGS:
        print(f"  {bug}: 1 train, {len(heldout_for(bug))} held-out")