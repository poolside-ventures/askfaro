"""Capability tiers (Track D): tier_of() introspection + run(require_tier=) guard.

The on-device tier depends on whether the bundled Rust core is built into this
environment, so the local-path assertions derive the capability from
`local_namespaces()` and skip when no core is present (matching test_local /
test_routing). The remote-path assertions hold regardless.
"""

import httpx
import pytest
import respx

from askfaro import Faro, FaroError
from askfaro.local import local_namespaces

SKILL = "https://skill.askfaro.com"

_local_ns = sorted(local_namespaces())
_needs_core = pytest.mark.skipif(not _local_ns, reason="bundled core not built in this environment")


def _ok():
    return {"faro_envelope": "1", "status": "success", "result": {"kind": "information", "data": {}}, "meta": {}}


def test_tier_of_remote_capability():
    assert Faro().tier_of("image") == "remote"  # never in the core


def test_tier_of_rejects_empty():
    with pytest.raises(FaroError):
        Faro().tier_of("")


def test_require_local_refuses_a_remote_capability():
    # A hard no-network guarantee: refuse rather than hit the skill agent.
    with pytest.raises(FaroError) as ei:
        Faro(api_key="faro_x").run("image", "a red bike", require_tier="local")
    assert ei.value.code == "tier_unavailable"


@respx.mock
def test_require_remote_allows_a_remote_capability():
    respx.post(f"{SKILL}/skills/image/run").mock(return_value=httpx.Response(200, json=_ok()))
    r = Faro(api_key="faro_x").run("image", "a red bike", require_tier="remote")
    assert r.local is False


def test_invalid_require_tier():
    with pytest.raises(FaroError) as ei:
        Faro(api_key="faro_x").run("image", "a red bike", require_tier="bogus")
    assert ei.value.code == "validation_error"


@_needs_core
def test_tier_of_local_capability():
    assert Faro().tier_of(_local_ns[0]) == "local"


@_needs_core
def test_require_remote_refuses_a_local_capability():
    faro = Faro()
    cap = next(c for c in ("astronomy", "calc", "units", _local_ns[0]) if faro.tier_of(c) == "local")
    with pytest.raises(FaroError) as ei:
        faro.run(cap, {}, require_tier="remote")
    assert ei.value.code == "tier_unavailable"
