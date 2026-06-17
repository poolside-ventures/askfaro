from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InvokeResult:
    """The outcome of an invocation, normalized to Faro's canonical envelope.

    The envelope is built by the SAME Rust core builders the backend uses, so a
    result produced on-device is shape-identical to one produced by the API. Code
    that reads `.data` / `.summary` / `.meta` works the same regardless of path.
    """

    envelope: dict
    local: bool

    @property
    def ok(self) -> bool:
        return self.envelope.get("status") == "success"

    @property
    def status(self) -> str:
        return self.envelope.get("status", "")

    @property
    def result(self) -> dict:
        return self.envelope.get("result") or {}

    @property
    def data(self):
        """The tool's information payload (None on failure)."""
        return self.result.get("data")

    @property
    def summary(self):
        return self.result.get("summary")

    @property
    def meta(self) -> dict:
        return self.envelope.get("meta") or {}

    @property
    def error(self) -> dict | None:
        """The error block when `status == "failed"`: `{code, message, retryable}`.
        Tool/skill failures are reported HERE (`.ok is False`), not raised."""
        return self.envelope.get("error")

    @property
    def needs_input(self) -> dict | None:
        """Present when `status == "needs_input"`: a clarification, or a budget
        quote that crossed `confirm_above`. `{question, missing}`. Pair it with
        `.continuation` to resume."""
        return self.envelope.get("needs_input")

    @property
    def continuation(self) -> str | None:
        """A signed token to resume a quote (`needs_input`) or paginate. Hand it
        back to `run(..., continuation=token)`."""
        return self.envelope.get("continuation")

    @property
    def credits_charged(self):
        """What this call cost you (0 for on-device / free)."""
        return self.meta.get("credits_charged")


@dataclass(frozen=True, repr=False)
class SearchHit:
    """One result from `Faro.search()`: a skill matched to a query.

    Hits are ranked by relevance and carry enough to run without a second
    round-trip: `id` (what you hand to `run()`), `input_schema`, and
    `pricing`. The full backend payload is on `.raw`.
    """

    raw: dict

    @property
    def kind(self) -> str:
        """'skill' or 'tool'."""
        return self.raw.get("object_type", "tool")

    @property
    def name(self) -> str | None:
        return self.raw.get("name")

    @property
    def namespace(self) -> str | None:
        return self.raw.get("namespace")

    @property
    def id(self) -> str | None:
        """The identifier to hand to `run()` (the skill id)."""
        if self.kind == "skill":
            return self.raw.get("skill_id") or self.raw.get("id")
        ns, name = self.raw.get("namespace"), self.raw.get("name")
        return f"{ns}/{name}" if ns and name else name

    @property
    def short_description(self) -> str | None:
        return self.raw.get("short_description")

    @property
    def pricing(self):
        return self.raw.get("pricing")

    @property
    def input_schema(self):
        return self.raw.get("input_schema")

    def __repr__(self) -> str:
        return f"SearchHit(kind={self.kind!r}, id={self.id!r}, {self.short_description!r})"
