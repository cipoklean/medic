"""DUAL TRACING.

Every span goes to TWO places:
  1. neatlogs  (the hosted product — the trace a judge looks at)
  2. runs/<run_id>.json  (our own recorder — works offline, survives an API
     outage, and is what Medic falls back to)

The local recorder is deliberately independent of neatlogs: if the SDK throws,
the run is still diagnosable. A heal that depends on the vendor being up is a
heal that breaks on demo day.
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import ROOT, get, neatlogs_ingest_key

RUNS_DIR = ROOT / "runs"

_NL_INITIALISED = False
_NL_INIT_ERROR: str | None = None


def init_neatlogs(workflow_name: str, tags: list[str] | None = None) -> bool:
    """Idempotent. Returns True if neatlogs is live for this process."""
    global _NL_INITIALISED, _NL_INIT_ERROR
    if _NL_INITIALISED:
        return True
    if _NL_INIT_ERROR:
        return False
    try:
        import neatlogs

        api_key = get("NEATLOGS_API_KEY")
        if not api_key:
            raise RuntimeError("NEATLOGS_API_KEY empty")
        neatlogs.init(
            api_key=api_key,
            workflow_name=workflow_name,
            tags=tags or [],
            capture_logs=False,
        )
        _NL_INITIALISED = True
        return True
    except Exception as exc:  # tracing must never kill a run
        _NL_INIT_ERROR = f"{type(exc).__name__}: {exc}"
        print(f"[tracing] neatlogs unavailable, local recorder only ({_NL_INIT_ERROR})")
        return False


def shutdown() -> None:
    try:
        import neatlogs

        neatlogs.flush()
        neatlogs.shutdown()
    except Exception:
        pass


def neatlogs_active() -> bool:
    return _NL_INITIALISED


class Recorder:
    """Local JSON span recorder. Mirrors what a trace viewer needs."""

    def __init__(self, run_id: str, workflow: str, tags: list[str] | None = None):
        self.run_id = run_id
        self.workflow = workflow
        self.tags = tags or []
        self.spans: list[dict[str, Any]] = []
        self.started = time.time()
        self._nl_depth = 0
        self._nl_stack: list[Any] = []

    # ── span emission ────────────────────────────────────────────────────
    def _emit(
        self,
        *,
        kind: str,
        name: str,
        span_input: Any,
        parent_id: str | None,
        started: float,
    ) -> dict:
        span = {
            "span_id": uuid.uuid4().hex[:16],
            "parent_id": parent_id,
            "trace_id": self.run_id,
            "kind": kind,
            "name": name,
            "input": span_input,
            "output": None,
            "error": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "started_at": started,
            "ended_at": None,
            "duration_ms": None,
        }
        self.spans.append(span)
        return span

    @contextmanager
    def span(
        self,
        kind: str,
        name: str,
        span_input: Any = None,
        tool_name: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> Iterator[dict]:
        """A span mirrored to BOTH sinks. Never raises."""
        parent = self.spans[-1]["span_id"] if self.spans else None
        started = time.time()
        rec = self._emit(kind=kind, name=name, span_input=span_input, parent_id=parent, started=started)
        rec["prompt_tokens"] = prompt_tokens
        rec["completion_tokens"] = completion_tokens
        rec["total_tokens"] = prompt_tokens + completion_tokens

        nl_cm = None
        if _NL_INITIALISED:
            try:
                import neatlogs

                kwargs = {"kind": kind}
                if tool_name:
                    kwargs["tool_name"] = tool_name
                nl_cm = neatlogs.trace(name, **kwargs)
                nl_cm.__enter__()
            except Exception:
                nl_cm = None
        try:
            yield rec
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            rec["ended_at"] = time.time()
            rec["duration_ms"] = round((rec["ended_at"] - started) * 1000, 2)
            if nl_cm is not None:
                try:
                    nl_cm.__exit__(None, None, None)
                except Exception:
                    pass

    # ── persistence ──────────────────────────────────────────────────────
    def write(self, extra: dict | None = None) -> Path:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        path = RUNS_DIR / f"{self.run_id}.json"
        payload = {
            "run_id": self.run_id,
            "workflow": self.workflow,
            "tags": self.tags,
            "started_at": self.started,
            "ended_at": time.time(),
            "neatlogs_active": _NL_INITIALISED,
            "spans": self.spans,
        }
        if extra:
            payload.update(extra)
        path.write_text(json.dumps(payload, indent=2, default=str))
        return path

    # ── metrics ──────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        done = [s for s in self.spans if s["ended_at"]]
        return {
            "run_id": self.run_id,
            "spans": len(self.spans),
            "steps": sum(1 for s in self.spans if s["kind"] == "TOOL"),
            "llm_calls": sum(1 for s in self.spans if s["kind"] == "LLM"),
            "prompt_tokens": sum(s["prompt_tokens"] for s in self.spans),
            "completion_tokens": sum(s["completion_tokens"] for s in self.spans),
            "total_tokens": sum(s["total_tokens"] for s in self.spans),
            "errors": sum(1 for s in self.spans if s["error"]),
            "latency_ms": round((time.time() - self.started) * 1000, 2),
        }

    def est_cost_usd(self) -> float:
        """Measured-token estimate. Rates are an explicit table, not a guess —
        update if you switch model."""
        return round(
            self.metrics()["prompt_tokens"] / 1_000_000 * 3.00
            + self.metrics()["completion_tokens"] / 1_000_000 * 15.00,
            6,
        )


def new_run(workflow: str, tags: list[str] | None = None) -> Recorder:
    return Recorder(uuid.uuid4().hex[:16], workflow, tags)