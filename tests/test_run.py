"""Skill execution tests: Faro.run() against the skill agent."""

import httpx
import pytest
import respx

from faro import Faro, FaroError, RemoteError

SKILL_URL = "https://skills.example.com"


def _ok_envelope(status="success", data=None):
    return {
        "faro_envelope": "1",
        "status": status,
        "result": {"kind": "information", "data": data or {"download_url": "https://x/y.png"}},
        "meta": {"credits_charged": 40},
    }


def test_run_defaults_to_hosted_skill_agent():
    # No skill_url passed -> uses the hosted default (skill.askfaro.com).
    assert Faro(api_key="faro_test")._skill_url == "https://skill.askfaro.com"


def test_run_without_skill_url_configured_raises(monkeypatch):
    # The "clear error when not configured" guard: force no default.
    monkeypatch.setattr("faro.client.DEFAULT_SKILL_URL", None)
    with pytest.raises(FaroError) as e:
        Faro(api_key="faro_test").run("image", {"prompt": "a red bicycle"})
    assert "skill-agent url" in str(e.value).lower()


def test_run_without_key_raises():
    with pytest.raises(FaroError):
        Faro(skill_url=SKILL_URL).run("image", "a red bicycle")


@respx.mock
def test_run_posts_intent_and_returns_envelope():
    route = respx.post(f"{SKILL_URL}/skills/image/run").mock(
        return_value=httpx.Response(200, json=_ok_envelope())
    )
    faro = Faro(api_key="faro_test", skill_url=SKILL_URL)
    r = faro.run("image", {"prompt": "a red bicycle"})
    assert route.called
    assert r.ok and not r.local
    assert r.data["download_url"].endswith("y.png")
    body = route.calls.last.request
    assert body.headers["authorization"] == "Bearer faro_test"
    import json

    assert json.loads(body.content)["intent"] == {"prompt": "a red bicycle"}


@respx.mock
def test_run_string_intent_is_wrapped_as_prompt():
    route = respx.post(f"{SKILL_URL}/skills/image/run").mock(
        return_value=httpx.Response(200, json=_ok_envelope())
    )
    Faro(api_key="faro_test", skill_url=SKILL_URL).run("image", "a red bicycle")
    import json

    assert json.loads(route.calls.last.request.content)["intent"] == {"prompt": "a red bicycle"}


@respx.mock
def test_run_forwards_ceilings_and_continuation():
    route = respx.post(f"{SKILL_URL}/skills/image/run").mock(
        return_value=httpx.Response(200, json=_ok_envelope())
    )
    Faro(api_key="faro_test", skill_url=SKILL_URL).run(
        "image", "x", max_credits=100, confirm_above=50, continuation="f1.abc.def"
    )
    import json

    sent = json.loads(route.calls.last.request.content)
    assert sent["max_credits"] == 100
    assert sent["confirm_above"] == 50
    assert sent["continuation"] == "f1.abc.def"


@respx.mock
def test_run_needs_input_is_surfaced_not_raised():
    # A quote (soft-ceiling crossing) returns 200 with status=needs_input.
    respx.post(f"{SKILL_URL}/skills/image/run").mock(
        return_value=httpx.Response(200, json=_ok_envelope(status="needs_input"))
    )
    r = Faro(api_key="faro_test", skill_url=SKILL_URL).run("image", "x")
    assert r.status == "needs_input"
    assert r.ok is False


@respx.mock
def test_run_http_error_raises():
    respx.post(f"{SKILL_URL}/skills/image/run").mock(
        return_value=httpx.Response(402, json={"detail": "insufficient credits"})
    )
    with pytest.raises(RemoteError):
        Faro(api_key="faro_test", skill_url=SKILL_URL).run("image", "x")


def test_run_uses_env_skill_url(monkeypatch):
    monkeypatch.setenv("FARO_SKILL_URL", SKILL_URL)
    with respx.mock:
        route = respx.post(f"{SKILL_URL}/skills/image/run").mock(
            return_value=httpx.Response(200, json=_ok_envelope())
        )
        Faro(api_key="faro_test").run("image", "x")
        assert route.called
