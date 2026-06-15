"""Faro Python SDK.

Local-first: tools the embedded Rust core can run execute on-device (no API key,
no network, no credits); everything else falls back to the Faro backend. Local and
remote results share the identical canonical envelope.

    from faro import Faro

    faro = Faro()                                   # no key needed for local tools
    r = faro.invoke("calc/evaluate", {"expression": "2 + 2 * 3"})
    r.ok        # True
    r.data      # {"expression": "2 + 2 * 3", "result": 8, ...}
    r.local     # True  (ran on-device)

    faro = Faro(api_key="faro_...")                 # key enables backend fallback
    faro.invoke("weather/current", {"city": "Paris"})   # -> backend
"""

from faro.client import Faro
from faro.errors import (
    FaroError,
    LocalUnavailableError,
    RemoteError,
    ToolError,
)
from faro.result import InvokeResult

__version__ = "0.1.0"

__all__ = [
    "Faro",
    "InvokeResult",
    "FaroError",
    "LocalUnavailableError",
    "RemoteError",
    "ToolError",
    "__version__",
]
