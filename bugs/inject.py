"""Bug injection, a preset is a PATCH to the clean medic.yaml.

Why a patch and not a whole file: the clean baseline lives in one place
(`bugs/presets/clean.yaml`) and every preset is expressed as the minimum set of
changes that produces the bug. If a preset were a full file, the two would
drift and "reset" would stop being trustworthy.

`apply_bug` ALWAYS starts from clean. Never "undo by editing the buggy file":
that drifts, and a drift means `reset` no longer proves anything.
"""
from __future__ import annotations

import copy
import shutil
from typing import Any

import yaml

from patient.config import ROOT

MEDIC_YAML = ROOT / "medic.yaml"
PRESET_DIR = ROOT / "bugs" / "presets"


def clean_config() -> dict:
    with open(PRESET_DIR / "clean.yaml") as fh:
        return yaml.safe_load(fh) or {}


def load_preset(name: str) -> dict:
    """A preset file is a partial medic.yaml merged over clean."""
    path = PRESET_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no preset named {name!r} ({path})")
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def apply_bug(name: str, write: bool = True) -> dict:
    """Apply preset `name` on top of clean and (by default) write medic.yaml.

    Some bugs are only half a config change, bug 2 needs a tool to actually
    misbehave. That runtime half is switched on HERE, next to the config half,
    so a caller can never get one without the other.
    """
    config = deep_merge(clean_config(), load_preset(name))

    if name == "parse_error":
        from patient.tools import set_broken_json

        set_broken_json(True)

    if write:
        MEDIC_YAML.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    return config


def reset_bug(name: str | None = None) -> dict:
    """Restore the clean baseline. `name` is accepted and ignored on purpose:
    reset must always be the full clean file, never a partial undo.

    Also clears RUNTIME bug state (bug 2's broken-JSON switch). A `reset` that
    leaves a runtime flag set is a reset that does not reset, and the next
    "clean" run would fail for a reason nobody injected."""
    from patient.tools import set_broken_json

    set_broken_json(False)
    config = clean_config()
    MEDIC_YAML.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    return config


def current_config() -> dict:
    with open(MEDIC_YAML) as fh:
        return yaml.safe_load(fh) or {}


def describe(name: str) -> dict[str, Any]:
    preset = load_preset(name)
    clean = clean_config()
    changed = {
        k: {"from": clean.get(k), "to": v}
        for k, v in preset.items()
        if clean.get(k) != v
    }
    return changed


def backup(path=None) -> str:
    """Back up medic.yaml OUTSIDE the repo, never as medic.yaml.bak inside it."""
    src = path or MEDIC_YAML
    dest = ROOT.parent / f"{src.name}.medic-backup"
    shutil.copy(src, dest)
    return str(dest)