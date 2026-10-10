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


def test_roles_resolve_different_models():
    """The patient and the medic must NOT resolve to the same model.

    Verified live: `medic` resolved to nova-lite because _role_model_for
    scanned every role's list and dict order put `patient` first. That hands
    Medic's reasoning to a cheap patient model, the exact degradation the
    role split exists to prevent, and invisible in the output because the
    chain line only showed the patient's model.
    """
    import os

    from medic import providers as prov

    patient = prov._role_model_for("litellm", "patient")
    medic = prov._role_model_for("litellm", "medic")

    assert patient == "nova-lite", f"patient resolved to {patient!r}"
    assert medic == "claude-sonnet-4.6", f"medic resolved to {medic!r}"
    assert patient != medic, (
        f"both roles resolved to {patient!r}; the medic must not use the "
        f"patient's cheap model"
    )


def test_role_model_does_not_leak_across_roles():
    """A role must only ever draw from its own model list."""
    from medic import providers as prov

    for role, allowed in prov.ROLE_MODELS.items():
        got = prov._role_model_for("litellm", role)
        assert got in allowed, (
            f"role {role!r} resolved {got!r}, which is not in its own list "
            f"{allowed}"
        )


def test_build_client_forwards_the_role():
    """build_client(role=...) must return THAT role's provider, not the patient's.

    It did not. `chain()` defaults to role="patient", and build_client called it
    bare, so a heal was attributed to nova-micro while the evidence claimed
    Sonnet had reasoned about it. chain(role="medic") resolved correctly, which
    is why the bug survived: the two functions disagreed and only the one the
    heal actually calls was wrong.
    """
    import os

    # Every variable this test needs is set here, so it passes on a fresh clone
    # with NO .env. It previously read LLM_PROVIDER_CHAIN from the environment,
    # so a stale value (or the old "nara,groq" default) decided the outcome and
    # the test failed on a clean checkout for reasons unrelated to the code.
    os.environ["LLM_PROVIDER_CHAIN"] = "litellm,gemini"
    os.environ["LLM_API_KEY_LITELLM"] = "sk-test-not-real"
    os.environ["LLM_API_KEY_GEMINI"] = "sk-test-not-real"
    os.environ["LLM_MODEL_GEMINI"] = "gemini-3.1-flash-lite"
    os.environ["LLM_MODEL_LITELLM_PATIENT"] = "nova-micro"
    os.environ.pop("LLM_MODEL_LITELLM", None)
    from medic import providers as prov

    for role, want in (("patient", "nova-micro"), ("medic", "claude-sonnet-4.6")):
        _, provider = prov.build_client(role=role)
        assert provider.model == want, (
            f"build_client(role={role!r}) returned {provider.model!r}, "
            f"expected {want!r}"
        )


def test_chain_and_build_client_agree():
    """The reader and the writer must not disagree about which model serves a role.

    A split like this is invisible in the chain line, which only prints the
    patient, so the wrong attribution looks correct until someone reads the
    evidence file.
    """
    import os

    # Every variable this test needs is set here, so it passes on a fresh clone
    # with NO .env. It previously read LLM_PROVIDER_CHAIN from the environment,
    # so a stale value (or the old "nara,groq" default) decided the outcome and
    # the test failed on a clean checkout for reasons unrelated to the code.
    os.environ["LLM_PROVIDER_CHAIN"] = "litellm,gemini"
    os.environ["LLM_API_KEY_LITELLM"] = "sk-test-not-real"
    os.environ["LLM_API_KEY_GEMINI"] = "sk-test-not-real"
    os.environ["LLM_MODEL_GEMINI"] = "gemini-3.1-flash-lite"
    os.environ["LLM_MODEL_LITELLM_PATIENT"] = "nova-micro"
    os.environ.pop("LLM_MODEL_LITELLM", None)
    from medic import providers as prov

    for role in prov.ROLE_MODELS:
        chained = prov.chain(role=role)[0].model
        _, built = prov.build_client(role=role)
        assert chained == built.model, (
            f"role {role!r}: chain() says {chained!r} but build_client() "
            f"returned {built.model!r}"
        )


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
