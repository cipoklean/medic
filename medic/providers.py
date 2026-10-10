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


# Named providers, read from the environment. Explicit shapes so a typo is a
# missing provider rather than a silently-unused variable.
#
# groq and openrouter can both serve openai/gpt-oss-20b, which is deliberate:
# the loop bug reproduces on that model, and two hosts means one exhausted
# daily budget cannot kill the demo. Same weights on a different host is NOT
# assumed to behave identically - scripts/probe_real_llm.py verifies per host,
# and evidence/loop_capability_matrix.json records the result either way.
NAMED: dict[str, tuple[str, str, str]] = {
    # name: (api-key env, base-url env, model env)
    "nara": ("LLM_API_KEY_NARA", "LLM_BASE_URL_NARA", "LLM_MODEL_NARA"),
    "groq": ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"),
    "openrouter": (
        "LLM_API_KEY_OPENROUTER",
        "LLM_BASE_URL_OPENROUTER",
        "LLM_MODEL_OPENROUTER",
    ),
}

# Default base URLs, so only the KEY is needed for the well-known hosts.
DEFAULT_BASE_URL = {
    "nara": "https://router.bynara.id/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def _provider(name: str) -> Provider | None:
    spec = NAMED.get(name)
    if spec is None:
        return None
    key_env, base_env, model_env = spec
    return Provider(
        name=name,
        api_key=get(key_env),
        base_url=get(base_env) or DEFAULT_BASE_URL.get(name, ""),
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


def next_model(current: Provider) -> Provider | None:
    """The next MODEL on the SAME provider.

    Useful when a provider is reachable and paid, but one model is missing or
    rejects tool calling. Both were observed on NaraRouter: `jev` and
    `exo-stealh` return HTTP 400 'the model rejected this request' when a tools
    array is sent, while three others on the same free plan work fine.
    """
    models = [m.strip() for m in get("LLM_MODEL_NARA_FALLBACKS", "").split(",") if m.strip()]
    if not models:
        return None
    try:
        idx = models.index(current.model)
    except ValueError:
        return None
    for nxt in models[idx + 1:]:
        return Provider(name=current.name, base_url=current.base_url,
                        api_key=current.api_key, model=nxt)
    return None