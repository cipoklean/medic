#!/usr/bin/env python
"""Does loop_strong reproduce on nara/laguna-s-2.1, RELIABLY?

Stops as soon as the failure is confirmed in 2 of 3 runs, because every probe
costs tokens and the point is to find out whether the demo is safe, not to
characterise the distribution to six decimal places.

Writes evidence/repro_loop_strong_laguna.json.
"""
from __future__ import annotations

import argparse
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
from tasks.loader import train_task_for


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bug", default="loop_strong")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--needed", type=int, default=2,
                    help="stop once this many runs FAIL (i.e. reproduce)")
    ap.add_argument("--out", default="evidence/repro_loop_strong_laguna.json")
    args = ap.parse_args()

    bug_key = "loop"           # the hard check stays the original loop check
    task = train_task_for(bug_key, preset=args.bug)
    if task is None:
        print("no train task with that preset")
        return 1

    reset_bug(args.bug)
    config = apply_bug(args.bug, write=False)
    reset_bug()

    print(f"preset {args.bug} · task {task['id']} · check=loop · limit {task['max_steps_allowed']}")
    print(f"need {args.needed} failures out of {args.runs}\n")

    results = []
    failures = 0
    for i in range(1, args.runs + 1):
        rec = tracing.new_run("patient-agent",
                              tags=[f"bug={bug_key}", f"preset={args.bug}",
                                    f"probe_run={i}", "llm=real"])
        result = run_once(task["question"], rec, config, mode="real")
        verdict = run_checks(bug_key, task, result)
        m = measured(result, rec)
        rec.write({"result": result.to_dict(), "bug": bug_key, "task_id": task["id"],
                   "split": "train", "llm_mode": "real",
                   "preset": args.bug, "phase": "probe",
                   "check": verdict.to_dict()})
        row = {
            "run": i,
            "reproduced": (not verdict.passed),
            "failure_type": verdict.failure_type,
            "reason": verdict.reason,
            "steps": m["steps"],
            "total_tokens": m["total_tokens"],
            "tools_used": [s.tool_name for s in result.steps],
            "run_id": rec.run_id,
            "neatlogs_trace_id": rec.neatlogs_trace_id,
        }
        if rec.neatlogs_trace_id:
            t = load_trace(rec.neatlogs_trace_id)
            if t:
                row["readback"] = {"ok": True, "source": t.source, "spans": len(t.spans)}
        results.append(row)
        mark = "REPRODUCED" if row["reproduced"] else "passed"
        print(f"  run {i}: {mark:11} {row['steps']:2} steps  {row['total_tokens']:6} tok  "
              f"{row['reason'][:52]}")
        if row["reproduced"]:
            failures += 1
        tracing.shutdown()

        if failures >= args.needed:
            print(f"\n  -> {failures}/{i} runs reproduced. Stopping (threshold {args.needed}).")
            break

    reset_bug()
    reliable = failures >= args.needed
    report = {
        "question": f"Does the STRENGTHENED loop preset reproduce on {args.bug}?",
        "preset": args.bug,
        "model": "nara/laguna-s-2.1",
        "hard_check": bug_key,
        "task_id": task["id"],
        "runs": results,
        "failures": failures,
        "needed": args.needed,
        "reliable": reliable,
        "disclosure": ("loop_strong is a DELIBERATELY STRENGTHENED variant of "
                       "bugs/presets/loop.yaml, created so this model reproduces "
                       "the bug. The original preset is unchanged. Any number from "
                       "loop_strong must be labelled as a strengthened preset."),
    }
    out = Path(__file__).resolve().parents[1] / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"\nRELIABLE: {reliable}  ({failures} failures in {len(results)} runs)")
    print(f"wrote {out}")
    return 0 if reliable else 1


if __name__ == "__main__":
    raise SystemExit(main())