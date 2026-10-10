"""Trace loading, neatlogs read API first, local JSON always.

RESOLVED BY EXPERIMENT (2026-10-10), not by reading their docs:

    GET https://app.neatlogs.com/api/traces/v3/<neatlogs-trace-id>
    Header: x-api-key: <NEATLOGS_API_KEY>          (the INGEST key)
    Optionally: x-neatlogs-doctor: v1
    -> 200 application/json, {trace fields..., "spans": [...]}

This CORRECTS an earlier claim of mine. Their auth page says ingest credentials
"do not authorize Public API reads", and I repeated that at CHECKPOINT 1. It is
true of the *versioned public API* (`/api/v1/public`, which returns 401
UNAUTHORIZED with every auth scheme tried: Bearer, x-api-key, both). But the
per-trace readback route `/api/traces/v3/<id>` accepts the ingest key, because
that is the route the SDK's own `neatlogs doctor --probe` uses internally.

So NEATLOGS_TOKEN / NEATLOGS_PROJECT_ID are NOT required. One key is enough.
The local-JSON fallback still exists for when neatlogs is unreachable, a heal
that dies because the vendor is down is a heal that breaks on demo day.

Span shape (captured, not guessed):
  span_id, parent_span_id, traceId, node_name, node_type ("llm"/"tool"),
  status ("SUCCESS"/...), data (a PYTHON-REPR STRING, not JSON),
  span_metadata (also a repr string, holds token_usage), createdAt/updatedAt.
`data` and `span_metadata` come back repr-encoded, so they are parsed with
ast.literal_eval, a plain json.loads would raise on every span.
"""
from __future__ import annotations

import ast
import json
from typing import Any

from pydantic import BaseModel, Field

from patient.config import ROOT, get
from patient.tracing import RUNS_DIR

PUBLIC_API = "https://app.neatlogs.com/api/v1/public"


class Span(BaseModel):
    span_id: str
    parent_id: str | None = None
    kind: str = "UNKNOWN"
    name: str = ""
    input: Any = None
    output: Any = None
    error: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: float | None = None
    status: str | None = None


class Trace(BaseModel):
    run_id: str
    source: str = "local"           # "neatlogs" | "local"
    workflow: str = ""
    tags: list[str] = Field(default_factory=list)
    spans: list[Span] = Field(default_factory=list)
    result: dict = Field(default_factory=dict)
    neatlogs_trace_url: str | None = None
    neatlogs_trace_id: str | None = None
    totals: dict = Field(default_factory=dict)

    # ── views the LLM prompt and the checks actually read ──
    def errors(self) -> list[Span]:
        return [s for s in self.spans if s.error]

    def tool_spans(self) -> list[Span]:
        # neatlogs reports tool spans as node_type "tool_call", our local
        # recorder as "TOOL". An exact == "TOOL" test silently returns [] for
        # every live trace, which quietly disarms the diagnosis.
        return [s for s in self.spans if s.kind.upper() in ("TOOL", "TOOL_CALL")]

    def find(self, span_id: str) -> Span | None:
        return next((s for s in self.spans if s.span_id == span_id), None)

    def to_compact_tree(self, max_output: int = 400) -> str:
        """A compact, indented span tree with long outputs truncated.

        Truncation matters: a real tool output can be a page of HTML, and
        sending that to a diagnosing model wastes the entire context on one
        span. The full trace is still on disk.
        """
        by_parent: dict[str | None, list[Span]] = {}
        for span in self.spans:
            by_parent.setdefault(span.parent_id, []).append(span)

        lines: list[str] = []

        def trunc(value: Any) -> str:
            if value is None:
                return "null"
            text = value if isinstance(value, str) else json.dumps(value, default=str)
            text = " ".join(text.split())
            if len(text) > max_output:
                text = text[:max_output] + f"… (+{len(text) - max_output} chars)"
            return text

        def walk(parent: str | None, depth: int) -> None:
            for span in by_parent.get(parent, []):
                pad = "  " * depth
                head = f"{pad}[{span.kind}] {span.name or span.span_id}"
                if span.kind == "TOOL":
                    head += f"  args={trunc(span.input)}"
                lines.append(head)
                if span.output is not None:
                    lines.append(f"{pad}    -> {trunc(span.output)}")
                if span.error:
                    lines.append(f"{pad}    !! ERROR {trunc(span.error)}")
                if span.total_tokens:
                    lines.append(f"{pad}    tokens={span.total_tokens}")
                walk(span.span_id, depth + 1)

        walk(None, 0)
        return "\n".join(lines)


def _from_local(run_id: str) -> Trace | None:
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return Trace(
        run_id=run_id,
        source="local",
        workflow=data.get("workflow", ""),
        tags=data.get("tags", []),
        spans=[Span(**{k: v for k, v in s.items() if k in Span.model_fields})
               for s in data.get("spans", [])],
        result=data.get("result", {}),
    )


def _repr_to_obj(value):
    """neatlogs returns `data` / `span_metadata` as PYTHON REPR STRINGS.

    A plain json.loads raises on every span because repr uses single quotes.
    """
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return {}


def _span_from_neatlogs(raw: dict) -> Span:
    """Map one neatlogs span onto our Span model.

    Field names differ from the local recorder: tool I/O lives under
    `input_value` / `output_value`, NOT `input` / `output`. Reading the wrong
    keys produces spans that look empty, which would silently starve the
    diagnosis of exactly the evidence it needs.
    """
    data = _repr_to_obj(raw.get("data")) or {}
    meta = _repr_to_obj(raw.get("span_metadata")) or {}
    usage = meta.get("token_usage") or data.get("token_usage") or {}
    status = raw.get("status") or ""
    kind = (raw.get("node_type") or "UNKNOWN").upper()

    span_in = data.get("input_value") or data.get("input") or data.get("input.value")
    span_out = data.get("output_value") or data.get("output") or data.get("output.value")
    if kind == "TOOL_CALL" and not span_in:
        # A tool span with no recorded arguments is still worth surfacing with
        # its name, so the diagnosis can name the span even without payload.
        span_in = data.get("tool_name") or meta.get("tool_name")

    error = None
    err_msg = data.get("error_message")
    if err_msg:
        error = err_msg
    elif status and status.upper() not in ("SUCCESS", "OK", "UNSET", ""):
        error = f"status={status}"

    return Span(
        span_id=raw.get("span_id", ""),
        parent_id=raw.get("parent_span_id"),
        kind=(raw.get("node_type") or "UNKNOWN"),
        name=raw.get("node_name", ""),
        input=span_in,
        output=span_out,
        error=error,
        prompt_tokens=int(usage.get("input") or data.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("output") or data.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total") or data.get("total_tokens") or 0),
        duration_ms=data.get("duration_ms"),
        status=status,
    )


def _from_neatlogs(trace_id: str) -> Trace | None:
    key = get("NEATLOGS_API_KEY")
    if not (key and trace_id):
        return None
    try:
        import httpx

        base = get("NEATLOGS_APP_URL", "https://app.neatlogs.com").rstrip("/")
        resp = httpx.get(
            f"{base}/api/traces/v3/{trace_id}",
            headers={"x-api-key": key, "x-neatlogs-doctor": "v1"},
            timeout=20.0,
        )
        if resp.status_code != 200:
            return None
        payload = resp.json()
        spans = [_span_from_neatlogs(s) for s in (payload.get("spans") or [])]
        if not spans:
            return None
        return Trace(
            run_id=trace_id,
            source="neatlogs",
            workflow=payload.get("workflowName", ""),
            tags=[t if isinstance(t, str) else str(t) for t in (payload.get("tags") or [])],
            spans=spans,
            neatlogs_trace_id=payload.get("_id", trace_id),
            neatlogs_trace_url=f"{base}/traces/{payload.get('_id', trace_id)}",
            totals={
                "prompt_tokens": payload.get("promptTokens", 0),
                "completion_tokens": payload.get("completionTokens", 0),
                "total_tokens": payload.get("totalTokensUsed", 0),
                "span_count": payload.get("spanCount", 0),
                "tool_calls": payload.get("toolCalls", 0),
                "llm_calls": payload.get("llmCalls", 0),
                "latency_ms": payload.get("latency", 0),
            },
        )
    except Exception:
        return None


def load_trace(run_id: str, prefer: str = "neatlogs") -> Trace | None:
    """neatlogs first, local always. Returns None only if neither has it."""
    if prefer == "neatlogs":
        trace = _from_neatlogs(run_id)
        if trace:
            return trace
    return _from_local(run_id)


def latest_run_id() -> str | None:
    files = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    return files[-1].stem if files else None