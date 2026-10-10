#!/usr/bin/env python
"""What can the Gemini key actually reach, and what does it cost?

The build prompt said: pin a model Google currently serves, don't assume
gemini-2.5-flash. Google's model IDs move fast and a retired ID fails at call
time rather than at setup, which is the worst moment to find out.

Lists reachable models, then probes the cheapest current flash model for real
tool_calls. Writes evidence/gemini_models.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patient.config import load_env, get

load_env()

import httpx

TOOLS = [{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for information.",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]},
    },
}]

ASK = "Find the current price of a standard widget. Use the search tool."


def main() -> int:
    base = get("LLM_BASE_URL_GEMINI",
               "https://generativelanguage.googleapis.com/v1beta/openai")
    key = get("LLM_API_KEY_GEMINI")
    if not key:
        print("LLM_API_KEY_GEMINI is not set — nothing to list.")
        return 1

    # 1. What can this key reach?
    listed: list[str] = []
    try:
        r = httpx.get(f"{base.rstrip('/openai')}/models",
                      headers={"x-goog-api-key": key}, timeout=40)
        if r.status_code == 200:
            data = r.json().get("data") or r.json().get("models") or []
            listed = [m.get("id") or m.get("name", "") for m in data]
            listed = [m.replace("models/", "") for m in listed if m]
        else:
            print(f"models list: HTTP {r.status_code} {r.text[:120]}")
    except Exception as exc:
        print(f"models list failed: {type(exc).__name__}: {exc}"[:200])

    print(f"reachable via this key: {len(listed)} models")
    flash = [m for m in listed if "flash" in m.lower()]
    for m in sorted(flash)[:12]:
        print(f"    {m}")

    # 2. Probe the cheapest current flash, plus 2.5-flash for the record.
    candidates = []
    for m in sorted(flash):
        # prefer the newest low-numbered flash-lite, then flash
        candidates.append(m)
    if "gemini-2.5-flash" not in candidates:
        candidates.append("gemini-2.5-flash")
    candidates = candidates[:4] + ["gemini-2.5-flash"]
    seen: set[str] = set()
    ordered = [c for c in candidates if not (c in seen or seen.add(c))]

    print(f"\nprobing for real tool_calls: {ordered}")
    results = {}
    verified = None
    for model in ordered:
        body = {"model": model,
                "messages": [{"role": "user", "content": ASK}],
                "tools": TOOLS, "temperature": 0, "max_tokens": 512}
        try:
            r = httpx.post(f"{base.rstrip('/')}/chat/completions",
                           headers={"Authorization": f"Bearer {key}"},
                           json=body, timeout=60)
        except Exception as exc:
            results[model] = {"status": "ERROR", "detail": str(exc)[:160]}
            print(f"  FAIL {model:24} ERROR")
            continue
        if r.status_code != 200:
            msg = r.text[:160]
            results[model] = {"status": f"HTTP {r.status_code}", "detail": msg}
            print(f"  FAIL {model:24} HTTP {r.status_code}")
            continue
        d = r.json()
        tcs = (d["choices"][0]["message"].get("tool_calls") or [])
        u = d.get("usage", {}) or {}
        results[model] = {
            "status": "PASS" if tcs else "PROSE (no tool_calls)",
            "tools_called": [t["function"]["name"] for t in tcs],
            "prompt_tokens": u.get("prompt_tokens"),
            "completion_tokens": u.get("completion_tokens"),
            "cost": u.get("cost"),
        }
        flag = "PASS" if tcs else "FAIL"
        print(f"  {flag} {model:24} {results[model]['status']}")
        if tcs and verified is None:
            verified = model

    report = {
        "question": "Which Gemini model should the fallback pin, and does it call tools?",
        "base_url": base,
        "reachable_models": len(listed),
        "flash_models_available": sorted(flash)[:12],
        "probed": results,
        "recommended": verified,
        "disclosure": ("Only a model with status PASS is verified to emit "
                       "tool_calls. gemini-2.5-flash was probed explicitly and "
                       "is NOT assumed to work."),
    }
    out = Path(__file__).resolve().parents[1] / "evidence" / "gemini_models.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))

    print(f"\nRECOMMENDED: {verified or 'none verified'}")
    print(f"wrote {out}")
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
