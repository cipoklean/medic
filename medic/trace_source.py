"""Trace loading — neatlogs read API first, local JSON always.

Medic must work when the vendor does not. `load_trace` tries the neatlogs
Public API and falls back to `runs/<run_id>.json` on ANY failure, then
normalises both into one `Trace` so nothing downstream knows or cares which
source answered.

The fallback is not defensive padding. A heal that dies because a read token
is missing or the dashboard is down is a heal that breaks on demo day, and the
whole product claim is that a heal is reproducible.

Auth: the SDK ingest key (`NEATLOGS_API_KEY`) CANNOT read the API — it only
writes. Reads need a service-account Bearer token (`NEATLOGS_TOKEN`) plus an
`x-project-id` header. With neither, we log once and stay on the local file.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from patient.config import ROOT, get, neatlogs_read_creds
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


class Trace(BaseModel):
    run_id: str
    source: str = "local"           # "neatlogs" | "local"
    workflow: str = ""
    tags: list[str] = Field(default_factory=list)
    spans: list[Span] = Field(default_factory=list)
    result: dict = Field(default_factory=dict)
    neatlogs_trace_url: str | None = None

    # ── views the LLM prompt and the checks actually read ──
    def errors(self) -> list[Span]:
        return [s for s in self.spans if s.error]

    def tool_spans(self) -> list[Span]:
        return [s for s in self.spans if s.kind == "TOOL"]

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


def _from_neatlogs(run_id: str) -> Trace | None:
    token, project = neatlogs_read_creds()
    if not (token and project):
        return None
    try:
        import httpx

        base = get("NEATLOGS_APP_URL", "https://app.neatlogs.com")
        headers = {"Authorization": f"Bearer {token}", "x-project-id": project}
        # List recent traces, then fetch the one matching our run id. The SDK
        # run id is not the neatlogs trace id, so we match on correlation.
        resp = httpx.get(
            f"{base.rstrip('/')}/api/v1/public/traces",
            headers=headers,
            params={"limit": 50},
            timeout=15.0,
        )
        if resp.status_code != 200:
            return None
        traces = (resp.json().get("data") or {}).get("traces") or []
        for item in traces:
            tags = item.get("tags") or []
            if run_id in json.dumps(tags) or item.get("id") == run_id:
                detail = httpx.get(
                    f"{base.rstrip('/')}/api/v1/public/traces/{item['id']}",
                    headers=headers,
                    timeout=15.0,
                )
                if detail.status_code != 200:
                    continue
                payload = detail.json().get("data") or {}
                spans = [
                    Span(
                        span_id=s.get("id", ""),
                        parent_id=s.get("parent_span_id"),
                        kind=s.get("kind", "UNKNOWN"),
                        name=s.get("name", ""),
                        input=s.get("input"),
                        output=s.get("output"),
                        error=s.get("error"),
                        prompt_tokens=(s.get("usage") or {}).get("prompt_tokens", 0),
                        completion_tokens=(s.get("usage") or {}).get("completion_tokens", 0),
                    )
                    for s in (payload.get("spans") or [])
                ]
                if spans:
                    return Trace(
                        run_id=run_id,
                        source="neatlogs",
                        workflow=payload.get("workflow_name", ""),
                        tags=tags,
                        spans=spans,
                        neatlogs_trace_url=f"{base.rstrip('/')}/traces/{item['id']}",
                    )
    except Exception:
        return None
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