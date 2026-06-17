"""On-device execution via the bundled Rust core (`askfaro._core`).

The core reports which namespaces it can run via `free_tools()` — that capability
list is the routing signal, not the catalog's pricing flag. A namespace the core
can run executes here with no network call, no API key, and no credit charge.

Local results are passed back through the same `wrap_tool_response` / `build_error`
core builders the backend uses, so the envelope is byte-identical to a remote call.
"""

from __future__ import annotations

import json
from functools import lru_cache

from askfaro.errors import LocalUnavailableError

try:
    from askfaro import _core as faro_core  # native extension bundled in this package
except ImportError:  # pragma: no cover - exercised only if the native build is absent
    faro_core = None


def core_available() -> bool:
    """True if the embedded core is importable in this environment."""
    return faro_core is not None


def core_version() -> str | None:
    return faro_core.__version__ if faro_core is not None else None


@lru_cache(maxsize=1)
def local_namespaces() -> frozenset[str]:
    """Namespaces the embedded core can execute on-device (cached)."""
    if faro_core is None:
        return frozenset()
    return frozenset(faro_core.free_tools())


def can_run_local(namespace: str) -> bool:
    return faro_core is not None and namespace in local_namespaces()


def split_skill_id(skill: str) -> tuple[str, str | None]:
    """Map a catalog skill id to (namespace, operation) for an in-core call.

    Catalog skill ids are either a bare namespace (`astronomy`) or
    `namespace.operation` (`calc.evaluate`). The NAMESPACE is the routing key for
    on-device execution; the operation, when present, is what the core's free tool
    dispatches on (a bare namespace lets the tool pick its default operation).

        split_skill_id("astronomy")      # ("astronomy", None)
        split_skill_id("calc.evaluate")  # ("calc", "evaluate")
    """
    sep = "/" if "/" in skill else ("." if "." in skill else None)
    if sep is None:
        return skill, None
    namespace, operation = skill.split(sep, 1)
    return namespace, (operation or None)


def run_local(namespace: str, operation: str | None, arguments: dict | None) -> dict:
    """Execute a free tool in the embedded core and return the canonical envelope.

    `operation`, when given, becomes the core's `operation` and the free tool
    dispatches on it; when None, the intent is passed through as-is and the tool
    selects its own default operation (e.g. astronomy -> `sun`).

    Raises LocalUnavailableError if the core is missing or can't run the namespace.
    """
    if faro_core is None:
        raise LocalUnavailableError(
            "The embedded Faro core (askfaro._core) is not installed. "
            "Reinstall the askfaro package; its bundled core wheel is missing for this platform."
        )
    if namespace not in local_namespaces():
        raise LocalUnavailableError(
            f"Namespace {namespace!r} cannot run on-device "
            f"(the core runs: {', '.join(sorted(local_namespaces()))})."
        )

    intent = dict(arguments or {})
    if operation is not None:
        intent["operation"] = operation
    raw = json.loads(faro_core.execute_free_tool(namespace, json.dumps(intent)))

    skill = f"{namespace}.{operation}" if operation is not None else namespace
    # Free tools charge nothing; stamp it so meta matches a remote free-tool call.
    meta_json = json.dumps({"credits_charged": 0})

    if raw.get("status") == "success":
        body = raw.get("result") or {}
        data = body.get("data")
        summary = body.get("summary")
        return json.loads(
            faro_core.wrap_tool_response(skill, json.dumps(data), summary, meta_json, None, None)
        )

    err = raw.get("error") or {}
    return json.loads(
        faro_core.build_error(
            skill,
            err.get("code", "error"),
            err.get("message", "tool failed"),
            bool(err.get("retryable", False)),
            meta_json,
            None,
            None,
        )
    )
