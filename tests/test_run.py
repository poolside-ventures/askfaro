"""Skill execution tests: Faro.run() against the hosted skill agent."""

import json

import httpx
import pytest
import respx

from askfaro import Faro, FaroError, RemoteError

# The fixed hosted skill agent (Faro infrastructure, not self-hostable).
SKILL = "https://skill.askfaro.com"


def _ok_envelope(status="success", data=None):
    return {
        "faro_envelope": "1",
        "status": status,
        "result": {"kind": "information", "data": data or {"download_url": "https://x/y.png"}},
        "meta": {"credits_charged": 40},
    }


def test_run_without_key_raises():
    with pytest.raises(FaroError):
        Faro().run("image", "a red bicycle")


@respx.mock
def test_run_posts_to_hosted_skill_agent_and_returns_envelope():
    route = respx.post(f"{SKILL}/skills/image/run").mock(
        return_value=httpx.Response(200, json=_ok_envelope())
    )
    r = Faro(api_key="faro_test").run("image", {"prompt": "a red bicycle"})
    assert route.called
    assert r.ok and not r.local
    assert r.data["download_url"].endswith("y.png")
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer faro_test"
    assert json.loads(req.content)["intent"] == {"prompt": "a red bicycle"}


@respx.mock
def test_run_string_intent_is_wrapped_as_prompt():
    route = respx.post(f"{SKILL}/skills/image/run").mock(
        return_value=httpx.Response(200, json=_ok_envelope())
    )
    Faro(api_key="faro_test").run("image", "a red bicycle")
    assert json.loads(route.calls.last.request.content)["intent"] == {"prompt": "a red bicycle"}


@respx.mock
def test_run_forwards_ceilings_and_continuation():
    route = respx.post(f"{SKILL}/skills/image/run").mock(
        return_value=httpx.Response(200, json=_ok_envelope())
    )
    Faro(api_key="faro_test").run(
        "image", "x", max_credits=100, confirm_above=50, continuation="f1.abc.def"
    )
    sent = json.loads(route.calls.last.request.content)
    assert sent["max_credits"] == 100
    assert sent["confirm_above"] == 50
    assert sent["continuation"] == "f1.abc.def"


@respx.mock
def test_run_needs_input_is_surfaced_not_raised():
    # A quote (soft-ceiling crossing) returns 200 with status=needs_input.
    respx.post(f"{SKILL}/skills/image/run").mock(
        return_value=httpx.Response(200, json=_ok_envelope(status="needs_input"))
    )
    r = Faro(api_key="faro_test").run("image", "x")
    assert r.status == "needs_input"
    assert r.ok is False


@respx.mock
def test_run_http_error_raises():
    respx.post(f"{SKILL}/skills/image/run").mock(
        return_value=httpx.Response(402, json={"detail": "insufficient credits"})
    )
    with pytest.raises(RemoteError):
        Faro(api_key="faro_test").run("image", "x")
