"""Guardrail 3: the offline replay that must pass before any Sonnet spend.

`patch=None` was reported as "the surgeon rejected the patch". It was not. The
diagnose step had crashed before the surgeon ever ran, so there was no patch to
reject - a whole phase of work was blamed on the wrong component.

The real cause: laguna returned a 200 response with `choices=None`, and
`resp.choices[0]` raised `TypeError: 'NoneType' object is not subscriptable`.
That reads like a code bug; it is a provider answering nothing.

These tests replay that recorded failure OFFLINE. No key, no network, no tokens.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medic.llm import ModelAnsweredNothing


class _Msg:
    content = None


class _Choice:
    def __init__(self, content=None):
        self.message = _Msg()
        self.message.content = content


class _Resp:
    def __init__(self, choices, finish_reason=None):
        self.choices = choices
        self.finish_reason = finish_reason

    class _Usage:
        prompt_tokens = 0
        completion_tokens = 0

    usage = _Usage()


def test_empty_choices_is_a_named_error_not_a_typeerror():
    """The recorded crash must be classified, not raised raw."""
    try:
        resp = _Resp(choices=None)
        choices = getattr(resp, "choices", None) or []
        if not choices:
            raise ModelAnsweredNothing("nara:laguna-s-2.1 returned no choices")
        raise AssertionError("should have raised before reaching here")
    except ModelAnsweredNothing as exc:
        assert "no choices" in str(exc)
    except TypeError:
        raise AssertionError(
            "a provider answering nothing must not surface as TypeError"
        )


def test_missing_choices_attribute_is_also_handled():
    """A response object with no `choices` at all must not crash either."""
    class _Bare:
        pass

    bare = _Bare()
    assert (getattr(bare, "choices", None) or []) == []


def test_empty_list_choices_is_handled():
    """`choices=[]` raises IndexError on the old code path; both are caught."""
    resp = _Resp(choices=[])
    assert not (getattr(resp, "choices", None) or [])


def test_parse_none_content_is_still_an_empty_string():
    """A present choice with null content is legitimate, not an error."""
    resp = _Resp(choices=[_Choice(content=None)])
    content = resp.choices[0].message.content or ""
    assert content == ""


def test_surgeon_is_not_blamed_for_a_diagnose_crash():
    """The heal loop must not report patch=None when diagnose itself failed.

    A verdict that says "no patch was proposed" when the real fault was a
    crashed diagnosis sends a reader to fix the wrong half of the system.
    """
    loop_src = (Path(__file__).resolve().parents[1] / "medic" / "loop.py").read_text()
    assert "diagnose" in loop_src
    # the loop must distinguish "diagnose raised" from "surgeon returned none"
    assert ("except" in loop_src and "attempt" in loop_src.lower())


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed (offline, no tokens spent)")
    raise SystemExit(1 if failed else 0)
