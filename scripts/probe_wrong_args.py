#!/usr/bin/env python
"""Does the wrong_args preset reproduce on nova-micro, with the right signature?

Wrong here means: a tool called with PROSE where an expression was required, or
a final answer that is not the known value. Both, measured. Runs the correct
task for the bug (not the loop task), against the correct check, on the correct
model.

    .venv/bin/python scripts/probe_wrong_args.py
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
NEEDED = 2


def main() -> int:
    import os

    os.environ["LLM_MODEL_LITELLM"] = MODEL
    os.environ.setdefault("MEDIC_TOKEN_CEILING", "30000")

    tasks = tasks_for("wrong_args", "train")
    if not tasks:
        print("no wrong_args train task")
        return 1
    task = tasks[0]
    print(f"wrong_args preset on {MODEL}")
    print(f"task {task['id']} · expects {task['expected_answer']} · limit {task['max_steps_allowed']}\n")

    reset_bug("wrong_args")
    config = apply_bug("wrong_args", write=False)

    rows, repro = [], 0
    for i in range(1, RUNS + 1):
        rec = tracing.new_run("patient-agent",
                              tags=["bug=wrong_args", f"model={MODEL}",
                                    f"run={i}", "llm=real", "preset=wrong_args"])
        result = run_once(task["question"], rec, config, mode="real")
        verdict = run_checks("wrong_args", task, result)
        m = measured(result, rec)

        # the signature: did any calculator call receive prose?
        prose_calls = []
        for step in result.steps:
            args = step.args or {}
            expr = str(args.get("expression", "")).strip()
            if expr and not all(c.isdigit() or c in ".+-*/()% ,eE" for c in expr):
                prose_calls.append(expr[:90])

        rec.write({"result": result.to_dict(), "bug": "wrong_args",
                   "task_id": task["id"], "split": "train", "llm_mode": "real",
                   "model": MODEL, "preset": "wrong_args", "phase": "probe",
                   "check": verdict.to_dict()})
        row = {
            "run": i,
            "reproduced": not verdict.passed,
            "failure_type": verdict.failure_type,
            "reason": verdict.reason,
            "steps": m["steps"], "total_tokens": m["total_tokens"],
            "answer": result.answer[:200],
            "prose_argument_calls": prose_calls,
            "run_id": rec.run_id,
            "neatlogs_trace_id": rec.neatlogs_trace_id,
        }
        if rec.neatlogs_trace_id:
            t = load_trace(rec.neatlogs_trace_id)
            if t:
                row["readback"] = {"ok": True, "source": t.source, "spans": len(t.spans)}
        rows.append(row)

        mark = "REPRODUCED" if row["reproduced"] else "passed    "
        sig = f"prose-arg: {prose_calls[0][:40]}" if prose_calls else "args clean"
        print(f"  run {i}: {mark} {m['steps']:2} steps {m['total_tokens']:6,} tok  {sig}")
        print(f"           {verdict.reason[:88]}")
        if row["reproduced"]:
            repro += 1
        tracing.shutdown()

    reset_bug("wrong_args")

    report = {
        "question": f"Does the wrong_args preset reproduce on {MODEL}, with the prose-argument signature?",
        "model": MODEL,
        "preset": "wrong_args (original, unmodified)",
        "task_id": task["id"],
        "expected_answer": task["expected_answer"],
        "runs": rows,
        "reproductions": repro,
        "reliable": repro >= NEEDED,
        "signature_present": any(r["prose_argument_calls"] for r in rows),
        "disclosure": ("A reproduction counts only when the hard check fails. "
                       "prose_argument_calls records whether the tool was "
                       "actually called with prose, which is the signature that "
                       "distinguishes this bug from a plain wrong answer."),
    }
    out = Path(__file__).resolve().parents[1] / "evidence" / "repro_wrong_args_nova_micro.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print(f"\n  reproduced: {repro}/{len(rows)}")
    print(f"  prose-argument signature present: {report['signature_present']}")
    print(f"  RELIABLE: {report['reliable']}")
    print(f"wrote {out}")
    return 0 if report["reliable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
