"""Shared test fixtures.

Isolate the pcx manifest cache to a per-test temp dir so browse()/navigator()
tests start cold (and assert real network calls) without touching the user's real
cache or leaking state between tests.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_manifest_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("askfaro._pcx_cache._CACHE_DIR", tmp_path / "pcx")
