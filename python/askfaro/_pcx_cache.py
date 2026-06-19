"""On-disk caching of the pcx catalog manifest for `browse()` / `navigator()`.

The manifest changes only when the catalog is rebuilt, so re-downloading it on
every call is wasteful. We cache it and revalidate with a conditional request,
using askfaro-progressive-context's `ManifestLoader` / `AsyncManifestLoader` +
`FileStore` (the identity-revalidate pattern): a warm cache costs one cheap 304,
and a rebuilt catalog is always picked up because the ETag changes.

The cache is keyed by API host *and* budget tier, so different deployments and
budgets never collide. The on-disk store is shared with the `askfaro` CLI (same
path), so they revalidate against each other's cache.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from askfaro_progressive_context import (
    AsyncManifestLoader,
    FetchOutcome,
    FileStore,
    ManifestKey,
    ManifestLoader,
    MemoryStore,
    identity_of,
)

# Shared with the askfaro CLI. Overridable per-client via Faro(manifest_cache=...);
# tests monkeypatch this module global for isolation.
_CACHE_DIR = Path(os.environ.get("ASKFARO_CACHE_DIR") or (Path.home() / ".cache" / "askfaro")) / "pcx"


def make_store(setting: bool | str | os.PathLike):
    """Build a manifest store from the `manifest_cache` constructor setting:

    - ``True``  -> on-disk `FileStore` at the shared cache dir (the default)
    - ``False`` -> process-local `MemoryStore` (no disk writes; still revalidates)
    - a path    -> on-disk `FileStore` at that directory
    """
    if setting is True:
        return FileStore(_CACHE_DIR)
    if setting is False:
        return MemoryStore()
    return FileStore(setting)


def _key(base_url: str, tier: str) -> ManifestKey:
    host = urlparse(base_url).netloc or "default"
    return ManifestKey(source_id=f"{host}:faro-catalog", budget=tier)


def load_manifest(conditional_get, base_url: str, tier: str, store) -> dict:
    """Sync: return the pcx manifest for `tier`, revalidated against the origin.

    `conditional_get(path, params, etag) -> (status, etag, body)` issues a GET that
    surfaces a 304 instead of raising (see `Faro._conditional_get`).
    """

    def fetch(key: ManifestKey, known):
        status, etag, body = conditional_get("/pcx/manifest", {"budget": key.budget}, known)
        if status == 304:
            return FetchOutcome.unchanged()
        return FetchOutcome.fresh(etag or identity_of(body), body)

    return ManifestLoader(fetch=fetch, store=store).load_dict(_key(base_url, tier))


async def aload_manifest(aconditional_get, base_url: str, tier: str, store) -> dict:
    """Async equivalent of `load_manifest`, over an awaited conditional GET."""

    async def fetch(key: ManifestKey, known):
        status, etag, body = await aconditional_get("/pcx/manifest", {"budget": key.budget}, known)
        if status == 304:
            return FetchOutcome.unchanged()
        return FetchOutcome.fresh(etag or identity_of(body), body)

    return await AsyncManifestLoader(fetch=fetch, store=store).load_dict(_key(base_url, tier))
