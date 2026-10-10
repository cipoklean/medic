"""Env loading. Values live in .env only — never in source, never committed."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    """Minimal .env loader — avoids a python-dotenv dependency.

    A key defined TWICE in .env is a hard error. It happened here: an appended
    provider block shadowed a real key with an empty value, and because
    os.environ.setdefault never overwrites an existing entry, the empty value
    won — so the provider looked "not configured" while a valid key sat a few
    lines above. Silent, and it cost real debugging time.
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        return

    seen: dict[str, int] = {}
    duplicates: list[str] = []
    for lineno, raw in enumerate(env_file.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in seen:
            duplicates.append(f"{key} (lines {seen[key]} and {lineno})")
            # Keep the first definition; a later duplicate must not shadow it.
            continue
        seen[key] = lineno
        # Real env wins over .env so CI/secret managers are never shadowed.
        os.environ.setdefault(key, value)

    if duplicates:
        raise RuntimeError(
            "Duplicate key(s) in .env: " + ", ".join(duplicates) + ". "
            "Remove the later definition — it can silently shadow a valid value."
        )


def get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set. Put it in {ROOT / '.env'} (see .env.example)."
        )
    return value


def neatlogs_ingest_key() -> str:
    return require("NEATLOGS_API_KEY")


def neatlogs_read_creds() -> tuple[str, str]:
    """Returns (token, project_id). EMPTY when not configured — callers must
    handle that as 'API read unavailable, use local fallback'."""
    return (
        os.environ.get("NEATLOGS_TOKEN", "").strip(),
        os.environ.get("NEATLOGS_PROJECT_ID", "").strip(),
    )


def llm_settings() -> dict:
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "").strip(),
        "api_key": os.environ.get("LLM_API_KEY", "").strip(),
        "model": os.environ.get("LLM_MODEL", "").strip(),
        "mode": os.environ.get("MEDIC_LLM_MODE", "live").strip() or "live",
    }


def llm_configured() -> bool:
    s = llm_settings()
    return bool(s["base_url"] and s["api_key"] and s["model"])