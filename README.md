# askfaro

[![PyPI](https://img.shields.io/pypi/v/askfaro)](https://pypi.org/project/askfaro/)
[![CI](https://github.com/poolside-ventures/askfaro/actions/workflows/ci.yml/badge.svg)](https://github.com/poolside-ventures/askfaro/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

The Faro Python SDK. **Local-first**: tools the bundled Rust core can run execute
on-device — no API key, no network, no credits. Everything else falls back to the
Faro backend. Local and remote results share the identical canonical envelope, so
the same code path works whether a tool ran on your machine or in the cloud.

```bash
pip install askfaro
```

```python
from faro import Faro

faro = Faro()                                    # no key needed for on-device tools
r = faro.invoke("calc/evaluate", {"expression": "2 + 2 * 3"})
assert r.ok and r.local and r.data["result"] == 8

faro = Faro(api_key="faro_...")                  # a key enables backend fallback
faro.invoke("weather/current", {"city": "Paris"})    # -> backend (vendor-backed)
```

The Rust core is compiled into this package (`faro._core`), so a single
`pip install askfaro` is all you need — there is no separate core package to
install.

## Routing

`Faro(mode=...)` (per-call override on `invoke(..., mode=...)`):

| mode | behavior |
|------|----------|
| `auto` (default) | run on-device when the core can; otherwise call the backend |
| `local` | on-device only; raise `LocalUnavailableError` if the core can't run it |
| `remote` | always call the backend |

What can run on-device is the bundled core's own capability list
(`Faro.local_namespaces()`), not a pricing flag — it grows as more tools are
ported into the core. A vendor-backed tool (weather, web search, …) physically
needs the backend and always routes remote.

## Discovery

Two ways to reach a capability: invoke one you already know, or find one from
intent. Discovery needs no API key.

```python
faro = Faro()

# Describe what you want; get ranked, ready-to-invoke skills/tools:
for hit in faro.search("transcribe an audio file"):
    print(hit.id, hit.short_description, hit.pricing)

# Each hit's .id is exactly what invoke() takes:
best = faro.search("transcribe an audio file")[0]
# faro.invoke(best.id, {"url": "https://.../clip.mp3"}, mode="remote")   # paid -> needs a key

# Full input schema + pricing for one candidate:
faro.describe("audio-intelligence/transcribe")

# Browse instead of search: a progressive-context (pcx) map you expand one branch
# at a time, sized for small / on-device context windows:
manifest = faro.browse(budget="4k")    # navigate via its self-describing `usage` field
```

`search()` is hybrid lexical + semantic over the public catalog; `browse()`
returns the [progressive-context](https://github.com/poolside-ventures/faro-progressive-context)
manifest. Both work with no account. `invoke()` on a paid tool still needs a key
and credits.

## What's bundled

`faro._core` is the MIT open-source free-tool slice of the Faro core (the
`faro-core-free` Rust crate): calc, units, phone, astronomy, encoding, datetime,
timezone, random, and timer, plus the canonical envelope builders. The proprietary
parts of Faro (selection gate, signed continuations, cloud client, billing) are NOT
in this package; vendor-backed tools run server-side via the API.

## Development

This is a [maturin](https://www.maturin.rs) mixed Rust/Python project, fully
self-contained:

- `core-free/` — the `faro-core-free` Rust crate (the free-tool implementations +
  the canonical envelope)
- `src/lib.rs` — the PyO3 binding that builds the `faro._core` extension from it
- `python/faro/` — the pure-Python SDK (routing, client, result types)
- `examples/quickstart.py` — a runnable tour

```bash
cargo test -p faro-core-free   # Rust tests
uv venv && uv pip install ".[dev]"   # builds faro._core via maturin
.venv/bin/pytest               # Python tests, no network
python examples/quickstart.py
```

Published wheels are prebuilt (manylinux x86_64/aarch64 + macOS universal2), so
end users install with no Rust toolchain.
