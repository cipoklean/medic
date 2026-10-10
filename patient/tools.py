"""Patient agent tools — 100% FIXTURE-BACKED.

Nothing here touches the network. A query maps to a stored JSON file under
fixtures/search/, a URL to fixtures/pages/. An unknown key returns an explicit
"no results" object rather than an exception, so a wrong-argument bug shows up
as a WRONG ANSWER (which a hard check catches) instead of a crash.

`--live` is not implemented on purpose: an agent demo that depends on a third
party being up is a demo that fails on camera.
"""
from __future__ import annotations

import ast
import json
import operator
from pathlib import Path
from typing import Any, Callable

from .config import ROOT

FIXTURES = ROOT / "fixtures"
SEARCH_DIR = FIXTURES / "search"
PAGES_DIR = FIXTURES / "pages"

# Bug-2 switch: set to True to make fetch_page return slightly-broken JSON.
_BROKEN_JSON = False

_OPS: dict[type[ast.AST], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


def _load_search(query: str) -> dict | None:
    path = SEARCH_DIR / f"{_slug(query)}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _load_page(url: str) -> str | None:
    name = _slug(url.rstrip("/").split("//")[-1])
    for ext in (".html", ".txt"):
        path = PAGES_DIR / f"{name}{ext}"
        if path.exists():
            return path.read_text()
    return None


# ── JSON Schema for every tool (used by hard checks AND by the agent) ────
TOOL_SCHEMAS: dict[str, dict] = {
    "web_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1, "maxLength": 200},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "fetch_page": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    "calculator": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "pattern": r"^[0-9\.\s\+\-\*/%\(\)]+$",
                "description": "A bare arithmetic expression, e.g. \"(128.4 * 3) + 20\"",
            }
        },
        "required": ["expression"],
        "additionalProperties": False,
    },
}


def tool_definitions(descriptions: dict[str, str]) -> list[dict]:
    """Build OpenAI-style tool defs from medic.yaml descriptions.

    The DESCRIPTION is the only thing Medic changes for bug 1 — so it must be
    the only thing that reaches the model.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": descriptions.get(name, ""),
                "parameters": schema,
            },
        }
        for name, schema in TOOL_SCHEMAS.items()
    ]


# ── the three tools ──────────────────────────────────────────────────────
def web_search(query: str) -> dict:
    data = _load_search(query)
    if data is None:
        return {
            "query": query,
            "results": [],
            "note": "no results — try a different query",
        }
    return data


def fetch_page(url: str) -> dict:
    body = _load_page(url)
    if body is None:
        return {"url": url, "found": False, "text": "", "note": "page not in fixtures"}
    payload = {"url": url, "found": True, "text": body}
    if _BROKEN_JSON:
        raw = json.dumps(payload)
        # Slightly broken: a trailing comma before the closing brace.
        return _BrokenJson(raw[:-1] + ",}")
    return payload


def calculator(expression: str) -> dict:
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError) as exc:
        return {"expression": expression, "error": f"not a valid expression: {exc}"}

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("only numbers are allowed")
        if isinstance(node, ast.BinOp):
            op = _OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"operator {type(node.op).__name__} not allowed")
            return op(walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _OPS.get(type(node.op))
            if op is None:
                raise ValueError("unsupported unary operator")
            return op(walk(node.operand))
        raise ValueError(f"{type(node).__name__} not allowed in an expression")

    try:
        value = walk(tree)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        return {"expression": expression, "error": str(exc)}
    return {"expression": expression, "result": value}


class _BrokenJson:
    """A string that claims to be JSON but is not.

    Bug 2 needs a tool that returns malformed output so the agent's parse
    blows up. Returning a plain str keeps the tool signature honest — the
    agent must json.loads() its output, and that is exactly where it fails.
    """

    def __init__(self, text: str):
        self._text = text

    def __repr__(self) -> str:
        return self._text

    def __str__(self) -> str:
        return self._text


def set_broken_json(enabled: bool) -> None:
    """Test/demo hook for bug 2."""
    global _BROKEN_JSON
    _BROKEN_JSON = enabled


def dispatch(name: str, args: dict) -> Any:
    fn = {"web_search": web_search, "fetch_page": fetch_page, "calculator": calculator}[name]
    return fn(**args)


def cited_urls_in(text: str) -> set[str]:
    """Every http(s) URL mentioned in a string — used by the bug-4 check."""
    import re

    return set(re.findall(r"https?://[^\s\)\]\"'<>]+", text))