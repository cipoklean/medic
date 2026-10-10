"""A deterministic, offline stand-in for the LLM.

It is NOT a dumb mock. It READS medic.yaml and behaves the way a literal,
obedient model would given that configuration:

  * calculator description is vague  -> passes PROSE as the expression value
  * system prompt has no stop rule   -> keeps going after it could answer
  * prompt says "cite what you know" -> cites a URL it never fetched
  * retry_on_parse_error is true     -> re-asks after a malformed payload

That is the whole point: the SAME loop then fails or passes purely because of
a config change, which is exactly what Medic is supposed to fix. A mock that
ignored the config would make every bug fake and the demo would prove nothing.

Two properties make the hard checks meaningful:

  * the final answer is built from the calculator's ACTUAL return value, so
    "answer == known value" is a real end-to-end assertion rather than a
    constant. A different question genuinely produces a different answer.
  * the tool-argument failure for a vague description is emitted as VALID JSON
    carrying a bad VALUE (`{"expression": "the unit price times ..."}`), so
    jsonschema is what rejects it. Emitting bare prose would instead blow up
    in json.loads and the bug would masquerade as a parse error.

Deterministic by construction: no randomness, no clock, no network. The same
config always produces the same run — which is what "heal it twice in a row"
requires.
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


def _resp(msg, prompt_tokens=120, completion_tokens=35):
    usage = types.SimpleNamespace(
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=usage)


# A URL in NO fixture. Inventing it is the bug-4 failure.
INVENTED_URL = "https://widget-facts.example.org/pricing-2024"

# Prose the model passes when the calculator description never shows an
# example. It is a legal JSON string and a legal KEY — only the VALUE is wrong,
# so jsonschema is the thing that catches it.
PROSE_EXPRESSION = "the unit price times the quantity minus twelve percent"


class ScriptedLLM:
    """OpenAI-shaped client. Injected wherever a real one would go."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        prompt = str(self.config.get("system_prompt", ""))
        calc_desc = str(
            (self.config.get("tools") or {}).get("calculator", {}).get("description", "")
        )

        # ── read the config the way a literal model would ──
        self.stop_rule_present = not lacks_stop_rule(prompt)
        self.emit_prose = is_vague(calc_desc)
        self.cite_without_evidence = "cite what you know" in prompt.lower()
        self.retry_allowed = bool(self.config.get("retry_on_parse_error", False))

        # A prompt without a stop rule has no reason to stop after one answer.
        self.search_budget = 2 if self.stop_rule_present else 8

        self.searches = 0
        self.fetched: list[str] = []
        self._queries_used: list[str] = []
        self.computed: float | None = None
        self.computed_expression: str | None = None
        self.invented = False
        self.retried_after_parse_error = False
        self.answered = False
        self._calls = 0
        self.chat = types.SimpleNamespace(completions=self)

    # ── OpenAI surface ──────────────────────────────────────────────────
    def create(self, **kwargs):
        self._calls += 1
        messages = kwargs.get("messages", [])

        # A user turn asking for a single JSON object = a retry after a parse
        # error. Honouring it is exactly what retry_on_parse_error buys.
        last_user = str(
            next((m for m in reversed(messages) if m.get("role") == "user"), {}).get("content", "")
        )
        if "not valid JSON" in last_user:
            self.retried_after_parse_error = True
            return self._call_calculator(self._expression_for_question(messages), prose=False)

        last = next((m for m in reversed(messages) if m.get("role") == "tool"), None)
        if last is None:
            return self._search(self._query_for(messages))

        try:
            payload = json.loads(last["content"])
        except json.JSONDecodeError:
            return self._on_malformed_tool_output()

        # A tool may return malformed JSON that the agent re-serialised as a
        # plain string. That IS the bug-2 signal, not a crash.
        if isinstance(payload, str):
            return self._on_malformed_tool_output()

        if "results" in payload:
            return self._on_search_results(payload, messages)
        if "text" in payload:
            # A page was read. WITHOUT a stop rule a literal model does not
            # treat that as "enough" — it goes back for more sources. That
            # extra searching is bug 3, so it must not be short-circuited by
            # having the page text available.
            return self._on_page(payload.get("text", ""), messages)
        if "result" in payload:
            return self._on_calculator(payload)
        if "error" in payload:
            return self._on_tool_error(payload)
        return self._final()

    def _on_malformed_tool_output(self):
        """The tool lied. Retry if the config allows it, else give up."""
        if self.retry_allowed:
            self.retried_after_parse_error = True
            return _resp(
                _Msg(
                    tool_calls=[
                        _Call(
                            "calculator",
                            json.dumps({"expression": self.computed_expression or "(128.40*250)*(1-0.12)"}),
                            self._calls,
                        )
                    ]
                )
            )
        return _resp(_Msg(content="I could not complete this calculation."))

    # ── behaviour ───────────────────────────────────────────────────────
    def _search(self, query):
        self.searches += 1
        self._queries_used.append(query)
        return _resp(
            _Msg(tool_calls=[_Call("web_search", json.dumps({"query": query}), self._calls)])
        )

    def _on_search_results(self, payload, messages):
        results = payload.get("results") or []
        if not results:
            if self.searches < self.search_budget:
                return self._search(self._query_for(messages, alt=True))
            return self._final()
        url = results[0]["url"]
        if url not in self.fetched:
            self.fetched.append(url)
            return _resp(
                _Msg(tool_calls=[_Call("fetch_page", json.dumps({"url": url}), self._calls)])
            )
        # Already read every candidate page. With a stop rule that is enough
        # to answer; without one, a literal model keeps looking for MORE
        # sources, and that is the whole point of bug 3.
        if self.stop_rule_present:
            return self._on_page_after_search(messages)
        if self.searches < self.search_budget:
            return self._search(self._query_for(messages, alt=True))
        return self._final()

    def _on_page_after_search(self, messages):
        expr = self._expression_for_question(messages)
        if expr is None:
            return self._final()
        return self._call_calculator(expr, prose=self.emit_prose)

    def _on_page(self, text: str, messages=None):
        expr = expression_for_question(self._question_text(messages)) or expression_for(text)
        if expr is None:
            return self._final()
        if self.stop_rule_present:
            return self._call_calculator(expr, prose=self.emit_prose)
        # No stop rule: reading one page is not permission to stop. Keep
        # searching until the budget is gone, which is the bug.
        if self.searches < self.search_budget:
            return self._search(self._alt_query_for_last())
        return self._call_calculator(expr, prose=self.emit_prose)

    def _question_text(self, messages) -> str:
        """The user's actual question, with tool output stripped out.

        Tool payloads contain prices too; including them would let a page's
        numbers masquerade as the question's.
        """
        if not messages:
            return ""
        return " ".join(
            str(m.get("content", ""))
            for m in messages
            if m.get("role") in ("user", "system")
        ).lower()

    def _alt_query_for_last(self) -> str:
        """Pick a DIFFERENT query, so the extra searching is visibly extra
        work rather than the same request repeated."""
        alternates = ["widget bulk discount", "acme widget order", "orbit server price"]
        for q in alternates:
            if q not in self._queries_used:
                self._queries_used.append(q)
                return q
        return "orbit server price"

    def _call_calculator(self, expr: str | None, prose: bool):
        if expr is None:
            return self._final()
        self.computed_expression = expr
        if prose:
            # Valid JSON, right key, WRONG value — jsonschema catches this.
            return _resp(
                _Msg(tool_calls=[_Call("calculator", json.dumps({"expression": PROSE_EXPRESSION}), self._calls)])
            )
        return _resp(
            _Msg(tool_calls=[_Call("calculator", json.dumps({"expression": expr}), self._calls)])
        )

    def _on_calculator(self, payload):
        """The answer comes from the tool's REAL return value."""
        self.computed = float(payload["result"])
        return self._final()

    def _on_tool_error(self, payload):
        # calculator rejected the expression. Retry if allowed, else give up.
        if self.retry_allowed:
            self.retried_after_parse_error = True
            return _resp(
                _Msg(
                    tool_calls=[
                        _Call(
                            "calculator",
                            json.dumps({"expression": self.computed_expression or "(128.40*250)*(1-0.12)"}),
                            self._calls,
                        )
                    ]
                )
            )
        return _resp(_Msg(content="I could not complete this calculation."))

    def _final(self):
        self.answered = True
        amount = f"${self.computed:,.2f}" if self.computed is not None else "an unknown amount"
        if self.emit_prose and self.computed is None:
            amount = "an amount I could not compute"

        if self.cite_without_evidence and not self.invented:
            self.invented = True
            return _resp(
                _Msg(content=f"The total is {amount}. See {INVENTED_URL} for the underlying figures.")
            )
        cited = self.fetched[0] if self.fetched else ""
        text = f"The total is {amount}."
        if cited:
            text += f" Source: {cited}"
        return _resp(_Msg(content=text))

    def _expression_for_question(self, messages):
        return expression_for_question(self._question_text(messages))

    def _query_for(self, messages, alt: bool = False) -> str:
        text = " ".join(str(m.get("content", "")) for m in messages).lower()
        ordered = [
            ("250 widget", "widget price", "acme widget order"),
            ("volume discount", "widget price", "widget bulk discount"),
            ("re-price", "widget price", "acme widget order"),
            ("case", "blue gadget price", "widget price"),
            ("gadget", "blue gadget price", "orbit server price"),
            ("three orbit", "orbit server price", "blue gadget price"),
            ("three months", "orbit server price", "blue gadget price"),
            ("server", "orbit server price", "blue gadget price"),
            ("panel", "helio panel price", "widget price"),
            ("solar", "helio panel price", "widget price"),
            ("unit", "widget price", "blue gadget price"),
            ("widget", "widget price", "acme widget order"),
        ]
        for key, first, second in ordered:
            if key in text:
                return second if alt else first
        return "orbit server price" if alt else "widget price"


# ── config-reading helpers (the whole point of this module) ──────────────
def lacks_stop_rule(prompt: str) -> bool:
    low = prompt.lower()
    has_stop = any(
        phrase in low
        for phrase in (
            "stop rule",
            "as soon as you can answer",
            "stop calling tools",
            "never make more than",
        )
    )
    return not has_stop


def is_vague(description: str) -> bool:
    """A description that never shows an example cannot pin the arg format."""
    low = description.lower()
    return not any(t in low for t in ("expression", "e.g", "example", "plain arithmetic"))


def expression_for_question(text: str) -> str | None:
    """The expression a competent agent would compute FOR THIS QUESTION.

    The question is the authority. A page may list several prices, and
    inferring the expression from page text alone computes the wrong thing for
    three of our tasks at once (a widget page carries both a discounted and an
    undiscounted figure). The page is only used to confirm the numbers exist.
    """
    low = text.lower()
    # "before the discount is applied" and "after the discount" differ only by
    # a negation. Keying on the mere PRESENCE of "discount" computes the
    # discounted figure for a question that explicitly asked for the list
    # price, so the negation has to be read, not just the keyword.
    wants_discount = "discount" in low and not any(
        neg in low
        for neg in ("before the", "without the", "prior to", "not applied", "undiscounted")
    )
    if "250 widget" in low or "re-price" in low or "unit price" in low:
        return "(128.40*250)*(1-0.12)" if wants_discount else "128.40*250"
    if "volume discount" in low or "after the discount" in low:
        return "(128.40*250)*(1-0.12)"
    if "four helio" in low or "4 panel" in low or "panel cost" in low:
        return "1250*4"
    if "one helio" in low or "list price of one" in low:
        return "1250*1"
    if "three orbit" in low or "three months" in low:
        return "450.00*3"
    if "one case" in low or "case cost" in low:
        return "169.98-(79.99*2)"
    if "in cents" in low or "one unit cost" in low:
        return "128.40*100"
    if "two blue" in low:
        return "79.99*2"
    return None


def expression_for(text: str) -> str | None:
    """Fallback when the question is unrecognised: infer from page contents."""
    if not text:
        return None
    if "128.40" in text and "12%" in text:
        return "(128.40*250)*(1-0.12)"
    if "1,250.00" in text:
        return "1250*4"
    if "450.00" in text:
        return "450.00*3"
    if "79.99" in text:
        return "79.99*2"
    if "128.40" in text:
        return "128.40*250"
    return None


def extract_numbers(text: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"-?[\d,]+\.?\d*", text)]