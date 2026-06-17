# Testing

Two layers. The second is non-negotiable for anything that crosses a Faro service
boundary.

## Offline tests (default)

`pytest` runs the offline suite (`-m 'not live'`): unit + routing tests with the
network mocked via `respx`. Fast, deterministic, no key.

**These cannot catch contract drift.** A mock encodes what the API did *when the
test was written* and keeps passing after the real contract changes. The SDK's
remote `invoke()` "passed" against a mock that returned `200` for weeks while the
live endpoint had started returning `403` ("use the skill layer"). The mock was the
bug.

## Live contract tests (`-m live`)

`tests/test_live.py` hits the REAL endpoints the SDK uses — discovery, the hosted
skill agent, the bundled core — so a contract change FAILS here instead of
shipping. They run in CI on every push and **gate the release** (`release.yml`,
before any wheel is published). The authed `run()` check needs a `FARO_API_KEY`
repo secret; the probe is an unknown skill, so it never bills. Without the secret
the no-key discovery + bundled-core checks still gate.

```bash
.venv/bin/pytest                          # offline (mocked)
FARO_API_KEY=faro_... .venv/bin/pytest -m live   # against the real API
```

## The rule

> Every mocked-boundary test must be paired with a live test that proves the mock
> still matches reality.

If you mock a Faro endpoint, add or extend a `@pytest.mark.live` test that calls the
real one. A green mock is only trustworthy next to a green live check.
