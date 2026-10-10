"""Verify every task passes on the CLEAN baseline, and fails when its bug is on.

Two directions matter and both are checked here:

  * clean config -> every train AND held-out task PASSES
  * injected bug -> its train task FAILS

A bug harness that only proves failures is half a harness. If clean does not
pass, "the bug caused it" is unproven and every number in the report is noise.

Run: .venv/bin/python -m tests.test_tasks
"""
from __future__ import annotations

import sys

from bugs.inject import apply_bug, clean_config, reset_bug
from checks.checks import run_checks
from medic.runner import run_once
from patient import tracing
from patient.agent import RunResult
from tasks.loader import BUGS, all_tasks, heldout_for, train_task_for


def _run(task: dict, config: dict, tag: str) -> tuple[RunResult, object]:
    recorder = tracing.new_run("patient-agent", tags=[tag])
    result = run_once(task["question"], recorder, config)
    recorder.write({"result": result.to_dict(), "task_id": task["id"], "tag": tag})
    return result, run_checks(task["bug"], task, result)


def check_clean_passes() -> list[str]:
    """Every task on the clean baseline must pass. Any failure here means the
    fixture/task/expectation set is inconsistent, not that a bug works."""
    config = clean_config()
    problems: list[str] = []
    for task in all_tasks():
        result, verdict = _run(task, config, "clean")
        if not verdict.passed:
            problems.append(
                f"CLEAN FAILED {task['id']} [{task['bug']}]: {verdict.reason}"
            )
    return problems


def check_bugs_fail() -> list[str]:
    """Each injected bug must FAIL its train task, with the right failure_type."""
    problems: list[str] = []
    for bug in BUGS:
        reset_bug(bug)
        config = apply_bug(bug)
        task = train_task_for(bug)
        if task is None:
            problems.append(f"{bug}: no train task")
            continue
        result, verdict = _run(task, config, f"bug={bug}")
        if verdict.passed:
            problems.append(f"{bug}: train task PASSED but should have failed")
        elif verdict.failure_type != bug:
            problems.append(
                f"{bug}: failed with the wrong type {verdict.failure_type!r}"
            )
    reset_bug()
    return problems


def check_determinism(times: int = 2) -> list[str]:
    """The same config must produce the same run every time — the definition
    of done says 'twice in a row', so it is worth enforcing mechanically."""
    problems: list[str] = []
    config = clean_config()
    task = train_task_for("loop")
    if task is None:
        return ["determinism: no loop train task"]
    signatures = set()
    for _ in range(times):
        result, verdict = _run(task, config, "determinism")
        signatures.add(
            (len(result.steps), result.answer.strip(), verdict.passed)
        )
    if len(signatures) > 1:
        problems.append(f"non-deterministic across {times} runs: {signatures}")
    return problems


def check_presets_are_distinguishable() -> list[str]:  # noqa: D401
    """Every preset must differ from clean in a way a config diff can show.

    Found by measurement: bug 2's config half sets retry_on_parse_error to
    false, which is ALREADY the clean value, so the merged config was identical
    to clean and a clean-vs-buggy comparison measured nothing. The bug is real
    (the runtime switch breaks the tool), but reporting it as a config
    difference would have been a false claim.
    """
    problems = []
    clean = clean_config()
    for bug in BUGS:
        reset_bug(bug)                      # clears runtime bug state too
        config = apply_bug(bug, write=False)
        reset_bug()
        differing = [
            k for k in set(clean) | set(config) if clean.get(k) != config.get(k)
        ]
        runtime_only = bug == "parse_error"
        if not differing and not runtime_only:
            problems.append(
                f"{bug}: preset produces a config identical to clean, so a "
                f"clean-vs-buggy comparison would measure nothing"
            )
        elif not differing and runtime_only:
            print(f"    (note: {bug} is runtime-only; its config half is a no-op "
                  f"by design and the fix is one boolean)")
    return problems


def main() -> int:
    failures = []
    print("→ every preset is distinguishable from clean")
    failures += check_presets_are_distinguishable()
    print("→ clean baseline must pass every task")
    failures += check_clean_passes()
    print("→ each injected bug must fail its train task")
    failures += check_bugs_fail()
    print("→ same config must give the same run twice")
    failures += check_determinism()

    reset_bug()
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"\nALL OK: {len(all_tasks())} tasks, {len(BUGS)} bugs, deterministic")
    return 0


if __name__ == "__main__":
    sys.exit(main())