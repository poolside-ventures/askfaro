"""Local-execution tests: every free namespace runs on-device, no network."""

import pytest

from askfaro import Faro, LocalUnavailableError


@pytest.fixture
def faro():
    # No api_key: proves these never touch the backend.
    return Faro()


def test_core_is_available(faro):
    assert faro.core_available() is True
    assert faro.core_version() is not None


def test_local_namespaces_include_ported_tools(faro):
    ns = faro.local_namespaces()
    for expected in ("calc", "units", "phone", "astronomy", "encoding", "datetime", "timezone", "random"):
        assert expected in ns, f"{expected} should run on-device"


def test_calc_runs_local(faro):
    r = faro.invoke("calc/evaluate", {"expression": "2 + 2 * 3"})
    assert r.local is True
    assert r.ok is True
    assert r.data["result"] == 8
    assert r.meta.get("credits_charged") in (0, 0.0)


def test_units_runs_local(faro):
    r = faro.invoke("units/convert", {"value": 100, "from_unit": "celsius", "to_unit": "fahrenheit"})
    assert r.local is True
    assert r.data["result"] == 212


def test_phone_runs_local(faro):
    r = faro.invoke("phone/parse", {"number": "+12025551234"})
    assert r.local is True
    assert r.ok is True
    assert r.data["country_code"] == 1


def test_astronomy_runs_local(faro):
    r = faro.invoke("astronomy/moon", {"date": "2024-01-25"})
    assert r.local is True
    assert r.data["illumination_percent"] > 90.0


def test_dot_separator_accepted(faro):
    r = faro.invoke("calc.evaluate", {"expression": "10 / 4"})
    assert r.ok is True
    assert r.data["result"] == 2.5


def test_tool_failure_returns_failed_envelope_not_raise(faro):
    # Division by zero is a tool-level failure -> failed envelope, not an exception.
    r = faro.invoke("calc/evaluate", {"expression": "1 / 0"})
    assert r.local is True
    assert r.ok is False
    assert r.error is not None
    assert r.error.get("code")


def test_mode_local_raises_for_backend_only_namespace(faro):
    with pytest.raises(LocalUnavailableError):
        faro.invoke("weather/current", {"city": "Paris"}, mode="local")


def test_invalid_tool_identifier(faro):
    from askfaro import FaroError

    with pytest.raises(FaroError):
        faro.invoke("nonsense", {})
