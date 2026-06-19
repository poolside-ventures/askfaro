"""browse()/navigator() cache the pcx manifest and revalidate by ETag.

A warm cache sends If-None-Match and reuses the body on a 304 instead of
re-downloading. Cache isolation is handled by the autouse fixture in conftest.
"""

import httpx
import pytest
import respx

from askfaro import AsyncFaro, Faro

MANIFEST = {
    "usage": "...",
    "source": {"content_hash": "sha256:abc"},
    "variant": {"budget": 4096},
    "root": {"id": "r", "what": "root", "when": "", "children": []},
    "nodes": {},
}


def _ok(etag="\"etag-1\""):
    return httpx.Response(200, json=MANIFEST, headers={"ETag": etag})


@respx.mock
def test_cold_cache_fetches_without_if_none_match():
    route = respx.get("https://api.askfaro.com/pcx/manifest").mock(return_value=_ok())
    Faro().browse(budget="4k")
    assert "if-none-match" not in {k.lower() for k in route.calls.last.request.headers}


@respx.mock
def test_warm_cache_revalidates_and_reuses_on_304():
    route = respx.get("https://api.askfaro.com/pcx/manifest").mock(
        side_effect=[_ok(), httpx.Response(304, headers={"ETag": "\"etag-1\""})]
    )
    faro = Faro()
    first = faro.browse(budget="4k")
    second = faro.browse(budget="4k")  # second client call -> revalidate
    assert first == second
    assert route.call_count == 2
    # The revalidation carried the cached ETag.
    assert route.calls.last.request.headers["if-none-match"] == '"etag-1"'


@respx.mock
def test_cache_shared_across_clients_via_disk(tmp_path):
    route = respx.get("https://api.askfaro.com/pcx/manifest").mock(
        side_effect=[_ok(), httpx.Response(304, headers={"ETag": "\"etag-1\""})]
    )
    # Two independent clients, same on-disk cache (isolated to tmp by conftest):
    Faro().browse(budget="4k")
    Faro().browse(budget="4k")
    assert route.calls.last.request.headers["if-none-match"] == '"etag-1"'


@respx.mock
def test_manifest_cache_false_uses_memory_no_revalidation_across_clients():
    route = respx.get("https://api.askfaro.com/pcx/manifest").mock(return_value=_ok())
    # In-memory store is per-client: a fresh client has nothing cached.
    Faro(manifest_cache=False).browse(budget="4k")
    Faro(manifest_cache=False).browse(budget="4k")
    assert route.call_count == 2
    assert "if-none-match" not in {k.lower() for k in route.calls.last.request.headers}


@respx.mock
def test_navigator_uses_the_same_cache():
    route = respx.get("https://api.askfaro.com/pcx/manifest").mock(
        side_effect=[_ok(), httpx.Response(304, headers={"ETag": "\"etag-1\""})]
    )
    faro = Faro()
    faro.browse(budget="4k")
    faro.navigator(budget="4k")  # reuses the cached manifest, revalidating
    assert route.calls.last.request.headers["if-none-match"] == '"etag-1"'


@pytest.mark.asyncio
@respx.mock
async def test_async_browse_revalidates_and_reuses_on_304():
    route = respx.get("https://api.askfaro.com/pcx/manifest").mock(
        side_effect=[_ok(), httpx.Response(304, headers={"ETag": "\"etag-1\""})]
    )
    faro = AsyncFaro()
    first = await faro.browse(budget="4k")
    second = await faro.browse(budget="4k")
    await faro.aclose()
    assert first == second
    assert route.calls.last.request.headers["if-none-match"] == '"etag-1"'
