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
        return self.envelope.get("error")
