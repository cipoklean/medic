"""Surgeon: diagnosis + current medic.yaml -> a structured Patch.

Two safety properties, both enforced in code and never in the prompt:

  1. ALLOWLIST. `field` may only name system_prompt, tools.<name>.description,
     max_steps or retry_on_parse_error. A model asking to patch a Python file,
     or to invent a new top-level key, is refused — Medic edits exactly one
     file and only these fields within it.
  2. TYPE CHECK. max_steps must be an int, retry_on_parse_error a bool, a
     description a string. A patch that would make medic.yaml unloadable is
     rejected before it is ever written.

The patch is applied to a COPY and shown as a diff. It is only written after
verification passes, or with an explicit --apply.
"""
from __future__ import annotations

import copy
import difflib
import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from medic import llm

PatchField = Literal[
    "system_prompt",
    "tools.calculator.description",
    "tools.web_search.description",
    "tools.fetch_page.description",
    "max_steps",
    "retry_on_parse_error",
]

ALLOWED_FIELDS: set[str] = {
    "system_prompt",
    "tools.calculator.description",
    "tools.web_search.description",
    "tools.fetch_page.description",
    "max_steps",
    "retry_on_parse_error",
}

SYSTEM = """You are the surgeon half of Medic. You fix an agent's CONFIG.

You are given a diagnosis, the agent's current medic.yaml, and the deterministic
check that failed. Produce the SMALLEST change to medic.yaml that fixes it.

You may ONLY change one of these fields:
  system_prompt | tools.web_search.description | tools.fetch_page.description
  | tools.calculator.description | max_steps | retry_on_parse_error

Rules:
- Change exactly one field.
- Keep the field's existing TYPE (max_steps is an int, retry_on_parse_error a bool).
- For a stop/loop failure, restore an explicit stop rule in system_prompt.
- For wrong arguments, make the tool description state the argument format AND
  give one concrete example. Do not change the JSON schema — it is correct.
- For a parse error, set retry_on_parse_error to true.
- For a hallucinated citation, require that only fetched URLs may be cited.
- Never propose a code change. Never add a new field.

Return ONLY a JSON object:
{"field": "<one allowed field>", "new_value": <the new value>,
 "rationale": "<one sentence>"}"""


class Patch(BaseModel):
    field: str
    new_value: Any
    rationale: str

    @property
    def allowed(self) -> bool:
        return self.field in ALLOWED_FIELDS


class PatchRefused(Exception):
    pass


def _prompt(diagnosis, config: dict, verdict) -> str:
    return f"""DIAGNOSIS
{llm.render(diagnosis.to_dict())}

FAILING CHECK (deterministic)
failure_type: {verdict.failure_type}
reason: {verdict.reason}

CURRENT medic.yaml
{llm.render(config)}
"""


def propose(diagnosis, config: dict, verdict, recorder=None) -> tuple[Patch, dict]:
    data, usage = llm.ask_json(
        SYSTEM, _prompt(diagnosis, config, verdict), recorder, span_name="medic_surgeon"
    )
    patch = Patch(**data)
    if not patch.allowed:
        raise PatchRefused(
            f"surgeon proposed {patch.field!r}, which is not an allowed medic.yaml field. "
            f"Allowed: {', '.join(sorted(ALLOWED_FIELDS))}"
        )
    _check_type(patch)
    return patch, usage


def _check_type(patch: Patch) -> None:
    """Reject a patch that would corrupt medic.yaml."""
    if patch.field == "max_steps" and not isinstance(patch.new_value, int):
        raise PatchRefused(f"max_steps must be an int, got {type(patch.new_value).__name__}")
    if patch.field == "retry_on_parse_error" and not isinstance(patch.new_value, bool):
        raise PatchRefused(
            f"retry_on_parse_error must be a bool, got {type(patch.new_value).__name__}"
        )
    if patch.field.endswith(".description") and not isinstance(patch.new_value, str):
        raise PatchRefused("a tool description must be a string")
    if patch.field == "system_prompt":
        if not isinstance(patch.new_value, str) or not patch.new_value.strip():
            raise PatchRefused("system_prompt must be a non-empty string")


def apply_patch(config: dict, patch: Patch) -> dict:
    """Returns a NEW config. Never mutates the input."""
    out = copy.deepcopy(config)
    parts = patch.field.split(".")
    if len(parts) == 1:
        out[parts[0]] = patch.new_value
    else:
        tool = parts[1]
        out.setdefault("tools", {}).setdefault(tool, {})["description"] = patch.new_value
    # Re-serialise immediately: a config that cannot round-trip is not a patch.
    yaml.safe_dump(out)
    return out


def diff(config_before: dict, config_after: dict) -> str:
    a = yaml.safe_dump(config_before, sort_keys=True).splitlines(keepends=True)
    b = yaml.safe_dump(config_after, sort_keys=True).splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(a, b, fromfile="medic.yaml (before)", tofile="medic.yaml (after)")
    )


def colour_diff(text: str) -> str:
    """Rich markup for a unified diff."""
    out = []
    for line in text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            out.append(f"[green]{line}[/green]")
        elif line.startswith("-") and not line.startswith("---"):
            out.append(f"[red]{line}[/red]")
        elif line.startswith("@@"):
            out.append(f"[cyan]{line}[/cyan]")
        else:
            out.append(f"[dim]{line}[/dim]")
    return "\n".join(out)


# ── minimal, deterministic fallbacks ─────────────────────────────────────
# If the LLM is unavailable or refuses, these fix the four known bugs without
# a model. They are NOT a substitute for the LLM — they exist so a heal can be
# demonstrated offline, and so the demo has a floor.

DETERMINISTIC_FIXES: dict[str, dict] = {
    "loop": {
        "field": "system_prompt",
        "rationale": "restore an explicit stop rule so the agent stops when it can answer",
    },
    "wrong_args": {
        "field": "tools.calculator.description",
        "rationale": "state the argument format and give a worked example",
    },
    "parse_error": {
        "field": "retry_on_parse_error",
        "new_value": True,
        "rationale": "let the agent retry once after a malformed tool payload",
    },
    "hallucinated_citation": {
        "field": "system_prompt",
        "rationale": "require that only URLs actually fetched may be cited",
    },
}

STOP_RULE = (
    "  Stop rule: as soon as you can answer, stop calling tools and answer.\n"
    "  Never make more than two web_search calls for one question.\n"
)

CALC_DESCRIPTION = (
    'Evaluate arithmetic. Pass a single arithmetic expression with numbers and '
    'operators, e.g. "(128.4 * 3) + 20" or "(128.40*250)*(1-0.12)". '
    "Do not pass prose, words or a sentence."
)

EVIDENCE_RULE = (
    "  Cite only URLs you actually fetched with fetch_page in this run. "
    "If you did not fetch a page, do not cite it.\n"
)


def _strip_citation_permission(prompt: str) -> str:
    """REMOVE the sentences that license inventing citations.

    Appending the correct rule is not enough. Bug 4's prompt still says "Cite
    what you know. If you did not fetch a page, you may still cite the URL from
    the search result", and a literal model obeys the instruction it meets
    FIRST. A config fix that adds a rule while leaving the contradicting one
    in place does not fix anything — it just makes the prompt longer.
    """
    lines = []
    for line in prompt.splitlines(keepends=True):
        low = line.lower()
        if "cite what you know" in low:
            continue
        if "you may still cite" in low:
            continue
        if "use your judgement about what is worth citing" in low:
            continue
        lines.append(line)
    return "".join(lines).rstrip()


def deterministic_patch(failure_type: str, config: dict) -> Patch | None:
    spec = DETERMINISTIC_FIXES.get(failure_type)
    if not spec:
        return None
    field = spec["field"]
    if field == "retry_on_parse_error":
        value = spec["new_value"]
    elif field == "tools.calculator.description":
        value = CALC_DESCRIPTION
    else:
        prompt = str(config.get("system_prompt", ""))
        if failure_type == "loop":
            if "stop rule" in prompt.lower():
                return None
            value = prompt.rstrip() + "\n\n" + STOP_RULE
        else:  # hallucinated_citation
            if "only urls you actually fetched" in prompt.lower():
                return None
            cleaned = _strip_citation_permission(prompt)
            value = cleaned + "\n" + EVIDENCE_RULE
    return Patch(field=field, new_value=value, rationale=spec["rationale"])