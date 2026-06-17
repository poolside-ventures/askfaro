<!--
  This file is part of the `core-free` crate and is mirrored verbatim into the
  public askfaro repo, where it doubles as the "do not edit here" banner. Keep it
  source-stable (no timestamps / commit hashes) so the mirror stays a pure
  function of the crate contents.
-->

# `core-free` is the public, mirrored crate

This directory (`faro-core/core-free`) is the **single source of truth** for the
open-source (MIT) Faro free-tool core. It is mirrored, verbatim, into the public
package repo:

- Monorepo (edit here): `poolside-ventures/faro` → `faro-core/core-free`
- Public mirror (generated, do **not** hand-edit): `poolside-ventures/askfaro` → `core-free`

The public [`askfaro`](https://pypi.org/project/askfaro/) PyPI package bundles this
crate (`faro._core`) via maturin. Everything outside `core-free/` in the public
repo (the PyO3 binding, the Python SDK, README, examples, CI) is authored in that
repo; **`core-free/` is generated from this monorepo and must never be edited in
the public repo** — changes there are overwritten on the next sync.

## How the sync works

`scripts/sync_public_sdk.sh` copies this directory into a checkout of the public
repo (`rsync --delete`, excluding `target/`). The `core-free/Cargo.toml` uses
workspace inheritance (`version.workspace`, `edition.workspace`,
`repository.workspace`), so it resolves correctly in either workspace and can be
copied byte-for-byte.

- **Auto-push:** `.github/workflows/sdk-sync.yml` runs the script on every push to
  `main` that touches `faro-core/core-free/**`, then commits + pushes the result to
  the public repo's `main`. The public repo is a true generated mirror.
- **Drift guard:** the same workflow runs a daily/`workflow_dispatch` check that
  fails loudly if the public mirror has diverged from this crate (e.g. an
  out-of-band hand-edit, or a sync that never landed).
- **Release to PyPI** stays a deliberate act in the public repo: bump its
  `[workspace.package] version` and push a `v*` tag, which triggers its existing
  `release.yml`. Content currency (this mirror) is automatic; cutting a release is
  intentional.
