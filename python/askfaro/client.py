from __future__ import annotations

import os
from typing import Optional

from askfaro._capabilities import Capabilities, resolve_capabilities
from askfaro.errors import FaroError, RemoteError
from askfaro.local import (
    can_run_local,
    core_available,
    core_version,
    local_namespaces,
    run_local,
    split_skill_id,
)
from askfaro.result import InvokeResult, SearchHit

DEFAULT_BASE_URL = "https://api.askfaro.com"
# Execution tiers: a capability runs either on-device in the core (a deterministic
# guarantee) or on the hosted skill agent (judgment + billed). See tier_of().
TIER_LOCAL = "local"
TIER_REMOTE = "remote"
_TIERS = (TIER_LOCAL, TIER_REMOTE)
# Skills run on Faro's hosted skill agent (intent in, envelope out), not the core
# API. It is Faro infrastructure, not self-hostable, so this is fixed.
SKILL_AGENT_URL = "https://skill.askfaro.com"


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
    """Faro client.

    `run(capability, intent)` is the single entry point for executing a
    capability. Where it runs is a transparent optimization you never choose: if
    the bundled core can run it on-device (calc, units, astronomy, ...) it does —
    free, instant, no key, no network — otherwise it goes to Faro's hosted skill
    agent, which selects the underlying tools and bills your account. Either way
    you get the same canonical `InvokeResult`.

    `invoke(tool)` is an advanced escape hatch that *forces* on-device execution
    of a specific core tool; most callers should just use `run()`.
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
        # Curate which capabilities this client surfaces and will run. Resolved
        # once: explicit arg > env vars > askfaro.toml. Applied to browse/search/run.
        self._caps = resolve_capabilities(capabilities)
        self._discovery_http = None  # discovery endpoints; no key required
        self._skill_http = None  # skill agent (run); created on first run()
        # browse()/navigator() cache the pcx manifest and revalidate by ETag.
        # True -> on-disk; False -> in-memory only; a path -> that directory.
        self._manifest_cache = manifest_cache
        self._manifest_store = None

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
    # Discover a skill from intent, then run() it. Discovery needs no API key
    # (a key is sent if set).

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        category: str | None = None,
    ) -> list[SearchHit]:
        """Find skills by intent — the "describe what you want, get a suitable
        skill" path. Hybrid lexical + semantic search over the public catalog,
        ranked by relevance. No API key required.

        Each `SearchHit` carries enough to run without a second call: `.id` (hand
        it to `run()`), `.input_schema`, and `.pricing`.

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
        hits = [SearchHit(item) for item in items]
        # Apply the client's capability curation: hide skills it doesn't surface.
        return [h for h in hits if h.kind != "skill" or self._caps.allows(h.id)]

    def describe(self, tool: str) -> dict:
        """Full input schema, long description, and pricing for one tool.
        Wraps `GET /tools/{namespace}/{tool}`. No API key required."""
        namespace, name = _split(tool)
        return self._get(f"/tools/{namespace}/{name}")

    def browse(
        self,
        budget: str | int = "4k",
        *,
        format: str = "json",
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> dict:
        """Fetch the progressive-context (pcx) catalog map. No API key required.

        The client's configured capability curation (see `Capabilities`) is applied
        automatically; `include`/`exclude` here override it for this call only.

        Args:
            budget: Token budget. Named tiers: "4k" (default) or "32k". Or pass an
                integer (e.g. 1500) to size the catalog to any context window — the
                on-device use-case wants ~1k-2k.
            format: "json" (default) returns the raw pcx manifest dict for
                programmatic navigation (drive it with `navigator()`). "text"
                returns an inject-ready markdown catalog in {"manifest_text": "..."},
                disclosed to fit `budget` via progressive-context — categories that
                fit list their skills (`skill_id: what`, ready for run(skill_id)),
                the rest are left as openable headers. Budget-bounded by real token
                accounting, not truncation.
            include: Skill ids to restrict to for this call (allowlist override).
            exclude: Skill ids to drop for this call (added to the configured set).
        """
        from askfaro._browse import budget_to_tier, budget_to_tokens, filter_manifest, render_budget_text

        if format not in ("json", "text"):
            raise FaroError(
                f"browse() format must be 'json' or 'text', got {format!r}.",
                "validation_error",
            )

        tier = budget_to_tier(budget)
        manifest = self._cached_manifest(tier)
        caps = self._caps.overlay(include=include, exclude=exclude)

        if format == "json":
            return filter_manifest(manifest, caps)

        return {"manifest_text": render_budget_text(manifest, budget_to_tokens(budget), caps)}

    def navigator(self, budget: str | int = "4k", *, include: list[str] | None = None, exclude: list[str] | None = None):
        """A progressive-context `NavSession` over the catalog, sized to `budget`
        and pre-filtered by your capability config. Drive it locally — `index()`,
        `look(ids)`, `open(id)` — to disclose the catalog one branch at a time
        instead of injecting it whole. Requires `askfaro-progressive-context`.

            nav = faro.navigator(budget=1500)
            print(nav.index())          # the budget-bounded starting view
            nav.open("cat-images")      # reveal that category's skills on demand
        """
        from askfaro._browse import budget_to_tier, budget_to_tokens, filter_manifest
        from askfaro_progressive_context import Manifest, NavSession

        caps = self._caps.overlay(include=include, exclude=exclude)
        manifest = self._cached_manifest(budget_to_tier(budget))
        m = Manifest.from_dict(filter_manifest(manifest, caps))
        return NavSession(m, budget=budget_to_tokens(budget))

    # ---- invocation ----------------------------------------------------------

    def invoke(self, tool: str, arguments: dict | None = None) -> InvokeResult:
        """Advanced: *force* on-device execution of a specific core tool
        `namespace/tool` (e.g. `calc/evaluate`) in the embedded core — no API key,
        no network, no credits. Returns a normalized InvokeResult; tool-level
        failures come back with `.ok == False`.

        Most callers should use `run()`, which routes on-device automatically when
        possible and otherwise to the skill agent. Reach for `invoke()` only when
        you need to guarantee a call stays local (and fail loudly if it can't).
        Only the embedded core's free tools are invocable here.
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
        """Which execution tier `capability` will run at, WITHOUT running it:

        - ``"local"`` — the bundled core runs it deterministically on-device
          (free, offline, no key) — a *guarantee*;
        - ``"remote"`` — it goes to the hosted skill agent, which exercises
          *judgment* (selects tools) and bills your account.

        Lets a caller route or gate on the tier up front (see `run(require_tier=)`)
        instead of discovering it only by what a run happened to cost.
        """
        if not capability or not isinstance(capability, str):
            raise FaroError("tier_of(capability) needs a capability id.", "validation_error")
        namespace, _ = split_skill_id(capability)
        return TIER_LOCAL if can_run_local(namespace) else TIER_REMOTE

    # ---- capability execution -------------------------------------------------
    # run() is the single transparent entry. On-device vs. server is an internal
    # optimization: if the bundled core can run the capability it does (free,
    # instant, offline); otherwise the skill agent selects operations, calls the
    # underlying tools, and bills your account.

    def run(
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

        Routing is transparent and automatic — you never pick on-device vs. server:

          - if the bundled core can run `capability` on-device (see
            `local_namespaces()`) it runs in-core — free, instant, no key, no
            network, even offline;
          - otherwise it POSTs to Faro's hosted skill agent, which selects the
            underlying tools and bills your account (needs an API key).

        Either way you get the same canonical `InvokeResult`. `intent` is a dict the
        capability understands, or a plain string (treated as `{"prompt": ...}`); on
        the on-device path it is the structured intent the core tool expects (e.g.
        astronomy needs `latitude`/`longitude`/`date`). A run that would cross the
        soft `confirm_above` ceiling comes back with `.status == "needs_input"`
        (a quote) rather than spending.

        Pass `idempotency_key` for any run you might retry: a repeat of the same key
        replays the prior successful result instead of running (and charging) again.
        Use a fresh key per distinct logical call. The budget/idempotency kwargs
        (`max_credits`, `confirm_above`, `continuation`, `idempotency_key`) govern
        the server path; on-device runs are free and deterministic, so they are moot
        there and ignored.

        Pass `require_tier="local"` to *guarantee* a run stays on-device (it raises
        rather than fall through to the billed skill agent) — a generalization of
        `invoke()` that keeps the `run()` surface. `require_tier="remote"` requires
        the judgment path. See `tier_of()` to check the tier without running.

            faro.run("astronomy", {"latitude": 48.85, "longitude": 2.35})  # on-device
            faro.run("image", {"prompt": "a red bicycle"})                 # server
            faro.run("image", "a red bicycle")                             # shorthand
            faro.run("image", "a red bicycle", idempotency_key="order-42")
        """
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

        # Transparent on-device routing: if the core can run this capability's
        # namespace, execute in-core — no key, no network, same envelope.
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
                    f"{require_tier!r} was requested. Routing is not degraded across tiers: a "
                    f"'local' guarantee refuses a capability the core can't run, and 'remote' "
                    f"refuses one that would silently run on-device.",
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
            resp = client.post(f"/skills/{capability}/run", json=payload)
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
        return self._json_or_raise(resp)

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

    def _conditional_get(self, path: str, params: dict | None, etag: str | None):
        """A GET that surfaces a 304 (instead of raising) for ETag revalidation.
        Returns (status_code, response_etag, body). Used by the manifest cache."""
        client = self._ensure_discovery_http()
        headers = {"If-None-Match": etag} if etag else {}
        try:
            resp = client.get(path, params=params, headers=headers)
        except Exception as e:
            raise RemoteError(f"Network error calling Faro: {e}", "network_error", retryable=True)
        if resp.status_code == 304:
            return 304, resp.headers.get("ETag") or etag, None
        return resp.status_code, resp.headers.get("ETag"), self._json_or_raise(resp)

    def _cached_manifest(self, tier: str) -> dict:
        """The pcx manifest for `tier`, served from the cache and revalidated by
        ETag (see _pcx_cache). Shared by browse() and navigator()."""
        from askfaro._pcx_cache import load_manifest, make_store

        if self._manifest_store is None:
            self._manifest_store = make_store(self._manifest_cache)
        return load_manifest(self._conditional_get, self._base_url, tier, self._manifest_store)

    # ---- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        for attr in ("_discovery_http", "_skill_http"):
            client = getattr(self, attr)
            if client is not None:
                client.close()
                setattr(self, attr, None)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
