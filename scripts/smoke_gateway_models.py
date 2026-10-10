#!/usr/bin/env python
"""Which gateway models actually emit tool_calls?

A model that answers a tool-using prompt in prose is USELESS as the patient: the
whole failure we demonstrate depends on the model calling tools. Untested models
are recorded as UNTESTED, never as pass or fail.

    .venv/bin/python scripts/smoke_gateway_models.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patient.config import load_env

load_env()

import httpx

TOOLS = [{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for information.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string",
                                     "description": "What to search for."}},
            "required": ["query"],
        },
    },
}, {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Evaluate an arithmetic expression.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string",
                                          "description": "e.g. 128.4 * 3"}},
            "required": ["expression"],
        },
    },
}]

# The full gateway model list. Anything not probed stays UNTESTED below.
MODELS = [
    "nova-micro",
    "nova-lite",
    "nova-pro",
    "nova-2-lite",
    "claude-haiku",
    "claude-sonnet-4.6",
    "claude-opus-4.6",
]

SYSTEM = ("You are a research agent. Use the tools to answer. "
          "calculator's expression argument must be a plain arithmetic "
          "expression such as \"128.4 * 3\".")

ASK = ("ACME Corp ordered 250 standard widgets at $128.40 each with a 10% "
       "volume discount. Use the tools, then give the final total.")


def probe(base: str, key: str, model: str, timeout: float = 90.0) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": ASK},
        ],
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 1024,
    }
    try:
        r = httpx.post(f"{base.rstrip('/')}/chat/completions",
                       headers={"Authorization": f"Bearer {key}"},
                       json=body, timeout=timeout)
    except Exception as exc:
        return {"status": "ERROR", "detail": f"{type(exc).__name__}: {exc}"[:200]}

    if r.status_code != 200:
        msg = r.text[:220]
        try:
            msg = r.json().get("error", {}).get("message", msg)[:220]
        except Exception:
            pass
        return {"status": f"HTTP {r.status_code}", "detail": msg}

    d = r.json()
    msg = d["choices"][0]["message"]
    tcs = msg.get("tool_calls") or []
    names = [tc["function"]["name"] for tc in tcs]
    args_ok, args_detail = None, None
    if tcs:
        try:
            raw = tcs[0]["function"].get("arguments")
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            args_ok = isinstance(parsed, dict)
            args_detail = json.dumps(parsed)[:160]
        except Exception as exc:
            args_ok = False
            args_detail = f"unparseable: {exc}"
    u = d.get("usage", {}) or {}
    return {
        "status": "PASS" if names else "PROSE (no tool_calls)",
        "tools_called": names,
        "arguments_valid_json": args_ok,
        "arguments": args_detail,
        "finish_reason": d["choices"][0].get("finish_reason"),
        "prompt_tokens": u.get("prompt_tokens"),
        "completion_tokens": u.get("completion_tokens"),
        "provider": (d.get("provider") or "").strip() or None,
    }


def main() -> int:
    from patient.config import get

    base = get("LLM_BASE_URL_LITELLM", "https://litellm.vision.aivar.app/v1")
    key = get("LLM_API_KEY_LITELLM")
    if not key:
        print("LLM_API_KEY_LITELLM is not set in .env — nothing to probe.")
        print("Add it, then re-run. No model is being reported as tested.")
        return 1

    print(f"gateway: {base}")
    print(f"probing {len(MODELS)} models for real tool_calls\n")

    results: dict[str, dict] = {}
    for model in MODELS:
        res = probe(base, key, model)
        results[model] = res
        flag = "PASS " if res.get("tools_called") else "FAIL "
        print(f"  {flag} {model:20} {res['status']}")
        if res.get("tools_called"):
            print(f"         called {res['tools_called']} args={res.get('arguments')}")
        elif res.get("detail"):
            print(f"         {res['detail'][:150]}")

    passed = [m for m, r in results.items() if r.get("tools_called")]
    failed = [m for m, r in results.items() if not r.get("tools_called")]

    report = {
        "question": "Which gateway models emit real tool_calls for a tool-using prompt?",
        "gateway": base,
        "probed": len(MODELS),
        "passed": passed,
        "not_passed": failed,
        "results": results,
        "disclosure": ("Only models in `passed` are verified to call tools. "
                       "A model listed in not_passed either errored or answered "
                       "in prose; it was NOT tuned and is not reported as "
                       "working. Any model not in `probed` is untested."),
    }
    out = Path(__file__).resolve().parents[1] / "evidence" / "gateway_tool_calling_smoke.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print(f"\nPASS: {passed or 'none'}")
    print(f"NOT PASSED: {failed or 'none'}")
    print(f"wrote {out}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
