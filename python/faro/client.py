from __future__ import annotations

import os
from typing import Optional

from faro.errors import FaroError, RemoteError
from faro.local import (
    can_run_local,
    core_available,
    core_version,
    local_namespaces,
    run_local,
)
from faro.result import InvokeResult, SearchHit

DEFAULT_BASE_URL = "https://api.askfaro.com"
# Skills run on Faro's hosted skill agent (intent in, envelope out), not the core
# API. It is Faro infrastructure, not self-hostable, so this is fixed.
SKILL_AGENT_URL = "https://skill.askfaro.com"
_MODES = ("auto", "local", "remote")


def _split(tool: str) -> tuple[str, str]:
    sep = "/" if "/" in tool else ("." if "." in tool else None)
    if sep is None:
        raise FaroError(
            f"Invalid tool identifier {tool!r}. Use 'namespace/tool' (e.g. 'calc/evaluate').",
            "validation_error",
        )
    ns, name = tool.split(sep, 1)
    if not ns or not name:
        raise FaroError(f"Invalid tool identifier {tool!r}.", "validation_error")
    return ns, name


class Faro:
    """Faro client with local-first routing.

    Tools the embedded core can run (see `local_namespaces()`) execute on-device:
    no API key, no network, no credits. Everything else goes to the backend.

    mode:
      - "auto"   (default) run on-device when possible, else call the backend
      - "local"  on-device only; raise if the core can't run the namespace
      - "remote" always call the backend
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
        self._http = None  # lazily created only if a remote (authed) call happens
        self._discovery_http = None  # discovery endpoints; no key required
        self._skill_http = None  # skill agent (run); created on first run()

    # ---- capability introspection -------------------------------------------

    @staticmethod
    def local_namespaces() -> frozenset[str]:
        """Namespaces that can run on-device in this environment."""
        return local_namespaces()

    @staticmethod
    def core_available() -> bool:
        return core_available()

    @staticmethod
    def core_version() -> str | None:
        return core_version()

    # ---- discovery -----------------------------------------------------------
    # The two ways to reach a capability: invoke one you already know (below), or
    # discover one from intent. Discovery needs no API key (a key is sent if set).

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        category: str | None = None,
    ) -> list[SearchHit]:
        """Find skills/tools by intent — the "describe what you want, get a
        suitable skill" path. Hybrid lexical + semantic search over the public
        catalog, ranked by relevance. No API key required.

        Each `SearchHit` carries enough to invoke without a second call: `.id`
        (hand it to `invoke()`), `.input_schema`, and `.pricing`.

            for hit in faro.search("transcribe an audio file"):
                print(hit.id, hit.short_description, hit.pricing)
        """
        if not query or not query.strip():
            raise FaroError("search(query) needs a non-empty query.", "validation_error")
        params: dict = {"q": query, "limit": limit}
        if category:
            params["category"] = category
        envelope = self._get("/tools/search", params)
        items = envelope.get("items", []) if isinstance(envelope, dict) else []
        return [SearchHit(item) for item in items]

    def describe(self, tool: str) -> dict:
        """Full input schema, long description, and pricing for one tool.
        Wraps `GET /tools/{namespace}/{tool}`. No API key required."""
        namespace, name = _split(tool)
        return self._get(f"/tools/{namespace}/{name}")

    def browse(self, *, budget: str = "4k") -> dict:
        """Fetch the progressive-context (pcx) catalog map: a navigable,
        budget-aware index you expand one branch at a time — ideal for small /
        on-device context windows. No API key required.

        Returns the manifest as a dict; it self-describes its navigation protocol
        in its top-level `usage` field, and `faro-progressive-context`'s
        `Runtime` / `NavSession` can drive it directly. `budget` is "4k" (tight /
        on-device) or "32k" (more headroom).
        """
        return self._get("/pcx/manifest", {"budget": budget})

    # ---- invocation ----------------------------------------------------------

    def invoke(self, tool: str, arguments: dict | None = None, *, mode: str | None = None) -> InvokeResult:
        """Invoke `namespace/tool`, returning a normalized InvokeResult.

        Tool-level failures come back as a result with `.ok == False` (same on both
        paths). Auth / network / config problems raise FaroError.
        """
        eff_mode = mode or self.mode
        if eff_mode not in _MODES:
            raise FaroError(f"mode must be one of {_MODES}, got {eff_mode!r}.", "validation_error")

        namespace, name = _split(tool)

        if eff_mode == "remote":
            return self._invoke_remote(namespace, name, arguments)
        if eff_mode == "local":
            return InvokeResult(run_local(namespace, name, arguments), local=True)
        # auto
        if can_run_local(namespace):
            return InvokeResult(run_local(namespace, name, arguments), local=True)
        return self._invoke_remote(namespace, name, arguments)

    # ---- skills --------------------------------------------------------------
    # `invoke()` calls a single tool. For anything that isn't an on-device core
    # tool, the path is a SKILL: the skill agent selects operations, calls the
    # underlying tools, and bills your account. Raw remote tools are not directly
    # invocable (the API returns "use the skill layer").

    def run(
        self,
        skill: str,
        intent: dict | str,
        *,
        max_credits: float | None = None,
        confirm_above: float | None = None,
        continuation: str | None = None,
    ) -> InvokeResult:
        """Run a skill end-to-end: intent in, normalized envelope out.

        `intent` is a dict the skill understands, or a plain string (treated as
        `{"prompt": ...}`). Returns an InvokeResult; a run that would cross the
        soft `confirm_above` ceiling comes back with `.status == "needs_input"`
        (a quote) rather than spending. Requires an API key.

            faro.run("image", {"prompt": "a red bicycle"})
            faro.run("image", "a red bicycle")            # shorthand
        """
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
            resp = client.post(f"/skills/{skill}/run", json=payload)
        except Exception as e:  # httpx network/timeout errors
            raise RemoteError(
                f"Network error calling the Faro skill agent: {e}", "network_error", retryable=True
            )
        if resp.is_success:
            return InvokeResult(resp.json(), local=False)
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        retryable = resp.status_code >= 500 or resp.status_code == 429
        raise RemoteError(str(detail), "remote_error", status=resp.status_code, retryable=retryable)

    def _invoke_remote(self, namespace: str, name: str, arguments: dict | None) -> InvokeResult:
        client = self._ensure_http()
        try:
            resp = client.post(f"/invoke/{namespace}/{name}", json={"arguments": arguments or {}})
        except Exception as e:  # httpx network/timeout errors
            raise RemoteError(f"Network error calling Faro: {e}", "network_error", retryable=True)

        if resp.is_success:
            return InvokeResult(resp.json(), local=False)

        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        retryable = resp.status_code >= 500 or resp.status_code == 429
        raise RemoteError(str(detail), "remote_error", status=resp.status_code, retryable=retryable)

    def _ensure_http(self):
        if self._http is None:
            import httpx

            if not self._api_key:
                raise FaroError(
                    "An API key is required for backend calls. Pass api_key=... or set FARO_API_KEY. "
                    "(Tools the core runs on-device need no key.)",
                    "auth_required",
                )
            self._http = httpx.Client(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        return self._http

    def _ensure_discovery_http(self):
        """A client for the public discovery endpoints — no key required (the
        bearer is attached only if one is set)."""
        if self._discovery_http is None:
            import httpx

            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._discovery_http = httpx.Client(
                base_url=self._base_url, headers=headers, timeout=self._timeout
            )
        return self._discovery_http

    def _ensure_skill_http(self):
        if self._skill_http is None:
            import httpx

            self._skill_http = httpx.Client(
                base_url=SKILL_AGENT_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        return self._skill_http

    def _get(self, path: str, params: dict | None = None):
        client = self._ensure_discovery_http()
        try:
            resp = client.get(path, params=params)
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

    def close(self) -> None:
        for attr in ("_http", "_discovery_http", "_skill_http"):
            client = getattr(self, attr)
            if client is not None:
                client.close()
                setattr(self, attr, None)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
