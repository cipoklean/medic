#!/usr/bin/env python
"""Does the ORIGINAL loop preset reproduce on the nova models?

Three runs each, capped at 15 steps and a 30,000-token ceiling per run so a
probe cannot run away. Hitting either cap counts as reproduced: an agent that
has not finished is not going to.

loop_strong is NOT used. It was built for laguna-s-2.1 and is disclosed
separately; if none of the nova models reproduce on the original preset, that is
reported as a non-reproduction rather than quietly switching to the stronger one.

    .venv/bin/python scripts/probe_nova_loop.py
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
from tasks.loader import train_task_for

MODELS = ["nova-lite", "nova-micro", "nova-2-lite"]
RUNS = 3
NEEDED = 2          # stop as soon as it reproduces twice — every run costs money
MAX_STEPS = 15
TOKEN_CEILING = 30000


def main() -> int:
    import os

    os.environ.setdefault("MEDIC_TOKEN_CEILING", str(TOKEN_CEILING))
    task = train_task_for("loop")
    if task is None:
        print("no loop train task")
        return 1

    print(f"task {task['id']} · ORIGINAL loop.yaml · check limit {task['max_steps_allowed']}")
    print(f"guardrails: {MAX_STEPS} steps, {TOKEN_CEILING:,} tokens per run")
    print(f"models: {MODELS} · {RUNS} runs each · stop at {NEEDED} reproductions\n")

    per_model: dict[str, dict] = {}
    for model in MODELS:
        os.environ["LLM_MODEL_LITELLM"] = model
        reset_bug("loop")
        config = apply_bug("loop", write=False)

        print(f"── {model}")
        rows, repro = [], 0
        for i in range(1, RUNS + 1):
            rec = tracing.new_run("patient-agent",
                                  tags=[f"bug=loop", f"model={model}",
                                        f"probe_run={i}", "llm=real",
                                        "preset=loop(original)"])
            result = run_once(task["question"], rec, config, mode="real",
                              max_steps=MAX_STEPS)
            verdict = run_checks("loop", task, result)
            m = measured(result, rec)
            rec.write({"result": result.to_dict(), "bug": "loop", "task_id": task["id"],
                       "split": "train", "llm_mode": "real", "model": model,
                       "preset": "loop", "phase": "probe",
                       "check": verdict.to_dict()})
            row = {
                "run": i, "reproduced": not verdict.passed,
                "failure_type": verdict.failure_type,
                "reason": verdict.reason,
                "steps": m["steps"], "total_tokens": m["total_tokens"],
                "stopped_because": result.stopped_because,
                "run_id": rec.run_id,
                "neatlogs_trace_id": rec.neatlogs_trace_id,
            }
            if rec.neatlogs_trace_id:
                t = load_trace(rec.neatlogs_trace_id)
                if t:
                    row["readback"] = {"ok": True, "source": t.source, "spans": len(t.spans)}
            rows.append(row)
            mark = "REPRODUCED" if row["reproduced"] else "passed   "
            print(f"   run {i}: {mark} {row['steps']:2} steps {row['total_tokens']:6,} tok "
                  f"[{result.stopped_because}] {row['reason'][:44]}")
            if row["reproduced"]:
                repro += 1
            tracing.shutdown()
            if repro >= NEEDED:
                print(f"   -> {repro}/{i} reproduced. Stopping this model.")
                break

        per_model[model] = {
            "runs": rows, "reproductions": repro,
            "reliable": repro >= NEEDED,
            "preset": "loop (original, unmodified)",
        }
        print()
        reset_bug("loop")

    best = max(per_model, key=lambda k: per_model[k]["reproductions"])
    reliable = [m for m, v in per_model.items() if v["reliable"]]

    report = {
        "question": "Which nova model reproduces the ORIGINAL loop preset as the patient?",
        "guardrails": {"max_steps": MAX_STEPS, "token_ceiling": TOKEN_CEILING,
                       "needed_to_count": NEEDED},
        "preset": "loop (original, unmodified — loop_strong NOT used)",
        "models": per_model,
        "most_reliable": best,
        "reliable_models": reliable,
        "disclosure": ("Only models reproducing 2 of 2 runs are called reliable. "
                       "The original preset was NOT strengthened for this probe; "
                       "if nothing reproduced, that is reported as a "
                       "non-reproduction, not as grounds to switch presets."),
    }
    out = Path(__file__).resolve().parents[1] / "evidence" / "repro_nova_loop.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print("=" * 62)
    for m, v in per_model.items():
        print(f"  {m:14} {v['reproductions']}/{len(v['runs'])} reproduced"
              f"   {'RELIABLE' if v['reliable'] else ''}")
    print(f"\nPIN: {best if reliable else 'none — no nova model reproduces reliably'}")
    print(f"wrote {out}")
    return 0 if reliable else 1


if __name__ == "__main__":
    raise SystemExit(main())
