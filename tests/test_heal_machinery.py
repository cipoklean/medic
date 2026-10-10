"""Heal MACHINERY tests, NOT proof that Medic heals anything.

WHAT THIS DOES AND DOES NOT PROVE
---------------------------------
This file never calls `medic.diagnose.diagnose()` or `medic.surgeon.propose()`.
It takes `failure_type` straight from the DETERMINISTIC hard check and calls
`surgeon.deterministic_patch()`. So there is no LLM in this path at all.

It DOES prove the machinery around the model is sound:
  - local trace fallback works when neatlogs is unreachable
  - a patch survives train + held-out verification for all four bugs
  - the allowlist refuses a non-medic.yaml field and the type checks refuse
    a string max_steps, a string retry flag and an empty system_prompt
  - apply_patch does not mutate its input and round-trips through YAML
  - medic.yaml returns to the clean baseline after healing

It does NOT prove "Medic healed it". That claim requires a real model naming
the broken span and proposing the patch, and is only made once
`--llm real` has produced a real end-to-end heal (see evidence/).

Renamed from test_heal.py after this distinction was pointed out: the old name
and the old summary line both implied a heal that was never performed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from bugs.inject import apply_bug, clean_config, reset_bug
from medic import surgeon as surg
from medic.trace_source import load_trace
from medic.verify import verify
from patient.tracing import new_run
from tasks.loader import BUGS, heldout_for, train_task_for


def _heal_with_deterministic_fix(bug: str, config: dict) -> dict:
    """The offline equivalent of one loop iteration."""
    from checks.checks import run_checks
    from medic.runner import run_once

    task = train_task_for(bug)
    if task is None:
        raise AssertionError(f"no train task for {bug}")
    recorder = new_run("patient-agent", tags=[f"bug={bug}", "phase=before"])
    result = run_once(task["question"], recorder, config)
    recorder.write({"result": result.to_dict(), "bug": bug, "task_id": task["id"]})

    verdict = run_checks(bug, task, result)
    if verdict.passed:
        return {"healed": True, "patch": None, "verify": None}

    trace = load_trace(recorder.run_id)
    assert trace is not None, "local trace fallback must always work"

    patch = surg.deterministic_patch(verdict.failure_type or "other", config)
    assert patch is not None, f"no deterministic fix for {verdict.failure_type}"

    patched = surg.apply_patch(config, patch)
    vr = verify(bug, patched, mode="scripted", attempt=1)
    return {"healed": vr.all_passed, "patch": patch, "verify": vr, "diff": surg.diff(config, patched)}


def test_trace_local_fallback_always_works() -> list[str]:
    """The product claim: Medic runs even when neatlogs cannot be reached."""
    problems = []
    rec = new_run("test")
    with rec.span("WORKFLOW", "test_run", "q"):
        with rec.span("TOOL", "web_search", tool_name="web_search") as sp:
            sp["output"] = {"results": []}
    rec.write({"result": {"answer": "x"}, "bug": "loop"})
    trace = load_trace(rec.run_id)
    if trace is None:
        return ["local trace fallback failed"]
    if trace.source != "local":
        problems.append(f"expected source=local, got {trace.source}")
    if not trace.spans:
        problems.append("trace has no spans")
    return problems


def test_deterministic_patch_satisfies_all_checks() -> list[str]:
    """A hand-written patch passes train + held-out. No LLM involved."""
    problems = []
    for bug in ("wrong_args", "loop", "parse_error", "hallucinated_citation"):
        reset_bug(bug)
        config = apply_bug(bug, write=False)
        out = _heal_with_deterministic_fix(bug, config)
        if not out["healed"]:
            vr = out.get("verify")
            detail = ""
            if vr:
                bad = [o.task_id for o in vr.heldout if not o.passed]
                if vr.train and not vr.train.passed:
                    bad.insert(0, vr.train.task_id)
                detail = f" still failing: {bad}"
            problems.append(f"{bug}: not healed after patch{detail}")
        else:
            vr = out["verify"]
            held = len(vr.heldout)
            if held < 2:
                problems.append(f"{bug}: healed with only {held} held-out task(s)")
    reset_bug()
    return problems


def test_patch_allowlist() -> list[str]:
    """A model must not be able to patch anything but medic.yaml's four fields."""
    problems = []
    bad_field = surg.Patch(field="python_code", new_value="x", rationale="r")
    if bad_field.allowed:
        problems.append("allowlist let a non-medic.yaml field through")

    typed = surg.Patch(field="max_steps", new_value="eight", rationale="r")
    try:
        surg._check_type(typed)
        problems.append("type check accepted a string max_steps")
    except surg.PatchRefused:
        pass

    booled = surg.Patch(field="retry_on_parse_error", new_value="yes", rationale="r")
    try:
        surg._check_type(booled)
        problems.append("type check accepted a string retry_on_parse_error")
    except surg.PatchRefused:
        pass

    empty = surg.Patch(field="system_prompt", new_value="   ", rationale="r")
    try:
        surg._check_type(empty)
        problems.append("type check accepted an empty system_prompt")
    except surg.PatchRefused:
        pass
    return problems


def test_patch_does_not_mutate_and_roundtrips() -> list[str]:
    problems = []
    config = clean_config()
    before = repr(config)
    patch = surg.Patch(field="max_steps", new_value=3, rationale="r")
    new = surg.apply_patch(config, patch)
    if repr(config) != before:
        problems.append("apply_patch mutated the input config")
    if new["max_steps"] != 3:
        problems.append("apply_patch did not set max_steps")
    import yaml

    try:
        yaml.safe_dump(new)
    except Exception as exc:
        problems.append(f"patched config does not round-trip through YAML: {exc}")
    return problems


def test_clean_config_is_untouched_by_healing() -> list[str]:
    """Healing must never leave medic.yaml worse than it found it."""
    problems = []
    for bug in BUGS:
        reset_bug(bug)
        config = apply_bug(bug, write=False)
        _heal_with_deterministic_fix(bug, config)
    reset_bug()
    from bugs.inject import current_config

    if current_config() != clean_config():
        problems.append("reset_bug did not restore the clean baseline exactly")
    return problems


def test_no_llm_is_used_in_this_path() -> list[str]:
    """Guard the distinction this file exists to make.

    If someone later routes these tests through the real diagnoser, the output
    changes meaning and the offline claim becomes false. The check reads only
    the helper functions ABOVE this one, so its own prose cannot match itself.
    """
    import io
    import re
    import tokenize

    # Compare CODE only. Docstrings mention these names in prose, and matching
    # prose is how this check produced false positives on its own explanation.
    body = source_before_this_guard()
    code = []
    for tok in tokenize.generate_tokens(io.StringIO(body).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        code.append(tok.string)
    code = " ".join(code)

    problems = []
    for fn in ("diagnose", "propose"):
        if re.search(r"\b" + fn + r"\s*\(", code):
            problems.append(f"tests now call {fn}() - the offline claim would be false")
    if "_heal_with_deterministic_fix" not in body:
        problems.append("helper renamed; re-check what this file exercises")
    if "deterministic_patch" not in body:
        problems.append("no longer exercising surgeon.deterministic_patch")
    return problems


def source_before_this_guard() -> str:
    """Everything above this function, i.e. the code the claim is about."""
    text = Path(__file__).read_text()
    return text[: text.index("def test_no_llm_is_used_in_this_path")]


def main() -> int:
    tests = [
        ("local trace fallback always works", test_trace_local_fallback_always_works),
        ("a deterministic patch satisfies train + held-out", test_deterministic_patch_satisfies_all_checks),
        ("patch allowlist holds", test_patch_allowlist),
        ("patch is immutable and round-trips", test_patch_does_not_mutate_and_roundtrips),
        ("clean config restored after healing", test_clean_config_is_untouched_by_healing),
        ("no LLM is used in this test path", test_no_llm_is_used_in_this_path),
    ]
    failures = []
    for name, fn in tests:
        print(f"→ {name}")
        try:
            problems = fn()
        except Exception as exc:
            problems = [f"the test itself raised {type(exc).__name__}: {exc}"]
        if problems:
            for p in problems:
                print(f"    FAIL {p}")
            failures.append(name)
    reset_bug()
    if failures:
        print(f"\n{len(failures)} test(s) failed")
        return 1
    print("\nALL MACHINERY TESTS PASS (no LLM was used in this path)")
    return 0


if __name__ == "__main__":
    sys.exit(main())