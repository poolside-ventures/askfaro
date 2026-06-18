"""Capability curation: the client-side include/exclude filter applied to
browse(), search(), and run()."""

import httpx
import pytest
import respx

from askfaro import Capabilities, Faro, FaroError

API = "https://api.askfaro.com"

_PCX_MANIFEST = {
    "usage": "...",
    "root": {"id": "root", "children": ["cat-web", "cat-data"]},
    "nodes": {
        "cat-web": {"title": "Web", "what": "Web capabilities", "children": ["n-web-search", "n-research"]},
        "cat-data": {"title": "Data", "what": "Data capabilities", "children": ["n-weather"]},
        "n-web-search": {"title": "Web Search", "what": "search the web", "skill_id": "web-search"},
        "n-research": {"title": "Research", "what": "cited research", "skill_id": "research"},
        "n-weather": {"title": "Weather", "what": "forecasts", "skill_id": "weather"},
    },
}

_SEARCH = {
    "items": [
        {"object_type": "skill", "skill_id": "web-search", "short_description": "search"},
        {"object_type": "skill", "skill_id": "weather", "short_description": "forecast"},
    ]
}


# ---- the filter primitive ----------------------------------------------------


def test_exclude_blocks_listed_ids():
    caps = Capabilities(exclude=["web-search", "research"])
    assert not caps.allows("web-search")
    assert not caps.allows("research")
    assert caps.allows("weather")


def test_include_is_an_allowlist():
    caps = Capabilities(include=["weather"])
    assert caps.allows("weather")
    assert not caps.allows("web-search")


def test_empty_filter_allows_everything():
    caps = Capabilities()
    assert caps.is_empty
    assert caps.allows("anything")


def test_overlay_unions_exclude_and_replaces_include():
    base = Capabilities(exclude=["web-search"])
    over = base.overlay(exclude=["research"])
    assert not over.allows("web-search")  # kept from base
    assert not over.allows("research")  # added per-call
    repl = base.overlay(include=["weather"])
    assert repl.allows("weather") and not repl.allows("web-search")


# ---- config resolution -------------------------------------------------------


def test_env_vars_resolve(monkeypatch):
    from askfaro._capabilities import resolve_capabilities

    monkeypatch.setenv("ASKFARO_EXCLUDE", "web-search, research")
    caps = resolve_capabilities(None)
    assert not caps.allows("web-search") and caps.allows("weather")


def test_askfaro_toml_resolves(tmp_path, monkeypatch):
    from askfaro._capabilities import resolve_capabilities

    (tmp_path / "askfaro.toml").write_text('[capabilities]\nexclude = ["image", "video"]\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ASKFARO_EXCLUDE", raising=False)
    monkeypatch.delenv("ASKFARO_INCLUDE", raising=False)
    caps = resolve_capabilities(None)
    assert not caps.allows("image") and caps.allows("weather")


def test_explicit_arg_beats_env(monkeypatch):
    from askfaro._capabilities import resolve_capabilities

    monkeypatch.setenv("ASKFARO_EXCLUDE", "weather")
    caps = resolve_capabilities(Capabilities(exclude=["image"]))
    assert caps.allows("weather") and not caps.allows("image")


# ---- applied to browse -------------------------------------------------------


@respx.mock
def test_browse_json_prunes_excluded_skills():
    respx.get(f"{API}/pcx/manifest").mock(return_value=httpx.Response(200, json=_PCX_MANIFEST))
    faro = Faro(capabilities=Capabilities(exclude=["web-search", "research"]))
    manifest = faro.browse()
    nodes = manifest["nodes"]
    assert "n-web-search" not in nodes and "n-research" not in nodes
    assert "n-weather" in nodes
    # The now-empty Web category is dropped, Data remains.
    assert manifest["root"]["children"] == ["cat-data"]


@respx.mock
def test_browse_text_reflects_filter():
    respx.get(f"{API}/pcx/manifest").mock(return_value=httpx.Response(200, json=_PCX_MANIFEST))
    faro = Faro(capabilities=Capabilities(include=["weather"]))
    text = faro.browse(format="text")["manifest_text"]
    assert "weather:" in text
    assert "web-search" not in text and "research" not in text


@respx.mock
def test_browse_per_call_exclude_overrides_config():
    respx.get(f"{API}/pcx/manifest").mock(return_value=httpx.Response(200, json=_PCX_MANIFEST))
    faro = Faro()  # no config
    manifest = faro.browse(exclude=["weather"])
    assert "n-weather" not in manifest["nodes"]
    assert "n-web-search" in manifest["nodes"]


# ---- applied to search -------------------------------------------------------


@respx.mock
def test_search_hides_excluded_skills():
    respx.get(f"{API}/tools/search").mock(return_value=httpx.Response(200, json=_SEARCH))
    faro = Faro(capabilities=Capabilities(exclude=["web-search"]))
    hits = faro.search("anything")
    ids = {h.id for h in hits}
    assert ids == {"weather"}


# ---- applied to run ----------------------------------------------------------


def test_run_refuses_excluded_capability():
    faro = Faro(api_key="faro_test", capabilities=Capabilities(exclude=["image"]))
    with pytest.raises(FaroError) as ei:
        faro.run("image", "a red bicycle")
    assert ei.value.code == "capability_excluded"


def test_run_excluded_blocks_even_on_device():
    # calc would route on-device, but exclusion is checked first.
    faro = Faro(capabilities=Capabilities(exclude=["calc"]))
    with pytest.raises(FaroError) as ei:
        faro.run("calc", {"expression": "1+1"})
    assert ei.value.code == "capability_excluded"
