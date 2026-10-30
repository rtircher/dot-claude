---
name: toolchain
description: >-
  Pin and install language runtimes and dev tools with mise, from one committed
  `.mise.toml` shared by local dev, CI, and cloud setup. Use when adding,
  upgrading, or pinning a runtime or dev tool; editing `.mise.toml`,
  `package.json` `engines`/`packageManager`, or `.ruby-version`; writing CI
  tool-install steps; or writing a cloud setup script that installs tools.
---

# Toolchain management

- **Default to `mise`** for pinning and installing language runtimes and dev
  tools. Put versions in a committed `.mise.toml` as the single source of
  truth, shared by local dev, CI (`jdx/mise-action`, pinned to a commit SHA),
  and any cloud setup.
- Keep ecosystem-native version fields aligned with `.mise.toml` rather than
  competing with it (`package.json` `engines`/`packageManager`,
  `.ruby-version`): `.mise.toml` *installs* the toolchain; those fields are
  what other tooling *reads*. Don't introduce a second installer once mise owns
  the toolchain.
- **Cloud setup scripts:** install mise from a **pinned GitHub release
  tarball**, never the `curl https://mise.run | sh` one-liner. `mise.run` and
  the mise CDN are not on the Claude Code web Trusted allowlist; `github.com`
  and `nodejs.org` are.
