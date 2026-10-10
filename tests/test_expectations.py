"""Every task's expected_answer must be RE-DERIVED from the fixtures.

This exists because of a specific failure. `parse-error-gadgets` asked for the
cost of a case given a $169.98 bundle and a $79.99 gadget. The correct answer is
$89.99. The task expected $10.00, and the scripted LLM returned
`169.98-(79.99*2)` — which doubles the gadget price and produces exactly $10.00.

So the wrong number was written into BOTH halves of the test: the expectation and
the stub that satisfies it. Every deterministic run agreed with itself. That is
how a suite earns trust it has not earned, and it survived until a real model
computed the right answer and the check failed it.

A hand-written expectation cannot be checked against anything. An expectation
that is COMPUTED from the same fixture data the agent reads can.

Each task declares `expect: {expr, from}` where `expr` is arithmetic over numbers
pulled out of a named fixture. The test recomputes it and compares. A task with
no `expect` block is reported as UNVERIFIED rather than passed.

    .venv/bin/python tests/test_expectations.py
"""
from __future__ import annotations

import json
import re
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml


def _numbers_in(text: str) -> list[Decimal]:
    return [Decimal(m.replace(",", "")) for m in re.findall(r"-?\d[\d,]*\.?\d*", text)]


def load_tasks() -> list[dict]:
    out: list[dict] = []
    for name in ("tasks/train.yaml", "tasks/heldout.yaml"):
        for doc in yaml.safe_load_all((ROOT / name).read_text()):
            if doc and doc.get("id"):
                out.append(doc)
    return out


def fixture_numbers(fixture: str) -> list[Decimal]:
    """Every number appearing in a fixture's titles, snippets and body."""
    path = ROOT / "fixtures" / "search" / f"{fixture}.json"
    if not path.exists():
        path = ROOT / "fixtures" / "pages" / f"{fixture}.html"
    if not path.exists():
        raise AssertionError(f"fixture not found: {fixture}")
    text = path.read_text()
    if path.suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {}
        blob = json.dumps(data)
    else:
        blob = text
    return _numbers_in(blob)


def evaluate(expr: str, values: dict[str, Decimal]) -> Decimal:
    """Evaluate a small arithmetic expression over named fixture values."""
    allowed = {k: v for k, v in values.items()}
    safe_globals = {"__builtins__": {}, "Decimal": Decimal, **allowed}
    return eval(expr, safe_globals)  # noqa: S307 — inputs are task files, not user data


def main() -> int:
    tasks = load_tasks()
    checked, unverified, failed = 0, [], []

    for task in tasks:
        tid = task["id"]
        spec = task.get("expect")
        if not spec:
            unverified.append(tid)
            print(f"  SKIP  {tid:30} no `expect` block — expectation is hand-written")
            continue

        expr = spec["expr"]
        source = spec["from"]
        nums = fixture_numbers(source)
        # bind the fixture's numbers to the names the expression uses
        bind: dict[str, Decimal] = {}
        for key, val in spec.items():
            if key in ("expr", "from"):
                continue
            bind[key] = Decimal(str(val))

        try:
            computed = evaluate(expr, bind)
        except Exception as exc:
            failed.append((tid, f"could not evaluate: {exc}"))
            print(f"  FAIL  {tid:30} {exc}")
            continue

        expected = Decimal(str(task["expected_answer"]))
        ok = computed == expected
        checked += 1
        if not ok:
            failed.append((tid, f"expected {expected}, fixtures give {computed}"))
        print(f"  {'PASS ' if ok else 'FAIL '} {tid:30} {expr} = {computed}"
              f"   (task says {expected})")
        print(f"       from fixtures/search/{source}.json, numbers present: "
              f"{[str(n) for n in nums][:6]}")

    print()
    print(f"re-derived: {checked}/{len(tasks)}   unverified: {len(unverified)}")
    if failed:
        print("\nMISMATCHES — the task expectation disagrees with its own fixtures:")
        for tid, why in failed:
            print(f"  {tid}: {why}")
    if unverified:
        print("\nUNVERIFIED (add an `expect` block to pin these):")
        for tid in unverified:
            print(f"  {tid}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
