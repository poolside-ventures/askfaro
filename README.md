# askfaro

[![PyPI](https://img.shields.io/pypi/v/askfaro)](https://pypi.org/project/askfaro/)
[![CI](https://github.com/poolside-ventures/askfaro/actions/workflows/ci.yml/badge.svg)](https://github.com/poolside-ventures/askfaro/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

The Faro Python SDK. **One call — `run(capability, intent)` — runs any
capability.** Where it runs is a transparent optimization you never choose: if the
bundled Rust core can run it on-device it does (free, instant, no key, no network,
even offline); otherwise it goes to Faro's hosted skill agent, which picks the
tools, enforces your budget, and bills your account. Both paths return the
identical canonical envelope, so your result-handling code is the same whether a
capability ran on your machine or in the cloud.

```bash
pip install askfaro
```

```python
from askfaro import Faro

faro = Faro()                                    # no key needed for on-device runs
r = faro.run("astronomy", {"latitude": 48.85, "longitude": 2.35})
assert r.ok and r.local                          # the core ran it on-device — $0

# A capability the core can't run goes to the skill agent automatically — same
# call, same result shape. The agent picks the tools, enforces your budget, and
# bills your account, so this path needs an API key.
faro = Faro(api_key="faro_...")
r = faro.run("image", {"prompt": "a red bicycle"})
if r.ok:
    print(r.data, r.credits_charged)
else:
    print("failed:", r.error)            # a failed run is a result, not an exception
```

The Rust core is compiled into this package (`askfaro._core`), so a single
`pip install askfaro` is all you need — there is no separate core package to
install.

## Transparent routing

`run()` is the single entry point. **You never pick on-device vs. server** — the
SDK routes for you:

- if the bundled core can run the capability (`calc`, `units`, `phone`,
  `astronomy`, …) it runs **in-core**: no key, no network, no credits, even
  offline;
- otherwise `run()` POSTs to Faro's hosted skill agent (`skill.askfaro.com`),
  which selects the operations, calls the underlying tools, enforces your budget,
  and bills your account — so that path needs an API key.

What runs on-device is the bundled core's capability list
(`Faro.local_namespaces()`), not a pricing flag; it grows as more tools are ported
into the core, and capabilities silently get cheaper/faster with no code change on
your side.

```python
faro.run("astronomy", {"latitude": 48.85, "longitude": 2.35})  # on-device, $0
faro.run("image", {"prompt": "a red bicycle"})                 # skill agent, billed
```

**Advanced — `invoke("namespace/tool")`** is an escape hatch that *forces*
on-device execution of a specific core tool and raises if it can't run there. Most
callers should just use `run()`; reach for `invoke()` only when a call must stay
local (e.g. a hard no-network guarantee).

**Tiers.** Every capability runs at one of two tiers: `local` (the bundled core
runs it deterministically on-device — a guarantee) or `remote` (the hosted skill
agent exercises judgment and bills you). `faro.tier_of("image")` tells you which
*without running it*, and `faro.run(..., require_tier="local")` refuses to fall
through to the billed path — routing is never silently degraded across tiers.

## Results & errors

`run()` (and `invoke()`) returns an `InvokeResult` (the canonical envelope). Read
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

**Safe retries.** Pass `idempotency_key` on any `run()` you might retry. A repeat of
the same key replays the prior **successful** result instead of running — and
charging — again; a failed run releases the key so a retry actually re-runs. Scope a
fresh key per distinct logical call.

```python
faro.run("image", "a red bicycle", idempotency_key="order-42")   # retry-safe
```

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
manifest = faro.browse(budget="4k")               # raw manifest dict (drive with navigator())
text = faro.browse(budget="4k", format="text")    # inject-ready markdown catalog
```

`search()` is hybrid lexical + semantic over the public catalog; `browse()`
returns the [progressive-context](https://github.com/poolside-ventures/askfaro-progressive-context)
manifest. Both work with no account. `run()` on a paid skill needs a key and credits.

### Narrow before you scan: facets and see-also links

The catalog map carries two navigation aids beyond the tree, and reaching for them
first is cheaper than scanning descriptors:

- **Facets** — orthogonal tags (`category`, `output`, …) you can filter on *before*
  reading anything. `browse(format="text")` leads with a compact **facet legend** of
  what's filterable, and a `NavSession` filters by them locally:

  ```python
  nav = faro.navigator(budget="4k")
  finance = nav.filter(category="Finance & Markets")   # node ids matching every facet
  ```

- **See-also cross-links** — when a node is *close but not exactly* what you want,
  follow its lateral links to related nodes in other branches instead of restarting
  the search. Each carries a `why` phrase explaining the relation:

  ```python
  for entry in nav.related("skill-image"):             # e.g. image → video
      print(entry.node_id, entry.meta.get("link_why"))
  ```

  Cross-links stay **on-demand** (they're per-node and only matter once you've opened
  something), so `browse(format="text")` does not inline them — call `related()` when
  you land close. The facet legend, being small and useful up front, is inlined.

`browse()` and `navigator()` **cache the manifest on disk and revalidate by ETag**
(the catalog changes only on a rebuild), so repeat calls cost a cheap `304`, not a
full re-download — and a rebuilt catalog is always picked up. The cache lives under
`~/.cache/askfaro/pcx` (shared with the `askfaro` CLI) and is keyed by API host +
budget. Control it per client:

```python
Faro()                                  # default: on-disk cache
Faro(manifest_cache=False)              # in-memory only, no disk writes
Faro(manifest_cache="/tmp/my-cache")   # a directory of your choosing
```

This uses progressive-context's `ManifestLoader` / `AsyncManifestLoader`, so the
async `AsyncFaro` revalidates the same way.

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
