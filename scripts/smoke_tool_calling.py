#!/usr/bin/env python
"""Tool-calling smoke test: which models actually call tools?

A model that answers in prose despite a `tools` array is unusable as the patient
agent AND unusable for diagnosis, because Medic would receive no structured
output. Groq had exactly this problem: of 11 reachable models, only ONE emitted
real `tool_calls`.

Auto/bynara style routes are excluded by the caller (they can switch models
between runs, which breaks the determinism claim).

  .venv/bin/python scripts/smoke_tool_calling.py --base-url ... --api-key-env LLM_API_KEY_NARA
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for sources. Pass a short query.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]

PROMPT = "Find the current price of a standard widget. Use the search tool."


def list_models(base_url: str, key: str) -> list[str]:
    r = httpx.get(f"{base_url.rstrip('/')}/models",
                  headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    return sorted(m["id"] for m in (r.json().get("data") or []))


def probe(base_url: str, key: str, model: str) -> dict:
    started = time.time()
    try:
        r = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": PROMPT}],
                "tools": TOOLS,
                "temperature": 0,
                "max_tokens": 800,
            },
            timeout=90,
        )
    except Exception as exc:
        return {"model": model, "ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    if r.status_code != 200:
        body = r.text
        short = "rate limit" if r.status_code == 429 else body[:120]
        return {"model": model, "ok": False, "error": f"HTTP {r.status_code}: {short}"}

    d = r.json()
    msg = (d.get("choices") or [{}])[0].get("message") or {}
    calls = msg.get("tool_calls") or []
    usage = d.get("usage") or {}
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    args = None
    if calls:
        args = (calls[0].get("function") or {}).get("arguments")
    return {
        "model": model,
        "ok": bool(calls),
        "tool_calls": len(calls),
        "arguments": (args or "")[:100],
        "arguments_is_json": _is_json(args),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "reasoning_tokens": reasoning,
        "elapsed_s": round(time.time() - started, 2),
        "content_preview": (msg.get("content") or "")[:80],
    }


def _is_json(text) -> bool:
    if not text:
        return False
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="https://router.bynara.id/v1")
    ap.add_argument("--api-key-env", default="LLM_API_KEY_NARA")
    ap.add_argument("--models", nargs="*", default=None, help="skip the /models listing")
    ap.add_argument("--limit", type=int, default=14)
    ap.add_argument("--out", default="evidence/tool_calling_smoke.json")
    args = ap.parse_args()

    key = os.environ.get(args.api_key_env, "").strip()
    if not key:
        print(f"{args.api_key_env} is not set — nothing to test.")
        return 1

    if args.models:
        models = args.models
    else:
        try:
            models = list_models(args.base_url, key)
        except Exception as exc:
            print(f"could not list models: {type(exc).__name__}: {exc}")
            return 1

    # Auto/bynara style routes can switch models between runs, which would make
    # every determinism claim in this project false. Excluded on purpose.
    skipped = [m for m in models
               if m.lower().startswith(("auto", "bynara", "openrouter/auto"))]
    models = [m for m in models if m not in skipped]
    print(f"testing {len(models)} model(s) against {args.base_url}")
    if skipped:
        print(f"skipping (can switch models between runs): {', '.join(skipped)}\n")

    results = []
    for i, model in enumerate(models[: args.limit], 1):
        row = probe(args.base_url, key, model)
        results.append(row)
        mark = "TOOL-CALLING" if row.get("ok") else ("prose" if "ok" in row else "error")
        print(f"[{i:2}/{len(models[:args.limit])}] {model:44} {mark:14} "
              f"{row.get('elapsed_s', '-')}s")
        if row.get("ok"):
            print(f"                 args={row.get('arguments')}")
        elif row.get("error"):
            print(f"                 {row['error'][:100]}")

    winners = [r for r in results if r.get("ok")]
    print("\n" + "=" * 74)
    if winners:
        print(f"{len(winners)} of {len(results)} emit real tool_calls:")
        for w in winners:
            print(f"  {w['model']:44} args={w.get('arguments')}")
        best = min(winners, key=lambda w: w.get("completion_tokens", 10**9))
        print(f"\nRecommended pin: {best['model']}")
        print(f"  lowest completion tokens among tool-calling models: {best['completion_tokens']}")
    else:
        print("NO model emitted real tool_calls. Medic cannot use this provider as-is.")

    out = Path(__file__).resolve().parents[1] / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "base_url": args.base_url,
        "tested": len(results),
        "tool_calling": [w["model"] for w in winners],
        "skipped_unstable": skipped,
        "results": results,
    }, indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())