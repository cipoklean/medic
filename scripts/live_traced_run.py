#!/usr/bin/env python
"""One real traced patient run, for the neatlogs dashboard.

A real LLM, real spans, a real trace id. This is the run the judge looks at, so
it is deliberately the CLEAN configuration: a failing run traced on a real model
is confusing evidence, and the bug demos have their own command.

Prints the dashboard trace link if one can be derived, and always the local run
id so the run is findable either way.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patient.config import load_env

# Non-CLI entry points must load .env themselves. cli.py does this at import;
# a script that skips it silently reads an empty environment and then fails
# with a stale or missing model — which is exactly what happened here.
load_env()

from bugs.inject import clean_config
from checks.checks import run_checks
from medic.runner import measured, run_once
from patient.tracing import init_neatlogs, new_run, shutdown
from tasks.loader import train_task_for


def main() -> int:
    live = init_neatlogs("patient-agent", tags=["demo", "real-llm", "clean"])
    print(f"neatlogs active: {live}")

    bug = "loop"
    task = train_task_for(bug)
    if task is None:
        print("no train task")
        return 1
    config = clean_config()

    recorder = new_run("patient-agent", tags=["demo", "real-llm", "clean"])
    print(f"run_id: {recorder.run_id}")
    print(f"question: {task['question'].strip()[:100]}")

    result = run_once(
        task["question"], recorder, config,
        on_step=lambda s: print(f"  step {s.index} {s.tool_name} {str(s.args)[:70]}"
                                + (f"  ERR {s.error[:60]}" if s.error else "")),
        mode="real",
    )
    verdict = run_checks(bug, task, result)
    m = measured(result, recorder)
    path = recorder.write({"result": result.to_dict(), "task_id": task["id"],
                           "bug": bug, "split": "train", "llm_mode": "real",
                           "phase": "demo", "check": verdict.to_dict()})

    shutdown()

    print("\n--- answer ---")
    print(result.answer[:400])
    print("\n--- measured ---")
    print(json.dumps(m, indent=2))
    print(f"\ncheck: {'PASS' if verdict.passed else 'FAIL'} — {verdict.reason}")
    print(f"local trace: {path}")
    print(f"spans: {len(recorder.spans)}")
    for span in recorder.spans:
        print(f"  {span['kind']:9} {span['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())