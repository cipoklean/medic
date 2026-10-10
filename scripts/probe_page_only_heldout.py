#!/usr/bin/env python
"""Do the two NEW page-only held-out tasks actually fire the parse_error bug?

A held-out task that cannot fail proves nothing about the patch. These two must
show parse_err_seen=True and FAIL on the buggy config BEFORE the healed config is
allowed to claim they passed.

    .venv/bin/python scripts/probe_page_only_heldout.py
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
NEW = ["parse-error-vertex", "parse-error-kestrel"]


def run_one(task, config, tag_phase):
    import os

    os.environ["LLM_MODEL_LITELLM"] = MODEL
    rec = tracing.new_run(
        "patient-agent",
        tags=["bug=parse_error", f"model={MODEL}", f"task={task['id']}",
              f"phase={tag_phase}", "llm=real", "heldout=page-only"])
    result = run_once(task["question"], rec, config, mode="real")
    verdict = run_checks("parse_error", task, result)
    m = measured(result, rec)
    saw = any("json" in (s.error or "").lower() or "parse" in (s.error or "").lower()
              for s in result.steps)
    rec.write({"result": result.to_dict(), "bug": "parse_error",
               "task_id": task["id"], "split": "heldout", "llm_mode": "real",
               "model": MODEL, "phase": tag_phase,
               "heldout_kind": "page-only", "check": verdict.to_dict()})
    tracing.shutdown()
    return {
        "task_id": task["id"], "phase": tag_phase,
        "passed": verdict.passed, "failure_type": verdict.failure_type,
        "reason": verdict.reason, "parse_err_seen": saw,
        "steps": m["steps"], "total_tokens": m["total_tokens"],
        "tools": [s.tool_name for s in result.steps],
        "answer": result.answer[:140],
        "run_id": rec.run_id,
        "neatlogs_trace_id": rec.neatlogs_trace_id,
    }


def main() -> int:
    tasks = {t["id"]: t for t in tasks_for("parse_error", "heldout")
             if t["id"] in NEW}
    if not tasks:
        print("new page-only tasks not found")
        return 1

    rows = []

    print(f"BUGGY config, the bug MUST fire ({MODEL})\n")
    reset_bug("parse_error")
    buggy = apply_bug("parse_error", write=False)
    for tid in NEW:
        r = run_one(tasks[tid], buggy, "buggy")
        rows.append(r)
        print(f"  {tid:22} {'FAIL' if not r['passed'] else 'PASS(!)'} "
              f"parse_err_seen={r['parse_err_seen']}  tools={r['tools']}")
        print(f"  {'':22} {r['reason'][:80]}")

    buggy_ok = all(not r["passed"] and r["parse_err_seen"] for r in rows)

    print(f"\nHEALED config (retry_on_parse_error: true)\n")
    healed = apply_bug("parse_error", write=False)
    healed["retry_on_parse_error"] = True
    for tid in NEW:
        r = run_one(tasks[tid], healed, "healed")
        rows.append(r)
        print(f"  {tid:22} {'PASS' if r['passed'] else 'FAIL'} "
              f"{r['steps']} steps {r['total_tokens']:,} tok")
        print(f"  {'':22} {r['reason'][:80]}")

    reset_bug("parse_error")
    healed_ok = all(r["passed"] for r in rows if r["phase"] == "healed")

    report = {
        "question": "Do the page-only held-out tasks fire the bug, and does the patch hold?",
        "model": MODEL,
        "tasks": NEW,
        "runs": rows,
        "bug_fires_on_buggy": buggy_ok,
        "patch_holds_on_healed": healed_ok,
        "disclosure": ("These two tasks are verification only and are never shown "
                       "to diagnose or surgeon. Their figures exist solely on the "
                       "page fixture, so the agent must call fetch_page - which is "
                       "where the malformed JSON lives. The two ORIGINAL held-out "
                       "tasks are kept unchanged; they state their figures in the "
                       "question, so they do not exercise this bug and passing them "
                       "does not prove the patch."),
    }
    out = Path(__file__).resolve().parents[1] / "evidence" / "page_only_heldout.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print(f"\n  bug fires on buggy config: {buggy_ok}")
    print(f"  patch holds on healed:     {healed_ok}")
    print(f"wrote {out}")
    return 0 if (buggy_ok and healed_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
