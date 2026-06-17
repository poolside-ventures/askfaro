"""run() is the single transparent entry: it routes a capability on-device when
the bundled core can run it, and to the skill agent otherwise. The consumer never
chooses. invoke() remains an advanced "force on-device" escape hatch."""

import httpx
import pytest
import respx

from askfaro import Faro, FaroError

SKILL = "https://skill.askfaro.com"


def _ok_envelope():
    return {
        "faro_envelope": "1",
        "status": "success",
        "result": {"kind": "information", "data": {"download_url": "https://x/y.png"}},
        "meta": {"credits_charged": 40},
    }


@respx.mock
def test_run_routes_core_capability_on_device_without_key_or_network():
    # A core capability runs in-core: no key, and the skill agent is never called.
    route = respx.post(f"{SKILL}/skills/astronomy/run").mock(
        return_value=httpx.Response(200, json=_ok_envelope())
    )
    r = Faro().run("astronomy", {"latitude": 48.85, "longitude": 2.35, "date": "2026-06-21"})
    assert r.local is True
    assert r.ok is True
    assert r.credits_charged in (0, 0.0)
    assert not route.called, "a core capability must run on-device, not hit the agent"


def test_run_routes_namespaced_capability_on_device():
    # `namespace.operation` ids route on the namespace and dispatch the operation.
    r = Faro().run("calc.evaluate", {"expression": "2 + 2 * 3"})
    assert r.local is True
    assert r.data["result"] == 8


@respx.mock
def test_run_routes_non_core_capability_to_skill_agent():
    # A capability the core can't run goes to the hosted agent (needs a key).
    route = respx.post(f"{SKILL}/skills/weather/run").mock(
        return_value=httpx.Response(200, json=_ok_envelope())
    )
    r = Faro(api_key="faro_test").run("weather", {"city": "Paris"})
    assert route.called
    assert r.local is False


def test_run_non_core_capability_without_key_raises():
    # Routing to the agent still needs a key; on-device capabilities do not.
    with pytest.raises(FaroError) as ei:
        Faro().run("weather", {"city": "Paris"})
    assert ei.value.code == "auth_required"


def test_invoke_is_advanced_force_local_escape_hatch():
    # invoke() still forces on-device and raises (pointing at run()) off-core.
    r = Faro().invoke("calc/evaluate", {"expression": "1 + 1"})
    assert r.local is True and r.data["result"] == 2
    with pytest.raises(FaroError) as ei:
        Faro().invoke("weather/current", {"city": "Paris"})
    assert "run(" in str(ei.value)


def test_mode_kwarg_removed():
    # The local-first `mode` knob is gone — routing is automatic, not a knob.
    with pytest.raises(TypeError):
        Faro(mode="remote")  # type: ignore[call-arg]
