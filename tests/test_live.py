"""Live contract tests — run against the REAL Faro endpoints, not mocks.

Mocked unit tests freeze a snapshot of the API contract and keep passing even when
the real contract drifts. That is exactly how the SDK's remote `invoke()` kept
"passing" (a mock returned 200) while the live endpoint had started returning 403.
These tests exercise the real paths the SDK actually uses, so a contract change
FAILS here instead of shipping.

Excluded from the default offline run (`addopts = -m 'not live'`); select with
`-m live`. The authed checks need `FARO_API_KEY`; the probe is an unknown skill, so
it never bills. They skip with a clear reason when the key is unset.
"""

import os
import uuid

import httpx
import pytest

import askfaro.aclient as _aclient
import askfaro.client as _client
from askfaro import AsyncFaro, Faro

# A free skill that the bundled core can also run on-device. Structured intent,
# $0 either way (used both for the on-device routing check and the backend
# idempotency check, which drives the agent directly).
_FREE_SKILL = "astronomy"
_FREE_INTENT = {"latitude": 48.85, "longitude": 2.35, "date": "2026-06-21"}

pytestmark = pytest.mark.live

_KEY = os.environ.get("FARO_API_KEY")
# Which environment to validate. Defaults to prod (what users hit); point at
# staging (FARO_API_BASE / FARO_SKILL_BASE) to catch drift before it promotes,
# with a non-prod key. The SDK's skill-agent URL is fixed by design, so the live
# test overrides the module constant rather than reopening a public knob.
_API = os.environ.get("FARO_API_BASE", _client.DEFAULT_BASE_URL)
_SKILL = os.environ.get("FARO_SKILL_BASE", _client.SKILL_AGENT_URL)
_client.SKILL_AGENT_URL = _SKILL
_aclient.SKILL_AGENT_URL = _SKILL

needs_key = pytest.mark.skipif(
    not _KEY, reason="set FARO_API_KEY to run the authed live contract checks"
)
# An id that cannot exist, so the full run() path is exercised (auth + skill agent
# + canonical envelope) with zero billing — the agent answers not_found first.
_PROBE_SKILL = "__askfaro_contract_probe__"


def _client_for(key=None):
    return Faro(api_key=key, base_url=_API)


def test_invoke_core_tool_runs_in_the_published_wheel():
    # The shipped wheel must carry a working core: calc runs on-device, no key, $0.
    r = Faro().invoke("calc/evaluate", {"expression": "2 + 2 * 3"})
    assert r.ok and r.local and r.data["result"] == 8


def test_run_routes_a_free_skill_on_device():
    # Transparent routing in the published wheel: run() of a free core skill
    # executes in-core — no key, no network, $0 — and yields the canonical envelope.
    r = Faro().run(_FREE_SKILL, _FREE_INTENT)
    assert r.ok and r.local, f"free skill did not run on-device: local={r.local} status={r.status!r}"
    assert (r.meta.get("credits_charged")) in (0, 0.0)
    assert r.data and r.data.get("sunrise"), "on-device astronomy returned no result"


@needs_key
def test_run_routes_a_non_core_capability_to_the_skill_agent():
    # The other half of transparent routing: a capability the core can't run goes
    # to the live skill agent. The unknown probe id keeps it $0 (not_found first).
    r = _client_for(_KEY).run(_PROBE_SKILL, {"prompt": "x"})
    assert r.local is False, "a non-core capability must route to the agent, not on-device"
    assert r.status == "failed" and (r.error or {}).get("code") == "not_found"


def test_search_returns_skills_from_the_real_catalog():
    # Discovery contract: the public catalog answers, and its leaves are skills.
    hits = _client_for().search("generate an image", limit=5)
    assert hits, "live search returned no hits — discovery contract broken"
    assert any(h.kind == "skill" and h.id for h in hits), (
        "search returned no runnable skill — the public surface should be skill-only"
    )


@needs_key
def test_run_reaches_the_real_skill_agent_and_speaks_the_envelope():
    # The exact regression class the mocks hid: prove run() reaches the live skill
    # agent and gets a canonical SkillResult back. An unknown skill -> a failed
    # envelope with not_found, zero billing.
    r = _client_for(_KEY).run(_PROBE_SKILL, {"prompt": "x"})
    assert r.status == "failed", f"expected a failed envelope, got status={r.status!r}"
    assert (r.error or {}).get("code") == "not_found", (
        f"run() contract drift: expected error.code 'not_found', got {r.error!r}"
    )


@needs_key
async def test_async_run_reaches_the_real_skill_agent():
    async with AsyncFaro(api_key=_KEY, base_url=_API) as faro:
        r = await faro.run(_PROBE_SKILL, {"prompt": "x"})
    assert r.status == "failed" and (r.error or {}).get("code") == "not_found"


@needs_key
def test_idempotency_key_replays_a_prior_run_against_the_real_backend():
    """Paired live check for the mocked idempotency_key forwarding in
    tests/test_run.py: the REAL backend must replay a repeated key instead of
    re-running, so the mock can't quietly drift away from a backend that ignores
    the field (an old agent would silently drop it -> false safety).

    Driven against the skill agent + faro-api directly: the SDK now routes core
    skills on-device, where idempotency is moot (free, deterministic, no charge),
    so the backend replay contract lives in the agent -> faro-api path the SDK's
    run() payload feeds. A free skill keeps this at $0.
    """
    key = f"askfaro-contract-{uuid.uuid4()}"
    headers = {"Authorization": f"Bearer {_KEY}"}
    body = {"intent": _FREE_INTENT, "idempotency_key": key}

    with httpx.Client(base_url=_SKILL, headers=headers, timeout=30.0) as agent:
        first = agent.post(f"/skills/{_FREE_SKILL}/run", json=body)
        second = agent.post(f"/skills/{_FREE_SKILL}/run", json=body)
    assert first.status_code == 200, f"first run failed: {first.status_code} {first.text}"
    assert second.status_code == 200, f"second run failed: {second.status_code} {second.text}"
    stored = first.json()
    assert (stored.get("meta") or {}).get("credits_charged") in (0, 0.0), "free skill must be $0"
    assert second.json() == stored, "repeat run with the same key did not return the stored envelope"

    # Cross-check the reservation on faro-api: the key is recorded completed and
    # carries the stored envelope — proof the replay came from the idempotency
    # store, not a coincidental re-computation of a deterministic skill.
    with httpx.Client(base_url=_API, headers=headers, timeout=30.0) as api:
        probe = api.post("/skills/runs/idempotency/reserve", json={"idempotency_key": key})
    assert probe.status_code == 200, (
        f"idempotency reserve endpoint missing/failed: {probe.status_code} {probe.text} "
        "(a 404 means the backend isn't deployed)"
    )
    reservation = probe.json()
    assert reservation.get("state") == "completed", (
        f"expected a completed reservation for the used key, got {reservation!r}"
    )
    assert reservation.get("response") == stored, (
        "the stored idempotency envelope does not match the first run's result"
    )
