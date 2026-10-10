#!/usr/bin/env python
"""THE GATE. Does nova-micro behave correctly on a clean config?

This runs BEFORE any wrong_args or heal work, because the interpretation of
every later result depends on it: a model that fails on the clean config is
weak, and no amount of Medic patching is the answer. Reporting a heal against a
model that was never going to pass would be the overclaim this project is
guarding against.

    .venv/bin/python scripts/gate_nova_micro.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patient.config import load_env

load_env()

from bugs.inject import apply_bug, reset_bug
from checks.checks import run_checks
from medic.runner import measured, run_once
from patient import tracing
from tasks.loader import all_tasks

MODEL = "nova-micro"
RUNS = 3
NEEDED = 2   # disclosed if it lands between 2/3 and 3/3


def main() -> int:
    import os

    os.environ["LLM_MODEL_LITELLM"] = MODEL
    os.environ.setdefault("MEDIC_TOKEN_CEILING", "30000")

    tasks = all_tasks()
    print(f"GATE, clean medic.yaml on {MODEL}")
    print(f"{len(tasks)} tasks x {RUNS} runs · need {NEEDED}/{RUNS} per task\n")

    per_task: dict[str, dict] = {}
    for task in tasks:
        reset_bug()
        from patient.agent import load_config

        config = load_config()
        rows, passes = [], 0
        print(f"── {task['id']}  (expects {task['expected_answer']})")
        for i in range(1, RUNS + 1):
            rec = tracing.new_run("patient-agent",
                                  tags=[f"gate=clean", f"model={MODEL}",
                                        f"task={task['id']}", f"run={i}",
                                        "llm=real"])
            result = run_once(task["question"], rec, config, mode="real")
            verdict = run_checks(task["bug"], task, result)
            m = measured(result, rec)
            rec.write({"result": result.to_dict(), "bug": task["bug"],
                       "task_id": task["id"], "split": task.get("split", "train"),
                       "llm_mode": "real", "model": MODEL,
                       "phase": "gate_clean", "check": verdict.to_dict()})
            rows.append({
                "run": i, "passed": verdict.passed, "reason": verdict.reason,
                "failure_type": verdict.failure_type,
                "steps": m["steps"], "total_tokens": m["total_tokens"],
                "run_id": rec.run_id,
                "neatlogs_trace_id": rec.neatlogs_trace_id,
            })
            mark = "PASS" if verdict.passed else "FAIL"
            print(f"   run {i}: {mark}  {m['steps']:2} steps {m['total_tokens']:6,} tok  "
                  f"{verdict.reason[:50]}")
            if verdict.passed:
                passes += 1
            tracing.shutdown()

        per_task[task["id"]] = {
            "runs": rows, "passes": passes,
            "ok": passes >= NEEDED,
        }
        print()

    failing = [t for t, v in per_task.items() if not v["ok"]]
    report = {
        "question": f"Does {MODEL} pass every task on the CLEAN config?",
        "model": MODEL,
        "runs_per_task": RUNS,
        "needed": NEEDED,
        "tasks": per_task,
        "tasks_failing": failing,
        "gate_passed": not failing,
        "interpretation": ("If the gate fails, the model is too weak for this "
                           "work and no config patch is the answer. That is a "
                           "stop-and-report, not a bug to heal."),
    }
    out = Path(__file__).resolve().parents[1] / "evidence" / "gate_nova_micro_clean.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print("=" * 62)
    for t, v in per_task.items():
        print(f"  {t:28} {v['passes']}/{RUNS} pass  {'OK' if v['ok'] else 'GATE FAIL'}")
    print(f"\nGATE: {'PASSED' if not failing else 'FAILED, stop and report'}")
    if failing:
        print(f"failing: {failing}")
    print(f"wrote {out}")
    return 0 if not failing else 1


if __name__ == "__main__":
    raise SystemExit(main())
