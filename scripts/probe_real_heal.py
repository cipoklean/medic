#!/usr/bin/env python
"""Real-LLM heal: capture before/after traces and measured numbers to evidence/.

This is the artefact behind the only claim that matters: "Medic healed it".
Every number here is read back from the runs themselves, and every trace id is
a real neatlogs trace that a judge can open.

Writes evidence/real_heal_loop.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patient.config import load_env

load_env()

from bugs.inject import apply_bug, clean_config, current_config, reset_bug
from checks.checks import run_checks
from medic.loop import heal
from medic.runner import measured, run_once
from medic.trace_source import load_trace
from patient import tracing
from tasks.loader import BUGS, heldout_for, train_task_for


def init_tracing() -> bool:
    """Without this every run records neatlogs_trace_id=None and the evidence
    has no trace link at all. run_once does not init the SDK - the caller owns
    that - so a script that forgets produces a silent, link-less artefact."""
    from patient.tracing import init_neatlogs

    return init_neatlogs("patient-agent", tags=["demo", "real-llm", "real-heal"])


def readback(run_id: str, trace_id: str | None) -> dict:
    """Can we read this run back from neatlogs? Recorded either way."""
    if not trace_id:
        return {"ok": False, "why": "no neatlogs trace id captured"}
    t = load_trace(trace_id)
    if t is None:
        return {"ok": False, "why": "read-back failed (local file still exists)"}
    return {
        "ok": True,
        "source": t.source,
        "spans": len(t.spans),
        "tool_spans": [s.name for s in t.tool_spans()],
        "totals": t.totals,
        "url": t.neatlogs_trace_url,
    }


def baseline(bug: str, preset: str | None = None) -> dict:
    """The failing run, on the buggy preset, with a real model."""
    task = train_task_for(bug, preset=preset)
    if task is None:
        raise SystemExit(f"no train task for {bug}")
    reset_bug(preset or bug)
    config = apply_bug(preset or bug, write=False)
    rec = tracing.new_run("patient-agent", tags=[f"bug={bug}", "phase=before", "llm=real"])
    result = run_once(task["question"], rec, config, mode="real")
    verdict = run_checks(bug, task, result)
    m = measured(result, rec)
    rec.write({"result": result.to_dict(), "bug": bug, "task_id": task["id"],
               "split": "train", "llm_mode": "real", "phase": "real-before",
               "check": verdict.to_dict()})
    return {
        "run_id": rec.run_id,
        "neatlogs_trace_id": rec.neatlogs_trace_id,
        "local_trace": f"runs/{rec.run_id}.json",
        "passed": verdict.passed,
        "failure_type": verdict.failure_type,
        "reason": verdict.reason,
        "details": verdict.details,
        "metrics": m,
        "tools_used": [s.tool_name for s in result.steps],
        "readback": readback(rec.run_id, rec.neatlogs_trace_id),
    }


def main() -> int:
    bug = "loop"
    preset = sys.argv[1] if len(sys.argv) > 1 else None
    if preset:
        print(f"using strengthened preset: {preset}")
    live = init_tracing()
    print(f"neatlogs active: {live}")
    print("=" * 74)
    print(f"REAL-LLM HEAL EVIDENCE — bug {bug}")
    print("=" * 74)

    print("\n[1/3] baseline (buggy preset, real model)…")
    before = baseline(bug, preset)
    print(f"      {'PASS' if before['passed'] else 'FAIL'} [{before['failure_type']}] "
          f"{before['reason'][:60]}")
    print(f"      {before['metrics']['steps']} steps · "
          f"{before['metrics']['total_tokens']} tokens · "
          f"${before['metrics']['est_cost_usd']:.6f}")
    print(f"      neatlogs trace: {before['neatlogs_trace_id']}")

    print("\n[2/3] heal loop (diagnose -> patch -> verify)…")
    outcome = heal(bug=bug, preset=preset or bug, mode="real", max_attempts=3)
    tracing.shutdown()
    print(f"      healed: {outcome.healed}  attempts: {len(outcome.attempts)}")

    attempts = []
    for a in outcome.attempts:
        entry = {
            "attempt": a.number,
            "diagnosis": a.diagnosis,
            "patch": a.patch,
            "refused": a.refused,
            "error": a.error,
            "llm_metrics": a.llm_metrics,
            "diff": a.diff,
        }
        if a.verify:
            train = a.verify.get("train") or {}
            entry["verify"] = {
                "train": {k: train.get(k) for k in
                          ("task_id", "passed", "steps", "total_tokens", "reason")},
                "heldout": [
                    {k: h.get(k) for k in ("task_id", "passed", "steps", "total_tokens", "reason")}
                    for h in (a.verify.get("heldout") or [])
                ],
                "all_passed": a.verify.get("all_passed"),
            }
        attempts.append(entry)
        print(f"      attempt {a.number}: patch="
              f"{(a.patch or {}).get('field')} all_passed="
              f"{(a.verify or {}).get('all_passed')}")

    print("\n[3/3] clean-baseline control…")
    reset_bug(preset or bug)
    clean = clean_config()
    control_task = train_task_for(bug)
    if control_task is None:
        raise SystemExit(f"no train task for {bug}")
    rec_c = tracing.new_run("patient-agent", tags=[f"bug={bug}", "phase=control", "llm=real"])
    res_c = run_once(control_task["question"], rec_c, clean, mode="real")
    ver_c = run_checks(bug, control_task, res_c)
    rec_c.write({"result": res_c.to_dict(), "bug": bug, "task_id": control_task["id"],
                 "split": "train", "llm_mode": "real", "phase": "real-control",
                 "check": ver_c.to_dict()})
    control = {
        "run_id": rec_c.run_id,
        "neatlogs_trace_id": rec_c.neatlogs_trace_id,
        "passed": ver_c.passed,
        "metrics": measured(res_c, rec_c),
        "readback": readback(rec_c.run_id, rec_c.neatlogs_trace_id),
    }
    tracing.shutdown()
    print(f"      clean {'PASS' if control['passed'] else 'FAIL'} · "
          f"{control['metrics']['steps']} steps · "
          f"{control['metrics']['total_tokens']} tokens")

    # Refuse to write a "heal" when none happened. `outcome.healed` is also True
    # on the already-healthy path, where nothing was diagnosed or patched; writing
    # that as a heal would be the exact overclaim this project exists to avoid.
    real_heal = bool(outcome.healed and outcome.attempts)
    if outcome.healed and not outcome.attempts:
        print("\n  NOTE: the baseline PASSED on this model — the bug did not\n"
              "        reproduce, so there was nothing for the LLM to heal.\n"
              "        Recording that, NOT a heal.")
    if not real_heal:
        print("\n  NOT writing a heal record: no LLM patch was proposed or verified.")
        reset_bug(bug)
        return 2

    report = {
        "claim": "A real LLM diagnosed the failing trace and proposed a medic.yaml "
                 "patch that cleared the train task AND every held-out task.",
        "bug": bug,
        "before": before,
        "attempts": attempts,
        "healed": outcome.healed,
        "after": outcome.final,
        "clean_control": control,
        "heldout_task_ids": [t["id"] for t in heldout_for(bug)],
    }
    suffix = f"_{preset}" if preset else ""
    out = Path(__file__).resolve().parents[1] / "evidence" / f"real_heal_loop{suffix}.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nwrote {out}")
    print(f"\nHEALED: {outcome.healed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())