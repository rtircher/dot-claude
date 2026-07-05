---
description: Vendor the canonical cloud-parity seed from dot-claude into the current repo (or --check for drift)
allowed-tools: Bash(bash:*), Bash(git rev-parse:*), Bash(jq:*), Read, Edit
---

Run the cloud-parity scaffold to make this repo cloud-session-ready, or to check a
repo's vendored seed for drift. The scaffold is a standalone script so it never
depends on a plugin having loaded.

## Vendor / refresh the seed into this repo

```sh
bash "${CLAUDE_PLUGIN_ROOT}/scaffold/init-cloud-parity.sh"
```

This copies the generic seed into `.claude/cloud/` (`cloud-setup.sh`, `session-start.sh`,
`ensure-plugins.sh`, `cloud-plugin-doctor.sh`, each provenance-stamped), writes a starter
`.claude/cloud/cloud-parity-recipes` if absent, and merges `.claude/settings.json` (adding
`extraKnownMarketplaces["dot-claude"]` and a SessionStart hook entry if absent). It never
edits `enabledPlugins`, `permissions`, or other hooks.

A repo vendored under the older layout (`scripts/*`, `.claude/cloud-setup.sh`) is migrated
automatically on the next vendor: authored files (`cloud-parity-recipes`, `cloud-setup-local.sh`)
move into `.claude/cloud/`, the old seed copies are removed and re-vendored there, and a stale
SessionStart hook entry is rewritten to `.claude/cloud/session-start.sh`. `--check` reports any
leftover as `[LEGACY]`. Repos also relocate their `ensure-<tool>.sh` by hand (see step 3).

After running, with the user:
1. Edit `.claude/cloud/cloud-parity-recipes` to list this repo's plugins (`marketplace-add` /
   `install` lines). A repo that needs no cloud plugins can delete the file.
2. Add matching `enabledPlugins` entries to `.claude/settings.json` (the scaffold
   deliberately does not touch this). Run `--check` to confirm recipes and
   `enabledPlugins` agree.
3. If the repo has a toolchain, add `.claude/cloud/ensure-<tool>.sh` (a userspace
   toolchain installer), wired as a Makefile prerequisite. That runs in-session as the
   non-root session user, so it only covers userspace.
4. If setup needs ROOT at container-build time (apt system packages, a native build
   toolchain, frozen installs), add an OPTIONAL `.claude/cloud/cloud-setup-local.sh`. The
   generic `cloud-setup.sh` calls it (by path, at `$PWD`) after its apt-fix and
   marketplace pre-warm; a repo that needs nothing ships none. This keeps the
   vendored `cloud-setup.sh` byte-identical (so `--check` stays clean) while the
   repo-specific root work lives in a repo-authored file the scaffold never touches
   (`cloud-setup-local.sh` is a reserved repo-only name: it is never a `SEED_FILES`
   destination, so vendoring never stamps or overwrites it and `--check` never flags
   it). Failures there are NOT swallowed: a real install error fails setup loudly
   rather than caching a broken image, so mark a genuinely best-effort step (e.g.
   Chrome) with `|| echo WARN` inside the hook itself.
5. Paste `.claude/cloud/cloud-setup.sh` into the cloud environment's Setup script field.
6. Set all four of `GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL` and `GIT_COMMITTER_NAME`/
   `GIT_COMMITTER_EMAIL` in the cloud environment's env vars, so commits are
   authored as the human, never the harness. Git honors them natively (author
   vars alone leave the committer field as the harness); the vendored
   SessionStart hook only warns in the repo pulse when the vars are missing.
   Remind the user of this step whenever the seed is vendored or re-synced.

**Trust boundary:** `.claude/cloud/cloud-parity-recipes` drives `claude plugin marketplace add`
/ `install` of whatever it names, on every cold session, detached. Treat it like any
committed code: review changes to it in PR, and only add marketplaces you trust
(dot-claude itself is pinned to live HEAD, an accepted exposure).

## Check for drift (local gate)

```sh
bash "${CLAUDE_PLUGIN_ROOT}/scaffold/init-cloud-parity.sh" --check
```

Non-zero exit means a vendored file differs from the current canonical seed (edited
locally, or the seed moved upstream). Re-run the vendor command to re-sync, then
review the diff. The check is network-free and compares against this dot-claude
checkout's live seed, so it requires the `dev` plugin / a dot-claude checkout present.
It also warns when `enabledPlugins` names a plugin with no matching recipe.
