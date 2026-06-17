"""Discovery tests: search / describe / browse (the intent -> skill path)."""

import httpx
import pytest
import respx

from askfaro import Faro, FaroError, SearchHit


_SEARCH_ENVELOPE = {
    "query": "transcribe audio",
    "limit": 10,
    "returned": 2,
    "items": [
        {
            "object_type": "skill",
            "skill_id": "audio-intelligence",
            "name": "transcribe",
            "short_description": "Transcribe speech in an audio file to text.",
            "pricing": {"pricing_mode": "fixed_per_request", "fixed_credit_cost": 3},
        },
        {
            "object_type": "tool",
            "namespace": "audio-intelligence",
            "name": "transcribe",
            "short_description": "Speech-to-text.",
            "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}},
            "pricing": {"pricing_mode": "fixed_per_request", "fixed_credit_cost": 3},
        },
    ],
}


@respx.mock
def test_search_returns_ranked_hits_without_a_key():
    # Discovery needs no API key — Faro() with no key must work.
    route = respx.get("https://api.askfaro.com/tools/search").mock(
        return_value=httpx.Response(200, json=_SEARCH_ENVELOPE)
    )
    hits = Faro().search("transcribe audio")
    assert route.called
    assert len(hits) == 2
    assert all(isinstance(h, SearchHit) for h in hits)


@respx.mock
def test_search_hit_id_is_invokable():
    respx.get("https://api.askfaro.com/tools/search").mock(
        return_value=httpx.Response(200, json=_SEARCH_ENVELOPE)
    )
    skill, tool = Faro().search("transcribe audio")
    assert skill.kind == "skill"
    assert skill.id == "audio-intelligence"          # skill id
    assert tool.kind == "tool"
    assert tool.id == "audio-intelligence/transcribe"  # namespace/tool, ready for invoke()
    assert tool.input_schema["properties"]["url"]["type"] == "string"


@respx.mock
def test_search_passes_limit_and_category():
    route = respx.get("https://api.askfaro.com/tools/search").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    Faro().search("weather", limit=3, category="data")
    req = route.calls.last.request
    assert req.url.params["q"] == "weather"
    assert req.url.params["limit"] == "3"
    assert req.url.params["category"] == "data"


def test_search_empty_query_raises():
    with pytest.raises(FaroError):
        Faro().search("   ")


@respx.mock
def test_describe_hits_tool_detail():
    route = respx.get("https://api.askfaro.com/tools/weather/current").mock(
        return_value=httpx.Response(200, json={"namespace": "weather", "name": "current"})
    )
    data = Faro().describe("weather/current")
    assert route.called
    assert data["namespace"] == "weather"


def test_describe_bad_identifier_raises():
    with pytest.raises(FaroError):
        Faro().describe("not-a-tool-id")


_PCX_MANIFEST = {
    "usage": "...",
    "root": {
        "id": "root",
        "children": ["cat-web", "cat-data"],
    },
    "nodes": {
        "cat-web": {
            "title": "Web",
            "what": "Web capabilities",
            "when": "...",
            "children": ["node-web-search", "node-research"],
        },
        "cat-data": {
            "title": "Data",
            "what": "Data capabilities",
            "when": "...",
            "children": ["node-weather"],
        },
        "node-web-search": {
            "title": "Web Search",
            "what": "Search the web for current information.",
            "when": "...",
            "skill_id": "web-search",
        },
        "node-research": {
            "title": "Research",
            "what": "Deep research with cited sources.",
            "when": "...",
            "skill_id": "research",
        },
        "node-weather": {
            "title": "Weather",
            "what": "Current and forecast weather for any location.",
            "when": "...",
            "skill_id": "weather",
        },
    },
}


@respx.mock
def test_browse_fetches_pcx_manifest():
    route = respx.get("https://api.askfaro.com/pcx/manifest").mock(
        return_value=httpx.Response(200, json={"usage": "...", "nodes": []})
    )
    manifest = Faro().browse(budget="32k")
    assert route.called
    assert route.calls.last.request.url.params["budget"] == "32k"
    assert "usage" in manifest


@respx.mock
def test_browse_accepts_integer_budget():
    # Integer budget 1500 maps to the "4k" tier on the server.
    route = respx.get("https://api.askfaro.com/pcx/manifest").mock(
        return_value=httpx.Response(200, json={"usage": "...", "nodes": []})
    )
    Faro().browse(1500)
    assert route.calls.last.request.url.params["budget"] == "4k"


@respx.mock
def test_browse_integer_budget_large_maps_to_32k():
    route = respx.get("https://api.askfaro.com/pcx/manifest").mock(
        return_value=httpx.Response(200, json={"usage": "...", "nodes": []})
    )
    Faro().browse(8000)
    assert route.calls.last.request.url.params["budget"] == "32k"


@respx.mock
def test_browse_format_text_returns_manifest_text():
    respx.get("https://api.askfaro.com/pcx/manifest").mock(
        return_value=httpx.Response(200, json=_PCX_MANIFEST)
    )
    result = Faro().browse(format="text")
    assert "manifest_text" in result
    text = result["manifest_text"]
    # All skills appear as callable ids in the text
    assert "web-search:" in text
    assert "research:" in text
    assert "weather:" in text
    # Categories rendered as headers
    assert "## Web" in text
    assert "## Data" in text


@respx.mock
def test_browse_format_text_exclude_drops_skills():
    respx.get("https://api.askfaro.com/pcx/manifest").mock(
        return_value=httpx.Response(200, json=_PCX_MANIFEST)
    )
    result = Faro().browse(format="text", exclude=["web-search", "research"])
    text = result["manifest_text"]
    assert "web-search" not in text
    assert "research" not in text
    assert "weather:" in text


def test_browse_invalid_format_raises():
    with pytest.raises(FaroError):
        Faro().browse(format="xml")


@respx.mock
def test_discovery_sends_bearer_when_key_present():
    route = respx.get("https://api.askfaro.com/tools/search").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    Faro(api_key="faro_test").search("x")
    assert route.calls.last.request.headers["authorization"] == "Bearer faro_test"


@respx.mock
def test_discovery_http_error_raises():
    from askfaro import RemoteError

    respx.get("https://api.askfaro.com/tools/search").mock(
        return_value=httpx.Response(503, json={"detail": "down"})
    )
    with pytest.raises(RemoteError):
        Faro().search("x")
