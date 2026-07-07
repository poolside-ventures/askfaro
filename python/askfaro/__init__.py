"""Faro Python SDK.

`run(capability, intent)` is the one way to execute a capability. Where it runs is
a transparent optimization you never choose: if the bundled Rust core can run it
on-device it does (free, instant, no key, no network); otherwise it goes to Faro's
hosted skill agent (needs an API key). Either way you get the identical canonical
envelope, so your result-handling code is the same.

    from askfaro import Faro

    faro = Faro()                                   # no key needed for on-device runs
    r = faro.run("astronomy", {"latitude": 48.85, "longitude": 2.35})
    r.ok        # True
    r.local     # True  (the core ran it on-device — free, no network)

    # Anything the core can't run goes to the skill agent, which runs the tools
    # and bills you (needs an API key) — same call, same result shape.
    faro = Faro(api_key="faro_...")
    faro.run("image", {"prompt": "a red bicycle"})

`invoke("namespace/tool")` is an advanced escape hatch that forces on-device
execution of a specific core tool; reach for it only when a call must stay local.

Discovery (no key needed): describe what you want and get a suitable capability, or
browse the progressive-context catalog map.

    for hit in Faro().search("generate an image"):
        print(hit.kind, hit.id, hit.short_description)

Server-side / async consumers (e.g. an async FastAPI backend) can use `AsyncFaro`,
which mirrors `Faro` with awaitable network methods:

    from askfaro import AsyncFaro

    async with AsyncFaro(api_key="faro_...") as faro:
        r = await faro.run("image", {"prompt": "a red bicycle"})
"""

from askfaro._capabilities import Capabilities
from askfaro.aclient import AsyncFaro
from askfaro.client import Faro
from askfaro.errors import (
    FaroError,
    LocalUnavailableError,
    RemoteError,
    ToolError,
)
from askfaro.result import InvokeResult, SearchHit

__version__ = "0.9.0"

__all__ = [
    "Faro",
    "AsyncFaro",
    "Capabilities",
    "InvokeResult",
    "SearchHit",
    "FaroError",
    "LocalUnavailableError",
    "RemoteError",
    "ToolError",
    "__version__",
]
