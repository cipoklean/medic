#!/usr/bin/env python
"""Does the parse_error bug reproduce on nova-micro, and does it recover?

This is the strongest bug class available: `retry_on_parse_error: false` is a
CONFIG DEFECT, not a tuned prompt. It is tool-level, so it should fail the same
way on any model, and the config half already forbids recovery, which makes
Medic's fix a single-field edit (false -> true).

Runs train plus every held-out task. Hitting the malformed payload counts as
reproduced; recovering from it does not.

    .venv/bin/python scripts/probe_parse_error.py
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
from medic.trace_source import load_trace
from patient import tracing
from tasks.loader import tasks_for

MODEL = "nova-micro"
RUNS = 3


def main() -> int:
    import os

    os.environ["LLM_MODEL_LITELLM"] = MODEL
    os.environ.setdefault("MEDIC_TOKEN_CEILING", "30000")

    tasks = tasks_for("parse_error", "train") + tasks_for("parse_error", "heldout")
    print(f"parse_error on {MODEL}, tool-level, {len(tasks)} tasks\n")

    reset_bug("parse_error")
    config = apply_bug("parse_error", write=False)

    per_task: dict[str, dict] = {}
    for task in tasks:
        rows, repro = [], 0
        split = "heldout" if task in tasks_for("parse_error", "heldout") else "train"
        print(f"── {task['id']}  [{split}]  expects {task['expected_answer']}")
        for i in range(1, RUNS + 1):
            rec = tracing.new_run(
                "patient-agent",
                tags=["bug=parse_error", f"model={MODEL}", f"task={task['id']}",
                      f"split={split}", f"run={i}", "llm=real"])
            result = run_once(task["question"], rec, config, mode="real")
            verdict = run_checks("parse_error", task, result)
            m = measured(result, rec)

            # did the malformed payload actually surface?
            saw_parse_error = any(
                "json" in (s.error or "").lower() or "parse" in (s.error or "").lower()
                for s in result.steps
            )
            rec.write({"result": result.to_dict(), "bug": "parse_error",
                       "task_id": task["id"], "split": split, "llm_mode": "real",
                       "model": MODEL, "preset": "parse_error", "phase": "probe",
                       "check": verdict.to_dict()})
            rows.append({
                "run": i, "reproduced": not verdict.passed,
                "failure_type": verdict.failure_type, "reason": verdict.reason,
                "saw_parse_error": saw_parse_error,
                "steps": m["steps"], "total_tokens": m["total_tokens"],
                "answer": result.answer[:160],
                "run_id": rec.run_id,
                "neatlogs_trace_id": rec.neatlogs_trace_id,
            })
            mark = "REPRODUCED" if not verdict.passed else "recovered "
            print(f"   run {i}: {mark} {m['steps']:2} steps {m['total_tokens']:6,} tok  "
                  f"parse_err_seen={saw_parse_error}")
            print(f"            {verdict.reason[:86]}")
            if not verdict.passed:
                repro += 1
            tracing.shutdown()

        per_task[task["id"]] = {"split": split, "runs": rows, "reproductions": repro}
        print()

    reset_bug("parse_error")

    total_repro = sum(v["reproductions"] for v in per_task.values())
    any_repro = total_repro > 0
    report = {
        "question": "Does the parse_error bug reproduce on nova-micro, regardless of model?",
        "model": MODEL,
        "bug_class": ("CONFIG DEFECT, not a tuned prompt: retry_on_parse_error=false "
                      "plus a tool that returns malformed JSON. The config half "
                      "already forbids recovery, so the fix is one boolean."),
        "tasks": per_task,
        "total_reproductions": total_repro,
        "reproduces": any_repro,
        "disclosure": ("A run counts as reproduced when the hard check fails. "
                       "saw_parse_error records whether the malformed payload "
                       "actually surfaced in that run, which separates 'the bug "
                       "fired' from 'the run failed for another reason'."),
    }
    out = Path(__file__).resolve().parents[1] / "evidence" / "repro_parse_error_nova_micro.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print("=" * 62)
    for tid, v in per_task.items():
        print(f"  {tid:26} {v['reproductions']}/{RUNS} reproduced  [{v['split']}]")
    print(f"\n  total: {total_repro}/{len(tasks)*RUNS} runs reproduced")
    print(f"  REPRODUCES: {any_repro}")
    print(f"wrote {out}")
    return 0 if any_repro else 1


if __name__ == "__main__":
    raise SystemExit(main())
