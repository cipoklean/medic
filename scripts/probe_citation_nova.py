#!/usr/bin/env python
"""Does the hallucinated_citation preset reproduce on nova-micro, unmodified?

Three runs on the train task. A reproduction counts only when the hard check
fails: a cited URL that was never fetched in that run. The preset is NOT
strengthened to force a failure. If it does not reproduce, that is recorded as a
non-reproduction and reported, not tuned away.

    .venv/bin/python scripts/probe_citation_nova.py
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
from tasks.loader import tasks_for

MODEL = "nova-micro"
RUNS = 3
NEEDED = 2


def main() -> int:
    import os

    os.environ["LLM_MODEL_LITELLM"] = MODEL
    os.environ.setdefault("MEDIC_TOKEN_CEILING", "30000")

    tasks = tasks_for("hallucinated_citation", "train")
    if not tasks:
        print("no hallucinated_citation train task")
        return 1
    task = tasks[0]

    print(f"hallucinated_citation preset, UNMODIFIED, on {MODEL}")
    print(f"task {task['id']} · limit {task['max_steps_allowed']} · {RUNS} runs\n")

    reset_bug("hallucinated_citation")
    config = apply_bug("hallucinated_citation", write=False)

    rows, repro = [], 0
    for i in range(1, RUNS + 1):
        rec = tracing.new_run(
            "patient-agent",
            tags=["bug=hallucinated_citation", f"model={MODEL}",
                  f"run={i}", "llm=real", "preset=hallucinated_citation"])
        result = run_once(task["question"], rec, config, mode="real")
        verdict = run_checks("hallucinated_citation", task, result)
        m = measured(result, rec)
        rec.write({"result": result.to_dict(), "bug": "hallucinated_citation",
                   "task_id": task["id"], "split": "train", "llm_mode": "real",
                   "model": MODEL, "phase": "probe",
                   "check": verdict.to_dict()})
        rows.append({
            "run": i,
            "reproduced": not verdict.passed,
            "failure_type": verdict.failure_type,
            "reason": verdict.reason,
            "metrics": verdict.metrics,
            "steps": m["steps"], "total_tokens": m["total_tokens"],
            "answer": result.answer[:300],
            "run_id": rec.run_id,
            "neatlogs_trace_id": rec.neatlogs_trace_id,
        })
        mark = "REPRODUCED" if not verdict.passed else "passed    "
        cited = verdict.metrics.get("cited", 0)
        fetched = verdict.metrics.get("fetched", 0)
        print(f"  run {i}: {mark} {m['steps']} steps {m['total_tokens']:6,} tok  "
              f"cited={cited} fetched={fetched}")
        print(f"           {verdict.reason[:84]}")
        if not verdict.passed:
            repro += 1
        tracing.shutdown()

    reset_bug("hallucinated_citation")

    report = {
        "question": f"Does the hallucinated_citation preset reproduce on {MODEL}?",
        "model": MODEL,
        "preset": "hallucinated_citation (original, unmodified)",
        "task_id": task["id"],
        "runs": rows,
        "reproductions": repro,
        "reliable": repro >= NEEDED,
        "disclosure": ("The preset was NOT strengthened. A run counts as "
                       "reproduced only when the hard check fails, i.e. a cited "
                       "URL that no fetch_page call in that run returned."),
    }
    out = Path(__file__).resolve().parents[1] / "evidence" / "repro_citation_nova_micro.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print(f"\n  reproduced: {repro}/{len(rows)}")
    print(f"  RELIABLE: {report['reliable']}")
    print(f"wrote {out}")
    return 0 if report["reliable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
