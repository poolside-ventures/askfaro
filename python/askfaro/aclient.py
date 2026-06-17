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

from askfaro.client import (
    DEFAULT_BASE_URL,
    SKILL_AGENT_URL,
    _MODES,
    _split,
)
from askfaro.errors import FaroError, RemoteError
from askfaro.local import can_run_local, run_local
from askfaro.result import InvokeResult, SearchHit


class AsyncFaro:
    """Async counterpart of `Faro` with the identical routing and surface.

    Same constructor and semantics as `Faro`; the only difference is that the
    network methods (`search`, `describe`, `browse`, remote `invoke`, `run`) are
    coroutines. On-device `invoke()` runs in the synchronous embedded core.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        mode: str = "auto",
        timeout: float = 30.0,
    ):
        if mode not in _MODES:
            raise FaroError(f"mode must be one of {_MODES}, got {mode!r}.", "validation_error")
        self._api_key = api_key or os.environ.get("FARO_API_KEY")
        self._base_url = base_url.rstrip("/")
        self.mode = mode
        self._timeout = timeout
        self._http = None  # authed backend transport; created on first remote call
        self._discovery_http = None  # public discovery endpoints; no key required
        self._skill_http = None  # skill agent (run); created on first run()

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
        """Find skills/tools by intent. Hybrid lexical + semantic search over the
        public catalog. No API key required. See `Faro.search`."""
        if not query or not query.strip():
            raise FaroError("search(query) needs a non-empty query.", "validation_error")
        params: dict = {"q": query, "limit": limit}
        if category:
            params["category"] = category
        envelope = await self._get("/tools/search", params)
        items = envelope.get("items", []) if isinstance(envelope, dict) else []
        return [SearchHit(item) for item in items]

    async def describe(self, tool: str) -> dict:
        """Full input schema, long description, and pricing for one tool.
        No API key required."""
        namespace, name = _split(tool)
        return await self._get(f"/tools/{namespace}/{name}")

    async def browse(self, *, budget: str = "4k") -> dict:
        """Fetch the progressive-context (pcx) catalog map. No API key required.
        See `Faro.browse`."""
        return await self._get("/pcx/manifest", {"budget": budget})

    # ---- invocation ----------------------------------------------------------

    async def invoke(
        self, tool: str, arguments: dict | None = None, *, mode: str | None = None
    ) -> InvokeResult:
        """Invoke `namespace/tool`, returning a normalized InvokeResult.

        On-device tools run in the synchronous embedded core (no await needed);
        remote tools are awaited over the network. See `Faro.invoke`.
        """
        eff_mode = mode or self.mode
        if eff_mode not in _MODES:
            raise FaroError(f"mode must be one of {_MODES}, got {eff_mode!r}.", "validation_error")

        namespace, name = _split(tool)

        if eff_mode == "remote":
            return await self._invoke_remote(namespace, name, arguments)
        if eff_mode == "local":
            return InvokeResult(run_local(namespace, name, arguments), local=True)
        # auto
        if can_run_local(namespace):
            return InvokeResult(run_local(namespace, name, arguments), local=True)
        return await self._invoke_remote(namespace, name, arguments)

    # ---- skills --------------------------------------------------------------

    async def run(
        self,
        skill: str,
        intent: dict | str,
        *,
        max_credits: float | None = None,
        confirm_above: float | None = None,
        continuation: str | None = None,
    ) -> InvokeResult:
        """Run a skill end-to-end: intent in, normalized envelope out. Requires an
        API key. See `Faro.run`."""
        if not skill or not isinstance(skill, str):
            raise FaroError("run(skill, intent) needs a skill id.", "validation_error")
        if isinstance(intent, str):
            intent = {"prompt": intent}
        if not isinstance(intent, dict):
            raise FaroError(
                'run() intent must be a dict or a string, e.g. {"prompt": "..."}.',
                "validation_error",
            )
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

        client = self._ensure_skill_http()
        try:
            resp = await client.post(f"/skills/{skill}/run", json=payload)
        except Exception as e:  # httpx network/timeout errors
            raise RemoteError(
                f"Network error calling the Faro skill agent: {e}", "network_error", retryable=True
            )
        return self._result_or_raise(resp)

    async def _invoke_remote(
        self, namespace: str, name: str, arguments: dict | None
    ) -> InvokeResult:
        client = self._ensure_http()
        try:
            resp = await client.post(
                f"/invoke/{namespace}/{name}", json={"arguments": arguments or {}}
            )
        except Exception as e:  # httpx network/timeout errors
            raise RemoteError(f"Network error calling Faro: {e}", "network_error", retryable=True)
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

    def _ensure_http(self):
        if self._http is None:
            import httpx

            if not self._api_key:
                raise FaroError(
                    "An API key is required for backend calls. Pass api_key=... or set FARO_API_KEY. "
                    "(Tools the core runs on-device need no key.)",
                    "auth_required",
                )
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        return self._http

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
        if resp.is_success:
            return resp.json()
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        retryable = resp.status_code >= 500 or resp.status_code == 429
        raise RemoteError(str(detail), "remote_error", status=resp.status_code, retryable=retryable)

    # ---- lifecycle -----------------------------------------------------------

    async def aclose(self) -> None:
        for attr in ("_http", "_discovery_http", "_skill_http"):
            client = getattr(self, attr)
            if client is not None:
                await client.aclose()
                setattr(self, attr, None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()
