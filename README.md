# askfaro

[![PyPI](https://img.shields.io/pypi/v/askfaro)](https://pypi.org/project/askfaro/)
[![CI](https://github.com/poolside-ventures/askfaro/actions/workflows/ci.yml/badge.svg)](https://github.com/poolside-ventures/askfaro/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

The Faro Python SDK. **Local-first**: the free tools the bundled Rust core can run
execute on-device with `invoke()` — no API key, no network, no credits. Everything
else is a **skill** you `run()` on Faro's hosted skill agent. Both return the
identical canonical envelope, so your result-handling code is the same whether a
tool ran on your machine or in the cloud.

```bash
pip install askfaro
```

```python
from askfaro import Faro

faro = Faro()                                    # no key needed for on-device tools
r = faro.invoke("calc/evaluate", {"expression": "2 + 2 * 3"})
assert r.ok and r.local and r.data["result"] == 8

# Anything beyond the on-device core is a *skill*: the skill agent picks the
# tools, runs them, enforces your budget, and bills your account.
faro = Faro(api_key="faro_...")
r = faro.run("image", {"prompt": "a red bicycle"})
if r.ok:
    print(r.data, r.credits_charged)
else:
    print("failed:", r.error)            # a failed skill is a result, not an exception
```

The Rust core is compiled into this package (`askfaro._core`), so a single
`pip install askfaro` is all you need — there is no separate core package to
install.

## invoke() vs run()

Two execution methods, split by where the work happens:

- **`invoke("namespace/tool")`** runs an **on-device core tool** (calc, units,
  phone, …) in-process: no key, no network, no credits. Only the bundled core's
  free tools are invocable; raw remote tools are not directly callable (the API
  answers "use the skill layer"), so for anything vendor-backed, use `run()`.
- **`run("skill", intent)`** runs a **skill**: the skill agent selects the
  operations, calls the underlying tools, enforces your budget, and bills your
  account. This is the path for every capability that isn't an on-device tool.
  It needs an API key and runs on Faro's hosted skill agent (`skill.askfaro.com`).

What runs on-device is the bundled core's capability list
(`Faro.local_namespaces()`), not a pricing flag; it grows as more tools are ported
into the core. Calling `invoke()` on a non-core tool raises and points you at
`run()`.

## Results & errors

`invoke()` and `run()` return an `InvokeResult` (the canonical envelope). Read
`.status`, which is one of three outcomes — **a failed call is a result, not an
exception**:

```python
r = faro.run("audio-intelligence", {"url": "https://.../clip.mp3"}, confirm_above=50)

if r.ok:                       # status == "success"
    use(r.data)                # .data, .summary, .meta, .credits_charged
elif r.status == "needs_input":
    # A clarification, or a budget QUOTE that crossed confirm_above. Inspect
    # r.needs_input, then resume the *same* plan with the signed token:
    r = faro.run("audio-intelligence", {...}, continuation=r.continuation)
else:                          # status == "failed"
    print(r.error["code"], r.error["message"])   # auth | insufficient_credits | ...
```

Only **transport/HTTP** problems raise: `FaroError` (bad input, missing key) and
`RemoteError` (network failure, or an HTTP error from the skill agent, with
`.status` and `.retryable`). Everything the skill itself reports — failure,
clarification, budget quote — comes back on the result so you handle all outcomes
in one place. Cost ceilings: `max_credits` is a hard cap (the run aborts rather
than exceed it); `confirm_above` is the soft ceiling that returns the quote above.

## Async

For server-side consumers on an event loop (e.g. an async FastAPI backend),
`AsyncFaro` mirrors `Faro` with awaitable network methods, so you don't wrap calls
in `asyncio.to_thread`:

```python
from askfaro import AsyncFaro

async with AsyncFaro(api_key="faro_...") as faro:
    hits = await faro.search("transcribe an audio file")
    r = await faro.run("image", {"prompt": "a red bicycle"})
    assert r.ok
```

Same constructor and result types as `Faro`. The network methods (`search`,
`describe`, `browse`, `run`) are coroutines; `invoke()` is awaitable too for a
uniform surface, but the on-device core runs in-process (sub-millisecond), so
there is no blocking I/O to offload.

## Discovery

Describe what you want and get a ranked skill to `run()`. Discovery needs no API key.

```python
faro = Faro()

# Describe what you want; get ranked, ready-to-run skills:
for hit in faro.search("transcribe an audio file"):
    print(hit.id, hit.short_description, hit.pricing)

# A hit's .id is exactly what run() takes:
best = faro.search("transcribe an audio file")[0]
faro.run(best.id, {"url": "https://.../clip.mp3"})       # paid -> needs a key

# Full input schema + pricing for one candidate:
faro.describe("audio-intelligence/transcribe")

# Browse instead of search: a progressive-context (pcx) map you expand one branch
# at a time, sized for small / on-device context windows:
manifest = faro.browse(budget="4k")    # navigate via its self-describing `usage` field
```

`search()` is hybrid lexical + semantic over the public catalog; `browse()`
returns the [progressive-context](https://github.com/poolside-ventures/askfaro-progressive-context)
manifest. Both work with no account. `run()` on a paid skill needs a key and credits.

## What's bundled

`askfaro._core` is the MIT open-source free-tool slice of the Faro core (the
`faro-core-free` Rust crate): calc, units, phone, astronomy, encoding, datetime,
timezone, random, and timer, plus the canonical envelope builders. The proprietary
parts of Faro (selection gate, signed continuations, cloud client, billing) are NOT
in this package; vendor-backed tools run server-side via the API.

## Development

This is a [maturin](https://www.maturin.rs) mixed Rust/Python project, fully
self-contained:

- `core-free/` — the `faro-core-free` Rust crate (the free-tool implementations +
  the canonical envelope)
- `src/lib.rs` — the PyO3 binding that builds the `askfaro._core` extension from it
- `python/askfaro/` — the pure-Python SDK (routing, client, result types)
- `examples/quickstart.py` — a runnable tour

```bash
cargo test -p faro-core-free   # Rust tests
uv venv && uv pip install ".[dev]"   # builds askfaro._core via maturin
.venv/bin/pytest               # offline Python tests (mocked, no network)
FARO_API_KEY=faro_... .venv/bin/pytest -m live   # contract tests vs the real API
python examples/quickstart.py
```

Tests come in two layers — offline (mocked) and **live contract** tests that hit
the real endpoints and gate the release. Mocks can't catch contract drift, so see
[TESTING.md](TESTING.md) for the rule: every mocked boundary must be paired with a
live check.

Published wheels are prebuilt (manylinux x86_64/aarch64 + macOS universal2), so
end users install with no Rust toolchain.
