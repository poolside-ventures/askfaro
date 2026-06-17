"""invoke() runs on-device free tools only; everything remote is a skill (run())."""

import pytest

from askfaro import Faro, FaroError


def test_invoke_runs_core_namespace_locally():
    # No key, no network: a core tool runs in the embedded core, on-device.
    r = Faro().invoke("calc/evaluate", {"expression": "1 + 1"})
    assert r.local is True
    assert r.data["result"] == 2


def test_invoke_non_core_namespace_raises_pointing_to_run():
    # A remote/paid capability is not invoke()-able (raw remote tools aren't
    # directly callable); the error tells the caller to use run().
    with pytest.raises(FaroError) as ei:
        Faro().invoke("weather/current", {"city": "Paris"})
    assert "run(" in str(ei.value)


def test_mode_kwarg_removed():
    # The local-first `mode` knob is gone — invoke() is on-device only.
    with pytest.raises(TypeError):
        Faro(mode="remote")  # type: ignore[call-arg]
