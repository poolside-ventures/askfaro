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

import pytest

from askfaro import AsyncFaro, Faro

pytestmark = pytest.mark.live

_KEY = os.environ.get("FARO_API_KEY")
needs_key = pytest.mark.skipif(
    not _KEY, reason="set FARO_API_KEY to run the authed live contract checks"
)
# An id that cannot exist, so the full run() path is exercised (auth + skill agent
# + canonical envelope) with zero billing — the agent answers not_found first.
_PROBE_SKILL = "__askfaro_contract_probe__"


def test_invoke_core_tool_runs_in_the_published_wheel():
    # The shipped wheel must carry a working core: calc runs on-device, no key, $0.
    r = Faro().invoke("calc/evaluate", {"expression": "2 + 2 * 3"})
    assert r.ok and r.local and r.data["result"] == 8


def test_search_returns_skills_from_the_real_catalog():
    # Discovery contract: the public catalog answers, and its leaves are skills.
    hits = Faro().search("generate an image", limit=5)
    assert hits, "live search returned no hits — discovery contract broken"
    assert any(h.kind == "skill" and h.id for h in hits), (
        "search returned no runnable skill — the public surface should be skill-only"
    )


@needs_key
def test_run_reaches_the_real_skill_agent_and_speaks_the_envelope():
    # The exact regression class the mocks hid: prove run() reaches the live skill
    # agent and gets a canonical SkillResult back. An unknown skill -> a failed
    # envelope with not_found, zero billing.
    r = Faro(api_key=_KEY).run(_PROBE_SKILL, {"prompt": "x"})
    assert r.status == "failed", f"expected a failed envelope, got status={r.status!r}"
    assert (r.error or {}).get("code") == "not_found", (
        f"run() contract drift: expected error.code 'not_found', got {r.error!r}"
    )


@needs_key
async def test_async_run_reaches_the_real_skill_agent():
    async with AsyncFaro(api_key=_KEY) as faro:
        r = await faro.run(_PROBE_SKILL, {"prompt": "x"})
    assert r.status == "failed" and (r.error or {}).get("code") == "not_found"
