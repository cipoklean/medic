#!/usr/bin/env python
"""Medic CLI, Typer + Rich.

  python cli.py doctor              env + neatlogs doctor + LLM ping
  python cli.py run --bug loop      inject a bug, run the patient, show the check
  python cli.py heal --bug loop     diagnose -> diff -> rerun -> heldout -> verdict
  python cli.py report              measured before/after per bug
  python cli.py reset               restore a clean medic.yaml
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from patient.config import ROOT, get, load_env, llm_configured, llm_settings

load_env()

app = typer.Typer(add_completion=False, help="Medic, the self-healing agent")
console = Console()

BUGS = ["wrong_args", "parse_error", "loop", "hallucinated_citation"]


def _ok(msg: str) -> None:
    console.print(f"[green]✓[/green] {msg}")


def _fail(msg: str) -> None:
    console.print(f"[red]✗[/red] {msg}")


def _warn(msg: str) -> None:
    console.print(f"[yellow]![/yellow] {msg}")


@app.command()
def doctor() -> None:
    """Environment, neatlogs SDK, and LLM connectivity."""
    console.print(Panel("[bold]Medic, doctor[/bold]", border_style="cyan"))

    # ── env ──
    table = Table(show_header=True, header_style="bold")
    table.add_column("check")
    table.add_column("result")
    ingest = get("NEATLOGS_API_KEY")
    token = get("NEATLOGS_TOKEN")
    project = get("NEATLOGS_PROJECT_ID")
    table.add_row("NEATLOGS_API_KEY (ingest)", "[green]set[/green]" if ingest else "[yellow]missing[/yellow]")
    table.add_row("NEATLOGS_TOKEN (read)", "[green]set[/green]" if token else "[yellow]missing, API read disabled[/yellow]")
    table.add_row("NEATLOGS_PROJECT_ID", "[green]set[/green]" if project else "[yellow]missing[/yellow]")
    s = llm_settings()
    table.add_row(
        "LLM (base/model)",
        f"{s['base_url'] or '[yellow]unset[/yellow]'} · {s['model'] or '[yellow]unset[/yellow]'}",
    )
    console.print(table)

    # ── python version ──
    ver = sys.version_info
    if (ver.major, ver.minor) >= (3, 10):
        _ok(f"Python {ver.major}.{ver.minor}.{ver.micro}")
    else:
        _fail("Python 3.10+ required")

    # ── neatlogs local doctor ──
    py = str(ROOT / ".venv" / "bin" / "python")
    if not Path(py).exists():
        py = sys.executable
    proc = subprocess.run(
        [py, "-m", "neatlogs", "doctor", "--local", "--json"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    try:
        out = json.loads(proc.stdout)
        if out.get("first_failure") is None:
            _ok(f"neatlogs doctor --local: {out['capture']['span_count']} spans, envelope valid")
        else:
            _fail(f"neatlogs doctor --local: {out['first_failure']}")
    except Exception:
        _fail(f"neatlogs doctor --local did not return JSON:\n{proc.stdout[-400:]}{proc.stderr[-400:]}")

    # ── LLM ping ──
    if llm_configured():
        try:
            from patient.agent import PatientAgent, load_config
            from patient.scripted import ScriptedLLM  # noqa: F401  (shape reference)

            from openai import OpenAI

            client = OpenAI(api_key=s["api_key"], base_url=s["base_url"])
            resp = client.chat.completions.create(
                model=s["model"],
                messages=[{"role": "user", "content": "reply with the single word: ok"}],
                temperature=0, max_tokens=5,
            )
            _ok(f"LLM reachable: {resp.choices[0].message.content.strip()!r} ({s['model']})")
        except Exception as exc:
            _fail(f"LLM ping failed: {type(exc).__name__}: {exc}")
    else:
        _warn("LLM not configured, offline scripted mode only (set LLM_BASE_URL/LLM_API_KEY/LLM_MODEL)")

    console.print(
        "\n[dim]Read-back of traces needs a service-account token, which is NOT the "
        "ingest key. Medic falls back to runs/<id>.json automatically.[/dim]"
    )


@app.command()
def run(
    bug: str = typer.Option(..., "--bug", help=f"one of: {', '.join(BUGS)}"),
    llm: str = typer.Option("scripted", "--llm", help="scripted (deterministic) or real"),
) -> None:
    """Inject a bug, run the patient on its train task, show the hard check."""
    from bugs.inject import apply_bug, reset_bug
    from checks.checks import run_checks
    from medic.runner import measured, run_once
    from tasks.loader import train_task_for
    from patient.tracing import new_run

    if bug not in BUGS:
        _fail(f"unknown bug {bug!r}; pick one of {', '.join(BUGS)}")
        raise typer.Exit(1)

    reset_bug(bug)
    config = apply_bug(bug)
    _ok(f"injected bug: {bug}")

    task = train_task_for(bug)
    if task is None:
        _fail(f"no train task for bug {bug}")
        raise typer.Exit(1)

    console.print(f"[dim]task {task['id']}: {task['question'].strip()[:90]}…[/dim]")
    recorder = new_run("patient-agent", tags=[f"bug={bug}", "phase=run"])

    def _show(step) -> None:
        try:
            console.print(
                f"  [cyan]step {step.index}[/cyan] {step.tool_name} {str(step.args)[:80]}"
                + (f" [red]ERR {step.error[:60]}[/red]" if step.error else "")
            )
        except Exception as exc:
            console.print(f"  [yellow]step {step.index} {step.tool_name} (render error: {exc})[/yellow]")

    if llm not in ("scripted", "real"):
        _fail(f"--llm must be 'scripted' or 'real', got {llm!r}")
        raise typer.Exit(1)
    console.print(f"[dim]llm mode: {llm}[/dim]")

    try:
        result = run_once(task["question"], recorder, config, on_step=_show, mode=llm)
    except Exception as exc:
        _fail(f"the agent raised {type(exc).__name__}: {exc}")
        raise typer.Exit(3)

    recorder.write({
        "result": result.to_dict(),
        "bug": bug,
        "task_id": task["id"],
        "llm_mode": llm,
    })

    verdict = run_checks(bug, task, result)
    m = measured(result, recorder)

    console.print()
    if verdict.passed:
        _ok(f"check PASSED, {verdict.reason}")
    else:
        _fail(f"check FAILED [{verdict.failure_type or 'unknown'}]: {verdict.reason}")
        for d in verdict.details:
            console.print(f"    [red]-[/red] {d}")
    console.print(
        f"[dim]run {result.run_id} · llm={llm} · steps {m['steps']} · tokens {m['total_tokens']} "
        f"(${m['est_cost_usd']:.6f}) · {m['latency_ms']:.0f}ms · "
        f"neatlogs {'active' if result.neatlogs_active else 'off'}[/dim]"
    )
    raise typer.Exit(0 if verdict.passed else 2)


@app.command()
def reset(bug: str = typer.Option(None, "--bug", help="only reset this bug; default is all")) -> None:
    """Restore the clean medic.yaml."""
    from bugs.inject import PRESET_DIR, reset_bug

    if bug:
        reset_bug(bug)
        _ok(f"cleared bug {bug}")
    else:
        clean = ROOT / "bugs" / "presets" / "clean.yaml"
        (ROOT / "medic.yaml").write_text(clean.read_text())
        _ok("medic.yaml restored to clean baseline")


@app.command()
def heal(
    bug: str = typer.Option(None, "--bug"),
    trace: str = typer.Option(None, "--trace"),
    apply: bool = typer.Option(False, "--apply", help="write the patch to medic.yaml"),
    llm: str = typer.Option("scripted", "--llm", help="scripted (deterministic) or real"),
    attempts: int = typer.Option(3, "--attempts"),
) -> None:
    """Full loop: diagnose -> diff -> rerun -> heldout -> verdict."""
    from medic.ui import run_heal_ui

    if llm not in ("scripted", "real"):
        _fail(f"--llm must be 'scripted' or 'real', got {llm!r}")
        raise typer.Exit(1)
    if not bug:
        _fail("pass --bug (a bare --trace cannot be verified without a hard check)")
        raise typer.Exit(1)

    try:
        healed = run_heal_ui(
            bug=bug,
            trace_id=trace,
            apply_patch=apply,
            mode=llm,
            max_attempts=attempts,
            console=console,
        )
    except Exception as exc:
        _fail(f"{type(exc).__name__}: {exc}")
        raise typer.Exit(3)
    raise typer.Exit(0 if healed else 2)


@app.command()
def report() -> None:
    """Measured before/after per bug. (Phase 4)"""
    from medic.report import build_report

    build_report(console)


if __name__ == "__main__":
    app()