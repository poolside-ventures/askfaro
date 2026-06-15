from __future__ import annotations


class FaroError(Exception):
    """Base error for the Faro SDK."""

    def __init__(self, message: str, code: str = "error", *, retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


class LocalUnavailableError(FaroError):
    """Raised when local execution was required but the embedded core cannot run
    the requested namespace (or the core is not installed)."""

    def __init__(self, message: str):
        super().__init__(message, "local_unavailable", retryable=False)


class RemoteError(FaroError):
    """Raised when the backend returns an error response."""

    def __init__(self, message: str, code: str = "remote_error", *, status: int | None = None, retryable: bool = False):
        super().__init__(message, code, retryable=retryable)
        self.status = status


class ToolError(FaroError):
    """Raised when a tool runs but reports a failure envelope (status == failed)."""

    def __init__(self, message: str, code: str = "tool_error", *, retryable: bool = False, envelope: dict | None = None):
        super().__init__(message, code, retryable=retryable)
        self.envelope = envelope
