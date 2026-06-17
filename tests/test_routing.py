"""Routing tests: when does the SDK go local vs remote."""

import httpx
import pytest
import respx

from askfaro import Faro, FaroError


def test_auto_prefers_local_for_core_namespace():
    # No key, no network mock: if this tried to go remote it would fail.
    r = Faro().invoke("calc/evaluate", {"expression": "1 + 1"})
    assert r.local is True
    assert r.data["result"] == 2


@respx.mock
def test_auto_falls_back_to_remote_for_other_namespace():
    route = respx.post("https://api.askfaro.com/invoke/weather/current").mock(
        return_value=httpx.Response(200, json={"status": "success", "result": {"kind": "information", "data": {"temp": 20}}})
    )
    faro = Faro(api_key="faro_test")
    r = faro.invoke("weather/current", {"city": "Paris"})
    assert r.local is False
    assert route.called
    assert r.data["temp"] == 20


@respx.mock
def test_mode_remote_forces_backend_even_for_core_namespace():
    route = respx.post("https://api.askfaro.com/invoke/calc/evaluate").mock(
        return_value=httpx.Response(200, json={"status": "success", "result": {"kind": "information", "data": {"result": 999}}})
    )
    faro = Faro(api_key="faro_test")
    r = faro.invoke("calc/evaluate", {"expression": "1 + 1"}, mode="remote")
    assert r.local is False
    assert route.called
    assert r.data["result"] == 999  # came from the (mocked) backend, not the core


def test_remote_without_key_raises():
    faro = Faro()  # no key
    with pytest.raises(FaroError):
        faro.invoke("weather/current", {"city": "Paris"}, mode="remote")


@respx.mock
def test_remote_http_error_raises():
    respx.post("https://api.askfaro.com/invoke/weather/current").mock(
        return_value=httpx.Response(402, json={"detail": "insufficient credits"})
    )
    faro = Faro(api_key="faro_test")
    from askfaro import RemoteError

    with pytest.raises(RemoteError):
        faro.invoke("weather/current", {"city": "Paris"})


def test_invalid_mode_rejected():
    with pytest.raises(FaroError):
        Faro(mode="sideways")
