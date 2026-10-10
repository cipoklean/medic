"""Provider fallback chain — every call records WHICH provider served it.

Two reasons this exists, in order of importance:

  1. Demo-day resilience. A heal makes a burst of calls (diagnose, surgeon,
     then verification on train + every held-out task). One provider's daily
     budget running out mid-demo is a dead demo. Measured: Groq's free tier is
     200,000 tokens/day and a single heal costs ~30,000.
  2. Honesty in the evidence. Every span is tagged with the provider and model
     that actually served it, so `evidence/` can never claim a run came from a
     provider it did not come from.

Provider order is explicit configuration, never an implicit "try things until
one works": an unlabelled fallback makes a result impossible to attribute.

Env:
    LLM_PROVIDER_CHAIN        comma-separated names, e.g. "nara,groq"
    LLM_API_KEY_NARA, LLM_BASE_URL_NARA, LLM_MODEL_NARA
    LLM_API_KEY,     LLM_BASE_URL,     LLM_MODEL          (Groq, or your default)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from patient.config import get


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def label(self) -> str:
        return f"{self.name}:{self.model}"


# Named providers, read from the environment. Only these three shapes exist so
# a typo is a missing provider, not a silently-unused variable.
NAMED: dict[str, tuple[str, str, str]] = {
    # name: (api-key env, base-url env, model env)
    "nara": ("LLM_API_KEY_NARA", "LLM_BASE_URL_NARA", "LLM_MODEL_NARA"),
    "groq": ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"),
}


def _provider(name: str) -> Provider | None:
    spec = NAMED.get(name)
    if spec is None:
        return None
    key_env, base_env, model_env = spec
    return Provider(
        name=name,
        api_key=get(key_env),
        base_url=get(base_env) or ("https://router.bynara.id/v1" if name == "nara" else ""),
        model=get(model_env),
    )


def chain() -> list[Provider]:
    """Configured providers, in the order they should be tried."""
    order = [p.strip() for p in get("LLM_PROVIDER_CHAIN", "nara,groq").split(",") if p.strip()]
    out: list[Provider] = []
    for name in order:
        p = _provider(name)
        if p and p.configured:
            out.append(p)
    if not out:
        # No chain configured: fall back to whatever the plain LLM_* vars imply.
        generic = Provider("default", get("LLM_BASE_URL"), get("LLM_API_KEY"), get("LLM_MODEL"))
        if generic.configured:
            out.append(generic)
    return out


def describe() -> str:
    providers = chain()
    if not providers:
        return "no provider configured"
    return " -> ".join(p.label() for p in providers)


class NoProviderConfigured(RuntimeError):
    pass


def build_client(preferred: str | None = None):
    """Return (client, provider). Raises only when nothing is configured."""
    from openai import OpenAI

    providers = chain()
    if preferred:
        providers.sort(key=lambda p: 0 if p.name == preferred else 1)
    if not providers:
        raise NoProviderConfigured(
            "No LLM provider configured. Set one of:\n"
            "  NaraRouter: LLM_API_KEY_NARA, LLM_BASE_URL_NARA, LLM_MODEL_NARA\n"
            "  Groq:      LLM_API_KEY, LLM_BASE_URL, LLM_MODEL\n"
            "and optionally LLM_PROVIDER_CHAIN='nara,groq' to order them."
        )
    p = providers[0]
    return OpenAI(base_url=p.base_url, api_key=p.api_key), p


def next_provider(failed: Provider) -> Provider | None:
    """The next configured provider after one that just failed."""
    providers = chain()
    for i, p in enumerate(providers):
        if p.name == failed.name:
            return providers[i + 1] if i + 1 < len(providers) else None
    return None