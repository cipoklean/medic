"""The Rich UI for `heal`.

Screen layout, in the order the spec asks for:
  header (bug, task) -> live patient run -> red FAIL + check reason + trace link
  -> diagnosis -> coloured diff -> re-run -> held-out table -> big verdict

One rule that shapes the whole file: NOTHING is printed that was not measured.
Every number comes from the run's own recorder. If a value is unavailable the
panel says "unavailable" rather than showing a plausible-looking zero.

The LLM's proposed failure_type and confidence are shown as what they are — a
proposal — next to the deterministic verdict, never as the verdict itself.
"""
from __future__ import annotations

from typing import Literal

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def _m(d: dict | None) -> str:
    if not d:
        return "n/a"
    steps = d.get("steps", "?")
    tokens = d.get("total_tokens", "?")
    cost = d.get("est_cost_usd")
    cost_s = f"${cost:.6f}" if isinstance(cost, (int, float)) else "n/a"
    lat = d.get("latency_ms")
    lat_s = f"{lat:.0f}ms" if isinstance(lat, (int, float)) else "n/a"
    return f"{steps} steps · {tokens} tokens · {cost_s} · {lat_s}"


def _header(console: Console, bug: str, mode: str) -> None:
    console.print(
        Panel(
            Text.assemble(
                ("Medic ", "bold white"),
                ("· heal", "bold cyan"),
                ("   bug=", "dim"),
                (bug, "bold yellow"),
                ("   llm=", "dim"),
                (mode, "bold magenta"),
            ),
            border_style="cyan",
            title="[bold]neatHack 2026[/bold]",
        )
    )


def _fail_panel(console: Console, verdict: dict, metrics: dict, trace_id: str) -> None:
    body = Text()
    body.append("✗ check FAILED\n", style="bold red")
    body.append(f"[{verdict.get('failure_type')}] ", style="red")
    body.append(verdict.get("reason", ""), style="white")
    body.append("\n")
    for d in verdict.get("details") or []:
        body.append(f"  - {d}\n", style="red")
    body.append(f"\nmeasured: {_m(metrics)}\n", style="dim")
    body.append(f"local trace: runs/{trace_id}.json", style="dim cyan")
    console.print(Panel(body, border_style="red", title="[bold red]failing run[/bold red]"))


def _diagnosis_panel(console: Console, att: dict, source_note: str = "") -> None:
    d = att.get("diagnosis")
    if not d:
        console.print(Panel(Text("no diagnosis", style="yellow"), border_style="yellow"))
        return
    body = Text()
    body.append("span      ", style="dim")
    body.append(f"{d.get('failing_span_id')}\n", style="bold white")
    body.append("type      ", style="dim")
    body.append(f"{d.get('failure_type')}\n", style="bold yellow")
    body.append("root cause ", style="dim")
    body.append(f"{d.get('root_cause')}\n", style="white")
    body.append("evidence   ", style="dim")
    body.append(f"{d.get('evidence')}\n", style="white")
    body.append("confidence ", style="dim")
    body.append(f"{d.get('confidence')}  ", style="white")
    body.append("[LLM proposal — the verdict is the hard check above]\n", style="italic dim")
    if source_note:
        body.append(f"\n{source_note}\n", style="dim magenta")
    llm = att.get("llm") or {}
    if llm:
        body.append(
            f"model={llm.get('model')} tokens={llm.get('total_tokens')} "
            f"({'REAL' if llm else 'n/a'})",
            style="dim",
        )
    console.print(Panel(body, border_style="yellow", title="[bold yellow]diagnosis[/bold yellow]"))


def _diff_panel(console: Console, diff_text: str, patch: dict | None) -> None:
    from medic.surgeon import colour_diff

    body = Text()
    if patch:
        body.append(f"field: {patch.get('field')}\n", style="bold white")
        body.append(f"why:   {patch.get('rationale')}\n", style="dim italic")
        body.append("\n")
    if diff_text:
        body.append_text(Text.from_markup(colour_diff(diff_text)))
    else:
        body.append("(no diff)", style="dim")
    console.print(Panel(body, border_style="blue", title="[bold blue]medic.yaml patch[/bold blue]"))


def _verify_table(console: Console, vr: dict) -> None:
    t = Table(show_header=True, header_style="bold", box=None)
    t.add_column("split")
    t.add_column("task")
    t.add_column("result")
    t.add_column("steps", justify="right")
    t.add_column("tokens", justify="right")
    t.add_column("reason")

    rows = []
    if vr.get("train"):
        rows.append(vr["train"])
    rows.extend(vr.get("heldout") or [])
    for r in rows:
        ok = r.get("passed")
        t.add_row(
            r.get("split", ""),
            r.get("task_id", ""),
            "[green]PASS[/green]" if ok else "[red]FAIL[/red]",
            str(r.get("steps", "-")),
            str(r.get("total_tokens", "-")),
            (r.get("reason") or "")[:60],
        )
    console.print(Panel(t, border_style="green", title="[bold]verification (train + held-out)[/bold]"))


def run_heal_ui(
    bug: str,
    trace_id: str | None = None,
    apply_patch: bool = False,
    mode: Literal["scripted", "real"] = "scripted",
    max_attempts: int = 3,
    console: Console | None = None,
) -> bool:
    from medic.loop import heal as run_heal

    console = console or Console()

    def on_event(event: str, payload: dict) -> None:
        if event == "before_run":
            _fail_panel(console, payload["verdict"], payload["metrics"], payload["trace_id"])
        elif event == "already_green":
            console.print(
                Panel(
                    Text(f"no bug to fix — the check already passes\n{_m(payload['metrics'])}",
                         style="green"),
                    border_style="green",
                    title="[bold green]already healthy[/bold green]",
                )
            )
        elif event == "diagnosis":
            console.print(f"\n[bold cyan]── attempt {payload['attempt']} ──[/bold cyan]")
            _diagnosis_panel(console, {"diagnosis": payload["diagnosis"]})
        elif event == "fallback":
            console.print(Panel(Text(payload["reason"], style="yellow"),
                                border_style="yellow", title="[bold yellow]fallback[/bold yellow]"))
        elif event == "diff":
            _diff_panel(console, payload.get("diff") or "", payload.get("patch"))
        elif event == "verify":
            _verify_table(console, payload["verify"])
        elif event == "healed":
            console.print(
                Panel(
                    Text.from_markup(
                        f"[bold green]HEALED[/bold green]\nbug: {bug}\n"
                        f"train + every held-out task pass\n"
                        + ("patch written to medic.yaml\n" if apply_patch
                           else "patch held in memory (re-run with --apply to write it)\n")
                    ),
                    border_style="green",
                    title="[bold green]verdict[/bold green]",
                )
            )

    _header(console, bug, mode)
    result = run_heal(
        bug=bug,
        trace_id=trace_id,
        apply_patch=apply_patch,
        mode=mode,
        max_attempts=max_attempts,
        on_event=on_event,
    )

    if not result.healed:
        body = Text()
        body.append("NEEDS A HUMAN\n", style="bold yellow")
        body.append(f"bug: {bug}\n", style="yellow")
        fatal = next((a for a in result.attempts if a.error), None)
        if fatal:
            body.append("\nblocked at attempt ", style="dim")
            body.append(f"{fatal.number}: ", style="bold")
            body.append(f"{fatal.error}\n", style="red")
        body.append(f"\n{len(result.attempts)} attempt(s) did not clear the held-out tasks\n",
                    style="yellow")
        body.append("medic.yaml left at the clean baseline", style="dim")
        console.print(Panel(body, border_style="yellow", title="[bold yellow]verdict[/bold yellow]"))
    return result.healed