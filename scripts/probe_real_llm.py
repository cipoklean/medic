#!/usr/bin/env python
"""Does a REAL model reproduce each bug on its buggy preset, and pass clean?

This is the honesty gate. A scripted agent obeying its own config proves the
harness is consistent; it does NOT prove a real model goes wrong in the same
way. Only this script can.

NO PRESET IS TUNED. Whatever the model does is recorded, including "it did not
reproduce the bug", which is a finding, not a failure to hide. A preset tuned
until the model misbehaves would make the bug a property of the preset rather
than of the agent.

  .venv/bin/python scripts/probe_real_llm.py --bugs loop wrong_args
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patient.config import load_env

load_env()

from bugs.inject import MEDIC_YAML, apply_bug, clean_config, reset_bug
from checks.checks import run_checks
from medic.runner import measured, run_once
from patient import tracing
from tasks.loader import train_task_for
from medic.trace_source import load_trace


def one(bug: str, config: dict, label: str, task: dict) -> dict:
    recorder = tracing.new_run(
        "patient-agent", tags=[f"bug={bug}", f"config={label}", "llm=real"]
    )
    started = time.time()
    result = run_once(task["question"], recorder, config, mode="real")
    verdict = run_checks(bug, task, result)
    m = measured(result, recorder)
    path = recorder.write({
        "result": result.to_dict(), "bug": bug, "task_id": task["id"],
        "split": "train", "llm_mode": "real", "phase": f"real-{label}",
        "config": label, "check": verdict.to_dict(),
    })
    tracing.shutdown()
    return {
        "bug": bug, "config": label, "run_id": recorder.run_id,
        "neatlogs_trace_id": recorder.neatlogs_trace_id,
        "local_trace": str(path),
        "passed": verdict.passed,
        "failure_type": verdict.failure_type,
        "reason": verdict.reason,
        "details": verdict.details,
        "steps": m["steps"], "total_tokens": m["total_tokens"],
        "est_cost_usd": m["est_cost_usd"], "latency_ms": m["latency_ms"],
        "stopped_because": result.stopped_because,
        "error": result.error,
        "tools_used": [s.tool_name for s in result.steps],
        "answer": result.answer[:300],
        "wall_clock_s": round(time.time() - started, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bugs", nargs="+", default=["loop", "wrong_args"])
    ap.add_argument("--out", default="evidence/real_llm_reproduction.json")
    args = ap.parse_args()

    clean = clean_config()
    report: dict = {
        "note": "Real model, temperature 0, fixtures only. No preset tuning: "
                "whatever the model did is recorded as-is.",
        "model_note": "see .env LLM_MODEL",
        "results": [],
    }

    for bug in args.bugs:
        task = train_task_for(bug)
        if task is None:
            print(f"!! no train task for {bug}")
            continue
        print("=" * 74)
        print(f"BUG {bug}  ({task['id']})")
        print("=" * 74)

        print("\n-- clean config (expect PASS) --")
        r_clean = one(bug, clean, "clean", task)
        print(f"   {'PASS' if r_clean['passed'] else 'FAIL'}  {r_clean['reason'][:70]}")
        print(f"   {r_clean['steps']} steps · {r_clean['total_tokens']} tok · "
              f"${r_clean['est_cost_usd']:.6f} · tools={r_clean['tools_used']}")
        report["results"].append(r_clean)

        reset_bug(bug)
        buggy = apply_bug(bug, write=False)
        print(f"\n-- {bug} preset injected (expect FAIL) --")
        r_bug = one(bug, buggy, f"bug:{bug}", task)
        print(f"   {'PASS' if r_bug['passed'] else 'FAIL'}  [{r_bug['failure_type']}] "
              f"{r_bug['reason'][:70]}")
        print(f"   {r_bug['steps']} steps · {r_bug['total_tokens']} tok · "
              f"${r_bug['est_cost_usd']:.6f} · tools={r_bug['tools_used']}")
        for d in r_bug["details"]:
            print(f"     - {d[:110]}")
        print(f"   answer: {r_bug['answer'][:150]}")
        report["results"].append(r_bug)

        # Can we read the real trace back and see the tool spans?
        if r_bug["neatlogs_trace_id"]:
            t = load_trace(r_bug["neatlogs_trace_id"])
            if t:
                print(f"   read-back OK: source={t.source} spans={len(t.spans)} "
                      f"tools={[s.name for s in t.tool_spans()]} "
                      f"tokens={t.totals.get('total_tokens')}")
                r_bug["readback"] = {"ok": True, "spans": len(t.spans),
                                     "source": t.source,
                                     "tool_spans": [s.name for s in t.tool_spans()],
                                     "totals": t.totals}
            else:
                print("   read-back: FAILED (local file still available)")
                r_bug["readback"] = {"ok": False}
        print()

    reset_bug()

    out = Path(__file__).resolve().parents[1] / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out}")

    # summary
    print("\n" + "=" * 74)
    print(f"{'bug':16} {'clean':8} {'buggy':8} {'reproduced':11} {'why'}")
    for bug in args.bugs:
        rows = [r for r in report["results"] if r["bug"] == bug]
        c = next((r for r in rows if r["config"] == "clean"), None)
        b = next((r for r in rows if r["config"].startswith("bug:")), None)
        if not c or not b:
            continue
        reproduced = (c["passed"] and not b["passed"])
        print(f"{bug:16} {'PASS' if c['passed'] else 'FAIL':8} "
              f"{'PASS' if b['passed'] else 'FAIL':8} "
              f"{'YES' if reproduced else 'NO':11} {b['reason'][:44]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())