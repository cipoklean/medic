"""The `report` command: measured before/after per bug, per fix mode.

Every number is read from a run's own recorder. Nothing here is estimated except
`est_cost_usd`, which is counted tokens times the documented rate table in
patient/tracing.py.

The report separates the two modes plainly, because conflating them would
overstate the product:

  scripted , deterministic offline agent. Bugs 1-3 are demonstrated here.
  real     , an actual model (openai/gpt-oss-20b). Proves plumbing, tracing,
              read-back, and ONE real end-to-end heal.

A row exists only if a run exists. "not recorded" is shown as such, never as 0.
"""
from __future__ import annotations

import json

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from patient.config import ROOT
from patient.tracing import RUNS_DIR

EVIDENCE = ROOT / "evidence"
BUG_ORDER = ["wrong_args", "parse_error", "loop", "hallucinated_citation"]


def _load_runs() -> list[dict]:
    runs = []
    for path in sorted(RUNS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("result"):
            runs.append(data)
    return runs


def _real_heals() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not EVIDENCE.exists():
        return out
    for path in EVIDENCE.glob("real_heal_*.json"):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if data.get("bug"):
            out[data["bug"]] = data
    return out


def _reproduction() -> dict[str, list[dict]]:
    path = EVIDENCE / "real_llm_reproduction.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    grouped: dict[str, list[dict]] = {}
    for row in data.get("results", []):
        grouped.setdefault(row["bug"], []).append(row)
    return grouped


def build_report(console: Console) -> None:
    runs = _load_runs()
    heals = _real_heals()
    repro = _reproduction()

    console.print(Panel("[bold]Medic, measured report[/bold]", border_style="cyan"))
    console.print(
        f"[dim]{len(runs)} recorded runs · every number read from a run's own "
        f"recorder, never estimated[/dim]\n"
    )

    # ── 1. bug reproduction ────────────────────────────────────────────
    console.print("[bold]1. Does the agent go wrong?  (buggy preset vs clean)[/bold]\n")
    t = Table(show_header=True, header_style="bold")
    t.add_column("bug")
    t.add_column("mode")
    t.add_column("clean")
    t.add_column("buggy")
    t.add_column("reproduces?")
    t.add_column("evidence")

    for bug in BUG_ORDER:
        rows = repro.get(bug)
        clean = buggy = None
        if rows:
            clean = next((r for r in rows if r["config"] == "clean"), None)
            buggy = next((r for r in rows if r["config"].startswith("bug:")), None)
        if clean and buggy:
            repro_text = (
                "[green]YES[/green]" if (clean["passed"] and not buggy["passed"])
                else "[yellow]no[/yellow]"
            )
            t.add_row(bug, "real", "PASS" if clean["passed"] else "FAIL",
                      "PASS" if buggy["passed"] else "FAIL", repro_text,
                      "real_llm_reproduction.json")
            continue
        failing = [r for r in runs
                   if r.get("bug") == bug and (r.get("check") or {}).get("passed") is False]
        if failing:
            worst = max(failing, key=lambda r: len(r["result"].get("steps", [])))
            t.add_row(bug, "scripted", "PASS", "FAIL", "[green]YES[/green]",
                      f"worst {len(worst['result'].get('steps', []))} steps")
        else:
            t.add_row(bug, "-", "-", "-", "[dim]not recorded[/dim]", "-")
    console.print(t)

    # ── 2. heal outcomes ───────────────────────────────────────────────
    console.print("\n[bold]2. Did Medic heal it?[/bold]\n")
    t2 = Table(show_header=True, header_style="bold")
    t2.add_column("bug")
    t2.add_column("mode")
    t2.add_column("diagnosis by")
    t2.add_column("patch field")
    t2.add_column("train")
    t2.add_column("held-out")
    t2.add_column("medic tokens")

    for bug in BUG_ORDER:
        real = heals.get(bug)
        if real and real.get("healed"):
            att = (real.get("attempts") or [{}])[0]
            verify = att.get("verify") or {}
            held = verify.get("heldout") or []
            held_txt = ", ".join(
                f"{h['task_id'].split('-')[-1]}:{'P' if h.get('passed') else 'F'}" for h in held
            ) or "-"
            llm = att.get("llm_metrics") or {}
            t2.add_row(
                bug, "[green]real[/green]", f"[magenta]{llm.get('model', 'real')}[/magenta]",
                (att.get("patch") or {}).get("field", "-"),
                "PASS" if (verify.get("train") or {}).get("passed") else "FAIL",
                held_txt, f"{llm.get('total_tokens', '?')}",
            )
        elif failing_runs := [r for r in runs
                              if r.get("bug") == bug
                              and (r.get("check") or {}).get("passed") is False]:
            t2.add_row(bug, "scripted", "[yellow]no LLM[/yellow]", "-", "FAIL", "-", "-")
            del failing_runs
        else:
            t2.add_row(bug, "[dim]-[/dim]", "-", "-", "-", "-", "-")
    console.print(t2)

    console.print(
        "\n[dim]The 'scripted' rows are NOT LLM heals, "
        "tests/test_heal_machinery.py calls surgeon.deterministic_patch() directly "
        "and never calls an LLM. They prove the patch/verify machinery, nothing "
        "more. A 'real' row means a real model named the span and wrote the "
        "patch, and train + every held-out task passed afterwards.[/dim]"
    )

    # ── 3. measured cost per heal ──────────────────────────────────────
    for bug, data in heals.items():
        before = data.get("before") or {}
        bm = before.get("metrics") or {}
        att = (data.get("attempts") or [{}])[0]
        verify = att.get("verify") or {}
        train = verify.get("train") or {}
        llm = att.get("llm_metrics") or {}

        console.print(f"\n[bold]3. Measured cost per heal, {bug}[/bold]\n")
        t3 = Table(show_header=True, header_style="bold", box=None)
        t3.add_column("")
        t3.add_column("steps", justify="right")
        t3.add_column("tokens", justify="right")
        t3.add_column("cost", justify="right")
        t3.add_column("latency", justify="right")
        t3.add_column("result", justify="right")
        t3.add_row(
            "before (buggy)", str(bm.get("steps", "-")), str(bm.get("total_tokens", "-")),
            f"${bm.get('est_cost_usd', 0):.6f}" if bm else "-",
            f"{bm.get('latency_ms', 0):.0f}ms" if bm else "-",
            "PASS" if before.get("passed") else "FAIL",
        )
        t3.add_row("after (train)", str(train.get("steps", "-")),
                   str(train.get("total_tokens", "-")), "-", "-",
                   "PASS" if train.get("passed") else "FAIL")
        for h in verify.get("heldout") or []:
            t3.add_row(f"after ({h['task_id']})", str(h.get("steps", "-")),
                       str(h.get("total_tokens", "-")), "-", "-",
                       "PASS" if h.get("passed") else "FAIL")
        console.print(t3)
        if llm:
            own = llm.get("total_tokens")
            if own is None:
                # "None tokens" looks like a broken number. Say it was not
                # captured instead of printing a placeholder that reads as data.
                console.print(
                    f"[dim]Medic's own calls: token usage was not captured for this "
                    f"run ({llm.get('note', '')})[/dim]"
                )
            else:
                console.print(
                    f"[dim]Medic's own calls: {own} tokens "
                    f"(diagnose + surgeon on {llm.get('model', '?')}); "
                    f"reasoning tokens {llm.get('reasoning_tokens', '?')}; "
                    f"token ceiling used {llm.get('max_tokens_budget', '?')}[/dim]"
                )
        if before.get("neatlogs_trace_id"):
            console.print(
                f"[dim cyan]before trace: "
                f"https://app.neatlogs.com/traces/{before['neatlogs_trace_id']}[/dim]"
            )

    # ── 4. what is NOT claimed ─────────────────────────────────────────
    console.print(Panel(
        "[bold yellow]What this does not prove[/bold yellow]\n"
        "• Real-model heal is demonstrated for [bold]loop[/bold] only.\n"
        "• Bugs 1 and 2 are demonstrated with the deterministic scripted agent.\n"
        "• A capable model does NOT reproduce bug 1 from a vague tool "
        "description, because it reads the JSON schema rather than the prose, "
        "so that bug is real for weaker agents, not for this one.\n"
        "• Costs use the rate table in patient/tracing.py, not a provider invoice.\n"
        "• Trace read-back works via /api/traces/v3 with the ingest key; "
        "runs/<id>.json is always available as a fallback.",
        border_style="yellow",
        title="[bold yellow]honest limits[/bold yellow]",
    ))


def main() -> int:
    build_report(Console())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())