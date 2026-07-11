"""Async Faro client.

`AsyncFaro` mirrors `Faro` for server-side consumers running on an event loop
(e.g. an async FastAPI backend): every network method is a coroutine backed by
`httpx.AsyncClient`, so you `await` it directly instead of wrapping a sync call in
`asyncio.to_thread`.

On-device tools still run in the bundled Rust core, which is synchronous and
in-process (sub-millisecond), so the local path is called directly without
awaiting — there is no blocking I/O to offload.

    from askfaro import AsyncFaro

    async with AsyncFaro(api_key="faro_...") as faro:
        hits = await faro.search("transcribe an audio file")
        r = await faro.run("image", {"prompt": "a red bicycle"})
"""

from __future__ import annotations

import os
from typing import Optional

from askfaro._capabilities import Capabilities, resolve_capabilities
from askfaro.client import (
    DEFAULT_BASE_URL,
    SKILL_AGENT_URL,
    _split,
)
from askfaro.errors import FaroError, RemoteError
from askfaro.client import TIER_LOCAL, TIER_REMOTE, _TIERS
from askfaro.local import can_run_local, local_namespaces, run_local, split_skill_id
from askfaro.result import InvokeResult, SearchHit


class AsyncFaro:
    """Async counterpart of `Faro` with the identical surface.

    Same constructor and semantics as `Faro`; the only difference is that the
    network methods (`search`, `describe`, `browse`, `run`) are coroutines.
    On-device `invoke()` runs in the synchronous embedded core (no await needed).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        capabilities: Capabilities | None = None,
        manifest_cache: bool | str | os.PathLike = True,
    ):
        self._api_key = api_key or os.environ.get("FARO_API_KEY")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # See Faro.__init__: resolved once, applied to browse/search/run.
        self._caps = resolve_capabilities(capabilities)
        self._discovery_http = None  # public discovery endpoints; no key required
        self._skill_http = None  # skill agent (run); created on first run()
        # See Faro.__init__: browse()/navigator() cache the pcx manifest by ETag.
        self._manifest_cache = manifest_cache
        self._manifest_store = None

    # ---- capability introspection -------------------------------------------
    # Local capability is a property of the in-process core, not the event loop,
    # so these stay synchronous and identical to `Faro`.

    @staticmethod
    def local_namespaces() -> frozenset[str]:
        from askfaro.local import local_namespaces

        return local_namespaces()

    @staticmethod
    def core_available() -> bool:
        from askfaro.local import core_available

        return core_available()

    @staticmethod
    def core_version() -> str | None:
        from askfaro.local import core_version

        return core_version()

    # ---- discovery -----------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        category: str | None = None,
    ) -> list[SearchHit]:
        """Find skills by intent. Hybrid lexical + semantic search over the
        public catalog. No API key required. See `Faro.search`."""
        if not query or not query.strip():
            raise FaroError("search(query) needs a non-empty query.", "validation_error")
        body: dict = {"q": query, "limit": limit}
        if category:
            body["category"] = category
        # POST keeps conversation-derived queries out of URLs and access logs;
        # fall back to GET for servers that predate POST /tools/search.
        resp = await self._post("/tools/search", body)
        if resp.status_code in (404, 405):
            envelope = await self._get("/tools/search", body)
        else:
            envelope = self._json_or_raise(resp)
        items = envelope.get("items", []) if isinstance(envelope, dict) else []
        hits = [SearchHit(item) for item in items]
        return [h for h in hits if h.kind != "skill" or self._caps.allows(h.id)]

    async def describe(self, target: str) -> dict:
        """Schema for a skill or a raw tool. No API key required.

        A bare id (e.g. "contact-data") is a SKILL: returns its capability — the
        intent inputs and priced operations you send to `run` — via
        `GET /catalog/public/{id}`. A "namespace/tool" returns a raw tool's full
        input schema and pricing via `GET /tools/{namespace}/{tool}`."""
        if "/" in target or "." in target:
            namespace, name = _split(target)
            return await self._get(f"/tools/{namespace}/{name}")
        return await self._get(f"/catalog/public/{target}")

    async def browse(
        self,
        budget: str | int = "4k",
        *,
        format: str = "json",
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> dict:
        """Fetch the progressive-context (pcx) catalog map. No API key required.
        See `Faro.browse` for full parameter documentation."""
        from askfaro._browse import budget_to_tier, budget_to_tokens, filter_manifest, render_budget_text

        if format not in ("json", "text"):
            raise FaroError(
                f"browse() format must be 'json' or 'text', got {format!r}.",
                "validation_error",
            )

        tier = budget_to_tier(budget)
        manifest = await self._cached_manifest(tier)
        caps = self._caps.overlay(include=include, exclude=exclude)

        if format == "json":
            return filter_manifest(manifest, caps)

        return {"manifest_text": render_budget_text(manifest, budget_to_tokens(budget), caps)}

    async def navigator(self, budget: str | int = "4k", *, include: list[str] | None = None, exclude: list[str] | None = None):
        """A budget-sized, capability-filtered `NavSession` over the catalog.
        See `Faro.navigator`. (The fetch is awaited; navigation is then local.)"""
        from askfaro._browse import budget_to_tier, budget_to_tokens, filter_manifest
        from askfaro_progressive_context import Manifest, NavSession

        caps = self._caps.overlay(include=include, exclude=exclude)
        manifest = await self._cached_manifest(budget_to_tier(budget))
        m = Manifest.from_dict(filter_manifest(manifest, caps))
        return NavSession(m, budget=budget_to_tokens(budget))

    # ---- invocation ----------------------------------------------------------

    async def invoke(self, tool: str, arguments: dict | None = None) -> InvokeResult:
        """Advanced: *force* on-device execution of a specific core tool in the
        embedded core — no API key, no network, no credits. The core is in-process
        so there is no real I/O to await, but this stays a coroutine for a uniform
        async surface. Most callers should use `run()`, which routes on-device
        automatically. Only the core's free tools are invocable here. See
        `Faro.invoke`.
        """
        namespace, name = _split(tool)
        if not can_run_local(namespace):
            local = ", ".join(sorted(local_namespaces())) or "none in this build"
            raise FaroError(
                f"{tool!r} is not an on-device tool, so it can't be invoke()d. "
                f"invoke() forces on-device execution of the embedded core's free "
                f"tools ({local}). Use run(capability, intent) to reach anything else.",
                "validation_error",
            )
        return InvokeResult(run_local(namespace, name, arguments), local=True)

    def tier_of(self, capability: str) -> str:
        """Which execution tier `capability` will run at without running it:
        ``"local"`` (in-core, guaranteed) or ``"remote"`` (skill agent, billed).
        See `Faro.tier_of`."""
        if not capability or not isinstance(capability, str):
            raise FaroError("tier_of(capability) needs a capability id.", "validation_error")
        namespace, _ = split_skill_id(capability)
        return TIER_LOCAL if can_run_local(namespace) else TIER_REMOTE

    # ---- capability execution -------------------------------------------------

    async def run(
        self,
        capability: str,
        intent: dict | str,
        *,
        max_credits: float | None = None,
        confirm_above: float | None = None,
        continuation: str | None = None,
        idempotency_key: str | None = None,
        require_tier: str | None = None,
    ) -> InvokeResult:
        """Run a capability end-to-end: intent in, normalized envelope out.

        Routing is transparent: if the bundled core can run `capability`
        on-device it does (free, no key, no network); otherwise it POSTs to the
        hosted skill agent (needs an API key). Pass `idempotency_key` to make a
        retried run replay the prior success instead of charging again.
        See `Faro.run`."""
        if not capability or not isinstance(capability, str):
            raise FaroError("run(capability, intent) needs a capability id.", "validation_error")
        if not self._caps.allows(capability):
            raise FaroError(
                f"{capability!r} is excluded by this client's capability config; "
                f"adjust the Capabilities filter (or askfaro.toml) to run it.",
                "capability_excluded",
            )
        if isinstance(intent, str):
            intent = {"prompt": intent}
        if not isinstance(intent, dict):
            raise FaroError(
                'run() intent must be a dict or a string, e.g. {"prompt": "..."}.',
                "validation_error",
            )

        # Transparent on-device routing: the synchronous in-core path has no I/O to
        # await, so it returns directly — no key, no network, same envelope.
        namespace, operation = split_skill_id(capability)
        actual_tier = TIER_LOCAL if can_run_local(namespace) else TIER_REMOTE
        if require_tier is not None:
            if require_tier not in _TIERS:
                raise FaroError(
                    f"require_tier must be one of {list(_TIERS)}, got {require_tier!r}.",
                    "validation_error",
                )
            if actual_tier != require_tier:
                raise FaroError(
                    f"{capability!r} runs on the {actual_tier!r} tier, but require_tier="
                    f"{require_tier!r} was requested. Routing is not degraded across tiers.",
                    "tier_unavailable",
                )

        if actual_tier == TIER_LOCAL:
            return InvokeResult(run_local(namespace, operation, intent), local=True)

        if not self._api_key:
            raise FaroError(
                "An API key is required to run skills. Pass api_key=... or set FARO_API_KEY.",
                "auth_required",
            )

        payload: dict = {"intent": intent}
        if max_credits is not None:
            payload["max_credits"] = max_credits
        if confirm_above is not None:
            payload["confirm_above"] = confirm_above
        if continuation is not None:
            payload["continuation"] = continuation
        if idempotency_key is not None:
            payload["idempotency_key"] = idempotency_key

        client = self._ensure_skill_http()
        try:
            resp = await client.post(f"/skills/{capability}/run", json=payload)
        except Exception as e:  # httpx network/timeout errors
            raise RemoteError(
                f"Network error calling the Faro skill agent: {e}", "network_error", retryable=True
            )
        return self._result_or_raise(resp)

    @staticmethod
    def _result_or_raise(resp) -> InvokeResult:
        if resp.is_success:
            return InvokeResult(resp.json(), local=False)
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        retryable = resp.status_code >= 500 or resp.status_code == 429
        raise RemoteError(str(detail), "remote_error", status=resp.status_code, retryable=retryable)

    # ---- transports ----------------------------------------------------------
    # Async clients are constructed lazily; building an httpx.AsyncClient does not
    # require a running loop, so the constructor stays sync.

    def _ensure_discovery_http(self):
        if self._discovery_http is None:
            import httpx

            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._discovery_http = httpx.AsyncClient(
                base_url=self._base_url, headers=headers, timeout=self._timeout
            )
        return self._discovery_http

    def _ensure_skill_http(self):
        if self._skill_http is None:
            import httpx

            self._skill_http = httpx.AsyncClient(
                base_url=SKILL_AGENT_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        return self._skill_http

    async def _get(self, path: str, params: dict | None = None):
        client = self._ensure_discovery_http()
        try:
            resp = await client.get(path, params=params)
        except Exception as e:  # httpx network/timeout errors
            raise RemoteError(f"Network error calling Faro: {e}", "network_error", retryable=True)
        return self._json_or_raise(resp)

    async def _post(self, path: str, body: dict):
        """POST returning the raw response (callers decide how to handle
        status, e.g. search's GET fallback on 404/405)."""
        client = self._ensure_discovery_http()
        try:
            return await client.post(path, json=body)
        except Exception as e:  # httpx network/timeout errors
            raise RemoteError(f"Network error calling Faro: {e}", "network_error", retryable=True)

    @staticmethod
    def _json_or_raise(resp):
        if resp.is_success:
            return resp.json()
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        retryable = resp.status_code >= 500 or resp.status_code == 429
        raise RemoteError(str(detail), "remote_error", status=resp.status_code, retryable=retryable)

    async def _conditional_get(self, path: str, params: dict | None, etag: str | None):
        """Async GET that surfaces a 304 for ETag revalidation; returns
        (status_code, response_etag, body). Used by the manifest cache."""
        client = self._ensure_discovery_http()
        headers = {"If-None-Match": etag} if etag else {}
        try:
            resp = await client.get(path, params=params, headers=headers)
        except Exception as e:
            raise RemoteError(f"Network error calling Faro: {e}", "network_error", retryable=True)
        if resp.status_code == 304:
            return 304, resp.headers.get("ETag") or etag, None
        return resp.status_code, resp.headers.get("ETag"), self._json_or_raise(resp)

    async def _cached_manifest(self, tier: str) -> dict:
        """The pcx manifest for `tier`, served from the cache and revalidated by
        ETag. Shared by browse() and navigator()."""
        from askfaro._pcx_cache import aload_manifest, make_store

        if self._manifest_store is None:
            self._manifest_store = make_store(self._manifest_cache)
        return await aload_manifest(self._conditional_get, self._base_url, tier, self._manifest_store)

    # ---- lifecycle -----------------------------------------------------------

    async def aclose(self) -> None:
        for attr in ("_discovery_http", "_skill_http"):
            client = getattr(self, attr)
            if client is not None:
                await client.aclose()
                setattr(self, attr, None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()
