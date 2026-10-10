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
    LLM_PROVIDER_CHAIN        comma-separated names, e.g. "litellm,gemini"
    MEDIC_ROLE_MODELS         "patient:nova-lite" — pins a role's model
    LLM_API_KEY_NARA, LLM_BASE_URL_NARA, LLM_MODEL_NARA
    LLM_API_KEY,     LLM_BASE_URL,     LLM_MODEL          (Groq, or your default)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from patient.config import get


class NoProviderConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str
    # OpenRouter-style upstream pinning. `order` is a preference list and
    # `allow_fallbacks=False` makes it a REQUIREMENT: without it OpenRouter may
    # silently serve the model from a different host, and a run measured on one
    # host cannot be reported as another. Verified serving "Groq" with it set.
    route_order: tuple[str, ...] = ()
    allow_fallbacks: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def label(self) -> str:
        upstream = f" via {self.route_order[0]}" if self.route_order else ""
        return f"{self.name}:{self.model}{upstream}"

    def routing(self) -> dict | None:
        """The provider-routing body, or None when pinning is not configured."""
        if not self.route_order:
            return None
        return {"order": list(self.route_order), "allow_fallbacks": self.allow_fallbacks}


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
    # Primary gateway, Oct 10. Serves several families behind one key, so the
    # MODEL name picks the family rather than the provider.
    "litellm": (
        "LLM_API_KEY_LITELLM",
        "LLM_BASE_URL_LITELLM",
        "LLM_MODEL_LITELLM",
    ),
    "gemini": (
        "LLM_API_KEY_GEMINI",
        "LLM_BASE_URL_GEMINI",
        "LLM_MODEL_GEMINI",
    ),
}

# Default base URLs, so only the KEY is needed for the well-known hosts.
DEFAULT_BASE_URL = {
    "nara": "https://router.bynara.id/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "litellm": "https://litellm.vision.aivar.app/v1",
    # OpenAI-compatible endpoint. Google's own model IDs move fast, so the
    # default is a name we have verified reachable, not the newest thing.
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}

# ---------------------------------------------------------------------------
# Roles. The patient and the medic are DIFFERENT jobs: the patient needs a
# cheap model that fails realistically, the medic needs one that reasons well
# enough to name the right span and write a correct patch. Coupling them meant
# a cheap patient made Medic's diagnosis worse for no reason.
#
# Each role resolves to its own model, falling back through its own list.
# ---------------------------------------------------------------------------

ROLE_MODELS: dict[str, tuple[str, ...]] = {
    # Patient: cheap, and it must actually emit tool_calls.
    "patient": ("nova-lite", "nova-micro", "nova-2-lite"),
    # Medic: reasons about a span tree and writes a minimal patch.
    "medic": ("claude-sonnet-4.6", "claude-haiku", "gemini-2.5-flash"),
}


def _provider(name: str, role: str = "patient") -> Provider | None:
    spec = NAMED.get(name)
    if spec is None:
        return None
    key_env, base_env, model_env = spec
    route = tuple(
        m.strip() for m in get(f"LLM_ROUTE_{name.upper()}", "").split(",") if m.strip()
    )
    # A role-specific override wins over the provider-wide one. Without it,
    # LLM_MODEL_LITELLM is read by BOTH roles, so pinning the patient to
    # nova-micro silently pinned the medic to it too — and a heal then gets
    # attributed to a cheap patient model while the evidence says the medic
    # reasoned on it. A measurement attributed to the wrong model is worse than
    # no measurement.
    role_env = f"LLM_MODEL_{name.upper()}_{role.upper()}"
    model = get(role_env) or get(model_env)
    if not model:
        model = _role_model_for(name, role)
    return Provider(
        name=name,
        api_key=get(key_env),
        base_url=get(base_env) or DEFAULT_BASE_URL.get(name, ""),
        model=model,
        route_order=route,
    )


def _role_model_for(provider_name: str, role: str) -> str:
    """The first model this provider can serve for THIS role.

    Takes the role explicitly. An earlier version scanned every role's model
    list and returned the first match, which meant dict ordering decided the
    outcome: `patient` sorts first, so the medic silently resolved to
    `nova-lite` — a cheap patient model doing Medic's reasoning, which is the
    exact degradation the role split exists to prevent. The returned model is
    checked against the requested role's list ONLY.
    """
    candidates = ROLE_MODELS.get(role)
    if not candidates:
        return ""
    for candidate in candidates:
        if _serves(provider_name, candidate):
            return candidate
    return ""


def _serves(provider_name: str, model: str) -> bool:
    """Does this provider serve this model?

    Deliberately conservative: an unknown provider serves nothing, which makes
    the failure a clear "no model configured" rather than a silently wrong
    request to a host that will 404.
    """
    family = {
        "litellm": ("nova", "claude"),
        "gemini": ("gemini",),
        "nara": ("laguna", "nemotron", "agnes", "jev", "exo"),
        "groq": ("gpt-oss", "llama", "qwen"),
        "openrouter": ("gpt-oss", "llama", "qwen", "claude", "gemini"),
    }.get(provider_name, ())
    return any(model.startswith(prefix) for prefix in family)


def chain(role: str = "patient") -> list[Provider]:
    """Configured providers, in the order they should be tried.

    A provider that is NAMED but not configured is an ERROR, never a silent
    skip. Skipping it let `LLM_PROVIDER_CHAIN=openrouter` fall through to the
    generic LLM_* provider — which is GROQ's credentials — so a probe labelled
    "openrouter" actually hit Groq and produced a plausible, wrong result. A
    measurement attributed to the wrong host is worse than no measurement.
    """
    raw = get("LLM_PROVIDER_CHAIN", "nara,groq")
    order = [p.strip() for p in raw.split(",") if p.strip()]

    out: list[Provider] = []
    unconfigured: list[str] = []
    unknown: list[str] = []
    for name in order:
        if name not in NAMED:
            unknown.append(name)
            continue
        prov = _provider(name, role=role)
        if prov and prov.configured:
            out.append(prov)
        else:
            unconfigured.append(name)

    if unknown:
        raise NoProviderConfigured(
            f"Unknown provider(s) in LLM_PROVIDER_CHAIN: {', '.join(unknown)}. "
            f"Known: {', '.join(sorted(NAMED))}."
        )
    if not out:
        if unconfigured:
            raise NoProviderConfigured(
                f"LLM_PROVIDER_CHAIN names {', '.join(unconfigured)} but none is "
                f"fully configured (base_url, api_key and model are all required).\n"
                f"Refusing to fall back to another provider: a run must be "
                f"attributable to the provider you asked for."
            )
        generic = Provider("default", get("LLM_BASE_URL"), get("LLM_API_KEY"), get("LLM_MODEL"))
        if generic.configured:
            out.append(generic)
    return out


def describe() -> str:
    providers = chain()
    if not providers:
        return "no provider configured"
    return " -> ".join(p.label() for p in providers)


def describe_roles() -> str:
    """One line per role, so a reader can see which model serves which job."""
    lines = []
    for role in ROLE_MODELS:
        provs = chain(role=role)
        if provs:
            lines.append(f"  {role:8} {provs[0].label()}")
        else:
            lines.append(f"  {role:8} (not configured)")
    return "\n".join(lines)


def build_client(preferred: str | None = None, role: str = "patient"):
    """Return (client, provider). Raises only when nothing is configured."""
    from openai import OpenAI

    # `role` must be forwarded here. `chain()` defaults to "patient", so calling
    # it bare made build_client(role="medic") return the PATIENT's provider — a
    # heal would then be attributed to the cheap patient model while the
    # evidence claimed the medic reasoned on Sonnet. Verified directly:
    # chain(role="medic") resolved claude-sonnet-4.6 while
    # build_client(role="medic") returned nova-micro.
    providers = chain(role=role)
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
                        api_key=current.api_key, model=nxt,
                        route_order=current.route_order,
                        allow_fallbacks=current.allow_fallbacks)
    return None