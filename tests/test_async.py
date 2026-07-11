"""AsyncFaro tests: the async client mirrors Faro's routing and surface.

asyncio_mode=auto (pyproject) runs these coroutines under pytest-asyncio; respx
intercepts httpx.AsyncClient the same way it does the sync client.
"""

import json

import httpx
import pytest
import respx

from askfaro import AsyncFaro, FaroError, RemoteError

API = "https://api.askfaro.com"
SKILL = "https://skill.askfaro.com"


async def test_local_invoke_runs_on_device_without_await_network():
    # No api_key: a local tool must never touch the backend.
    async with AsyncFaro() as faro:
        r = await faro.invoke("calc/evaluate", {"expression": "2 + 2 * 3"})
        assert r.local is True
        assert r.ok is True
        assert r.data["result"] == 8


async def test_invoke_non_core_namespace_raises_pointing_to_run():
    # invoke() is on-device only; a remote/paid capability points to run().
    async with AsyncFaro() as faro:
        with pytest.raises(FaroError) as ei:
            await faro.invoke("weather/current", {"city": "Paris"})
    assert "run(" in str(ei.value)


@respx.mock
async def test_search_returns_hits():
    respx.post(f"{API}/tools/search").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"object_type": "skill", "skill_id": "image", "short_description": "make images"}]},
        )
    )
    async with AsyncFaro() as faro:
        hits = await faro.search("generate an image")
    assert len(hits) == 1
    assert hits[0].kind == "skill" and hits[0].id == "image"


@respx.mock
async def test_run_routes_core_capability_on_device():
    # Transparent routing in the async client too: a core capability runs in-core
    # with no key and never reaches the skill agent.
    route = respx.post(f"{SKILL}/skills/astronomy/run").mock(
        return_value=httpx.Response(200, json={"status": "success"})
    )
    async with AsyncFaro() as faro:
        r = await faro.run("astronomy", {"latitude": 48.85, "longitude": 2.35, "date": "2026-06-21"})
    assert r.local is True and r.ok is True
    assert not route.called


@respx.mock
async def test_run_posts_to_skill_agent():
    route = respx.post(f"{SKILL}/skills/image/run").mock(
        return_value=httpx.Response(
            200,
            json={
                "faro_envelope": "1",
                "status": "success",
                "result": {"kind": "information", "data": {"download_url": "https://x/y.png"}},
                "meta": {"credits_charged": 40},
            },
        )
    )
    async with AsyncFaro(api_key="faro_test") as faro:
        r = await faro.run("image", "a red bicycle")
    assert route.called and r.ok and not r.local
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer faro_test"
    assert json.loads(req.content)["intent"] == {"prompt": "a red bicycle"}


async def test_run_without_key_raises():
    async with AsyncFaro() as faro:
        with pytest.raises(FaroError):
            await faro.run("image", "a red bicycle")


@respx.mock
async def test_remote_error_raises():
    respx.post(f"{API}/tools/search").mock(return_value=httpx.Response(503, json={"detail": "down"}))
    async with AsyncFaro() as faro:
        with pytest.raises(RemoteError):
            await faro.search("anything")


async def test_async_tier_of_and_require_tier():
    # tier_of mirrors the sync client; require_tier gates identically.
    async with AsyncFaro(api_key="faro_x") as faro:
        assert faro.tier_of("image") == "remote"
        with pytest.raises(FaroError) as ei:
            await faro.run("image", "a red bike", require_tier="local")
        assert ei.value.code == "tier_unavailable"
        with pytest.raises(FaroError):
            await faro.run("image", "a red bike", require_tier="bogus")
