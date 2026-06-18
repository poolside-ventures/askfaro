"""Client-side capability curation for the askfaro SDK.

An integration declares which capabilities it uses ONCE and the SDK applies it
everywhere automatically — `browse()`, `search()`, `run()`. Configure it via, in
descending precedence:

  1. a `Capabilities(...)` passed to the client,
  2. env vars `ASKFARO_INCLUDE` / `ASKFARO_EXCLUDE` (comma-separated ids),
  3. an `askfaro.toml` (or `pyproject.toml` `[tool.askfaro]`) found by walking up
     from the working directory:

        [capabilities]
        exclude = ["web-search", "research", "image"]
        # or, as an allowlist:
        # include = ["image", "weather", "maps"]

This is self-curation applied CLIENT-SIDE: it shapes what the SDK surfaces and
will run, not a server-enforced boundary (the API key still technically reaches
anything). Capability ids are skill ids, e.g. "image", "web-search", "calc.evaluate".
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional


class Capabilities:
    """An include/exclude filter over capability (skill) ids.

    - `include` (allowlist): if set, only these ids are allowed.
    - `exclude` (blocklist): these ids are never allowed.

    Both may be set: `include` bounds the set, `exclude` trims within it.
    """

    __slots__ = ("include", "exclude")

    def __init__(
        self,
        *,
        include: Optional[Iterable[str]] = None,
        exclude: Optional[Iterable[str]] = None,
    ):
        self.include: frozenset[str] | None = frozenset(include) if include is not None else None
        self.exclude: frozenset[str] = frozenset(exclude or ())

    def allows(self, capability_id: str) -> bool:
        if self.include is not None and capability_id not in self.include:
            return False
        return capability_id not in self.exclude

    @property
    def is_empty(self) -> bool:
        """True when nothing is curated, so the filter is a no-op."""
        return self.include is None and not self.exclude

    def overlay(
        self,
        *,
        include: Optional[Iterable[str]] = None,
        exclude: Optional[Iterable[str]] = None,
    ) -> "Capabilities":
        """Per-call override layered on top of this filter. A per-call `include`
        replaces the configured allowlist; a per-call `exclude` unions with the
        configured blocklist."""
        if include is None and exclude is None:
            return self
        new_include = self.include if include is None else frozenset(include)
        new_exclude = self.exclude | (frozenset(exclude) if exclude else frozenset())
        return Capabilities(include=new_include, exclude=new_exclude)

    def __repr__(self) -> str:
        inc = set(self.include) if self.include is not None else None
        return f"Capabilities(include={inc}, exclude={set(self.exclude)})"


def _split_env(val: Optional[str]) -> list[str]:
    return [s.strip() for s in (val or "").split(",") if s.strip()]


def _load_toml(path: Path) -> dict:
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # backport for 3.9 / 3.10
        except ModuleNotFoundError:
            return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, ValueError):
        return {}


def _from_mapping(data: dict) -> Capabilities:
    inc = data.get("include")
    exc = data.get("exclude")
    return Capabilities(
        include=list(inc) if isinstance(inc, (list, tuple)) else None,
        exclude=list(exc) if isinstance(exc, (list, tuple)) else None,
    )


def _from_file(start: Path) -> Optional[Capabilities]:
    """Walk up from `start` for an askfaro.toml or pyproject.toml [tool.askfaro]."""
    for d in [start, *start.parents]:
        af = d / "askfaro.toml"
        if af.is_file():
            return _from_mapping(_load_toml(af).get("capabilities", {}))
        pp = d / "pyproject.toml"
        if pp.is_file():
            tool = _load_toml(pp).get("tool", {}).get("askfaro", {})
            if tool:
                return _from_mapping(tool.get("capabilities", tool))
    return None


def resolve_capabilities(explicit: Optional[Capabilities]) -> Capabilities:
    """Resolve the active filter: constructor arg > env vars > config file > none."""
    if explicit is not None:
        return explicit
    inc = _split_env(os.environ.get("ASKFARO_INCLUDE"))
    exc = _split_env(os.environ.get("ASKFARO_EXCLUDE"))
    if inc or exc:
        return Capabilities(include=inc or None, exclude=exc or None)
    from_file = _from_file(Path.cwd())
    if from_file is not None:
        return from_file
    return Capabilities()
