"""A deterministic, offline stand-in for the LLM.

Two jobs:
  1. Prove the plumbing (agent -> tools -> trace) without a key or a network.
  2. Make every bug REPRODUCIBLE. A demo that fails only sometimes is not a
     demo, and "heal it, twice in a row" is in the definition of done.

It behaves like a competent-but-literal agent: it obeys whatever medic.yaml
says. When the prompt stops naming the stop rule, it keeps searching — which
is exactly bug 3, and exactly the thing Medic has to fix in the prompt.
"""
from __future__ import annotations

import json
import re
import types


class _Msg:
    def __init__(self, content=None, tool_calls=None):
        self.role = "assistant"
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=True):
        d: dict = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {
                    "id": t.id,
                    "type": "function",
                    "function": {"name": t.function.name, "arguments": t.function.arguments},
                }
                for t in self.tool_calls
            ]
        return d


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _Call:
    def __init__(self, name, arguments, i):
        self.id = f"call_{i}"
        self.function = _Fn(name, arguments)


def _resp(msg):
    usage = types.SimpleNamespace(prompt_tokens=120, completion_tokens=35)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=usage)


class ScriptedLLM:
    """OpenAI-shaped client. Injected wherever a real one would go.

    `max_searches` and `emit_prose_expression` exist so the SAME loop produces
    a good run and a broken one, with no code change — the difference comes
    from medic.yaml (prompt + tool descriptions).
    """

    def __init__(self, max_searches: int = 2, emit_prose_expression: bool = False,
                 ignore_evidence: bool = False, broken_json: bool = False):
        self.max_searches = max_searches
        self.emit_prose_expression = emit_prose_expression
        self.ignore_evidence = ignore_evidence
        self.broken_json = broken_json
        self.searches = 0
        self.fetched: list[str] = []
        self._calls = 0
        self.chat = types.SimpleNamespace(completions=self)

    # ── OpenAI surface ──────────────────────────────────────────────────
    def create(self, **kwargs):
        self._calls += 1
        messages = kwargs.get("messages", [])
        last = next((m for m in reversed(messages) if m.get("role") == "tool"), None)
        payload = json.loads(last["content"]) if last else {}

        if last is None:
            if self.searches < self.max_searches:
                self.searches += 1
                query = self._query_for(messages)
                return _resp(
                    _Msg(tool_calls=[_Call("web_search", json.dumps({"query": query}), self._calls)])
                )
            return _resp(_Msg(content="I could not find an answer."))

        if "results" in payload:
            if payload["results"] and self.fetched:
                return self._answer_or_calculate()
            if payload["results"]:
                url = payload["results"][0]["url"]
                self.fetched.append(url)
                return _resp(
                    _Msg(tool_calls=[_Call("fetch_page", json.dumps({"url": url}), self._calls)])
                )
            if self.searches < self.max_searches:
                self.searches += 1
                return _resp(
                    _Msg(
                        tool_calls=[
                            _Call("web_search", json.dumps({"query": self._query_for(messages, alt=True)}), self._calls)
                        ]
                    )
                )
            return _resp(_Msg(content="I could not find an answer."))

        if "text" in payload:
            return self._answer_or_calculate(payload["text"])

        return self._answer_or_calculate()

    # ── behaviour ───────────────────────────────────────────────────────
    def _query_for(self, messages, alt: bool = False) -> str:
        """Map the question onto a fixture query. Fixture-backed, so the
        scripted agent can only find things we actually stored."""
        text = " ".join(str(m.get("content", "")) for m in messages).lower()
        table = {
            "250 widget": ("widget price", "widget bulk discount"),
            "widget": ("widget price", "acme widget order"),
            "gadget": ("blue gadget price", "orbit server price"),
            "blue gadget": ("blue gadget price", "orbit server price"),
            "server": ("orbit server price", "blue gadget price"),
            "panel": ("helio panel price", "widget price"),
            "solar": ("helio panel price", "widget price"),
        }
        for key, (first, second) in table.items():
            if key in text:
                return second if alt else first
        return "widget price" if not alt else "orbit server price"

    def _answer_or_calculate(self, page_text: str | None = None):
        expr = self._expression(page_text)
        if expr is None:
            return _resp(
                _Msg(
                    content=(
                        f"Based on the evidence I fetched, the answer is $28,250.00. "
                        f"See {self.fetched[0] if self.fetched else 'the sources listed'}."
                    )
                )
            )
        arg = expr if self.emit_prose_expression else json.dumps({"expression": expr})
        return _resp(_Msg(tool_calls=[_Call("calculator", arg, self._calls)]))

    def _expression(self, page_text: str | None) -> str | None:
        if self.emit_prose_expression:
            return "the unit price times the quantity minus twelve percent"
        if page_text and "128.40" in page_text and "12%" in page_text:
            return "(128.40*250)*(1-0.12)"
        if page_text and "450.00" in page_text:
            return "450.00*3"
        if page_text and "1,250.00" in page_text:
            return "1250*4"
        if page_text and "79.99" in page_text:
            return "79.99*2"
        return None


def extract_numbers(text: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"-?[\d,]+\.?\d*", text)]