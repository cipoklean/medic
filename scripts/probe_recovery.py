"""Bug 2 recovery probe, addendum item 4.

`cli.py run --bug parse_error` shows the FAILURE: the tool lies, the agent has
no recovery, the run dies. This shows the OTHER half: the SAME failure with
`retry_on_parse_error: true`, where the agent visibly recovers.

Both runs are traced, so the pair is a before/after in neatlogs with the
recovered run tagged `recovery=demonstrated`. Recovery is a judged focus area,
so it must be an artefact we can point at rather than a claim in a README.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Running `python scripts/probe_recovery.py` puts scripts/ on sys.path, not the
# repo root, so every project import would fail. cli.py solves this for itself
# at the top of the file; a script has to do it for itself.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from bugs.inject import MEDIC_YAML, apply_bug, reset_bug
from checks.checks import run_checks
from medic.runner import measured, run_once
from patient import tracing
from tasks.loader import train_task_for


def recovered_config() -> dict:
    """Bug 2 with the ONE config change that fixes it."""
    config = apply_bug("parse_error", write=False)
    config = dict(config)
    config["retry_on_parse_error"] = True
    return config


def main() -> int:
    bug = "parse_error"
    task = train_task_for(bug)
    if task is None:
        print("no train task")
        return 1

    print("=" * 72)
    print(f"BUG 2 RECOVERY, task {task['id']}")
    print("=" * 72)

    # ── BEFORE: no recovery path ──
    reset_bug(bug)
    before_cfg = apply_bug(bug, write=False)
    rec_b = tracing.new_run("patient-agent", tags=[f"bug={bug}", "recovery=before"])
    print("\n── BEFORE (retry_on_parse_error: false) ──")
    res_b = run_once(task["question"], rec_b, before_cfg,
                     on_step=lambda s: print(f"  step {s.index} {s.tool_name}"
                                              + (f"  ERR {s.error[:60]}" if s.error else "")))
    rec_b.write({"result": res_b.to_dict(), "task_id": task["id"], "recovery": "before"})
    v_b = run_checks(bug, task, res_b)
    m_b = measured(res_b, rec_b)
    print(f"  {'PASS' if v_b.passed else 'FAIL'}: {v_b.reason}")
    print(f"  steps={m_b['steps']} tokens={m_b['total_tokens']} errors={m_b['errors']}")

    # ── AFTER: same broken tool, recovery enabled ──
    after_cfg = recovered_config()
    rec_a = tracing.new_run("patient-agent", tags=[f"bug={bug}", "recovery=demonstrated"])
    print("\n── AFTER (retry_on_parse_error: true, ONE config change) ──")
    res_a = run_once(task["question"], rec_a, after_cfg,
                     on_step=lambda s: print(f"  step {s.index} {s.tool_name}"
                                              + (f"  ERR {s.error[:60]}" if s.error else "")))
    rec_a.write({"result": res_a.to_dict(), "task_id": task["id"], "recovery": "after"})
    v_a = run_checks(bug, task, res_a)
    m_a = measured(res_a, rec_a)
    print(f"  {'PASS' if v_a.passed else 'FAIL'}: {v_a.reason}")
    print(f"  steps={m_a['steps']} tokens={m_a['total_tokens']} errors={m_a['errors']}")

    reset_bug()

    ok = (not v_b.passed) and v_a.passed
    print("\n" + "─" * 72)
    print(f"RECOVERY DEMONSTRATED: {ok}")
    print(f"  before: {m_b['steps']} steps, {m_b['total_tokens']} tokens, "
          f"${m_b['est_cost_usd']:.6f}, stopped because '{res_b.stopped_because}'")
    print(f"  after : {m_a['steps']} steps, {m_a['total_tokens']} tokens, "
          f"${m_a['est_cost_usd']:.6f}, stopped because '{res_a.stopped_because}'")
    print(f"  traces: {rec_b.run_id}.json (before), {rec_a.run_id}.json (after)")

    # A committed evidence artefact. Measured only, no prose numbers.
    evidence = {
        "bug": bug,
        "task_id": task["id"],
        "question": task["question"].strip(),
        "single_config_change": {"field": "retry_on_parse_error", "from": False, "to": True},
        "before": {
            "trace_id": rec_b.run_id,
            "check": v_b.to_dict(),
            "metrics": m_b,
            "failed_tool_step": next(
                ({"index": s.index, "tool": s.tool_name, "error": s.error}
                 for s in res_b.steps if s.error),
                None,
            ),
        },
        "after": {
            "trace_id": rec_a.run_id,
            "check": v_a.to_dict(),
            "metrics": m_a,
            "recovery_observed": any(
                s.error and i + 1 < len(res_a.steps)
                for i, s in enumerate(res_a.steps)
            ),
        },
        "recovery_demonstrated": ok,
    }
    out = Path(__file__).resolve().parents[1] / "evidence" / "recovery_parse_error.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2))
    print(f"  evidence: evidence/recovery_parse_error.json")

    if ok:
        with open(MEDIC_YAML, "w") as fh:
            yaml.safe_dump(after_cfg, fh, sort_keys=False, allow_unicode=True)
        print("\nmedic.yaml now holds the recovered config (run `cli.py reset` to restore clean).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())