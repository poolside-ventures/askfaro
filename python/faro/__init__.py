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

    # Anything beyond the on-device core is a skill: the skill agent runs the
    # tools and bills you (needs an API key).
    faro = Faro(api_key="faro_...")
    faro.run("image", {"prompt": "a red bicycle"})

Discovery (no key needed): describe what you want and get a suitable skill, or
browse the progressive-context catalog map.

    for hit in Faro().search("generate an image"):
        print(hit.kind, hit.id, hit.short_description)
"""

from faro.client import Faro
from faro.errors import (
    FaroError,
    LocalUnavailableError,
    RemoteError,
    ToolError,
)
from faro.result import InvokeResult, SearchHit

__version__ = "0.2.0"

__all__ = [
    "Faro",
    "InvokeResult",
    "SearchHit",
    "FaroError",
    "LocalUnavailableError",
    "RemoteError",
    "ToolError",
    "__version__",
]
