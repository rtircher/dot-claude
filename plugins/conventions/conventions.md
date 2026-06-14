# Working conventions

Cross-cutting working-style conventions, injected into every session (local and
cloud) by the `conventions` plugin's SessionStart hook. This file is the single
source of truth — edit here, and every project that enables the plugin picks it
up on its next session. Project-specific facts belong in that repo's `AGENTS.md`,
not here.

## Model selection

- Refer to models by **unversioned alias** — `opus`, `sonnet`, `haiku` — never a
  version-pinned id. The alias always resolves to the latest release of that tier,
  so nothing needs editing when a new version ships.
- **Pick the model per task.** Assess each subagent task's difficulty before
  dispatch rather than defaulting one tier across a whole plan. Subtle reasoning
  (feasibility, security, cross-cutting review) warrants a stronger tier than
  mechanical work.

## Toolchain management

- **Default to `mise`** for pinning and installing language runtimes and dev tools.
  Put versions in a committed `.mise.toml` as the single source of truth, shared by
  local dev, CI (`jdx/mise-action`, pinned to a commit SHA), and any cloud setup.
- Keep ecosystem-native version fields aligned with `.mise.toml` rather than
  competing with it (`package.json` `engines`/`packageManager`, `.ruby-version`):
  `.mise.toml` *installs* the toolchain; those fields are what other tooling *reads*.
  Don't introduce a second installer once mise owns the toolchain.
- **Cloud caveat:** `mise.run` / the mise CDN are NOT on the Claude-Code-web Trusted
  allowlist, but `github.com` and `nodejs.org` are. In a cloud setup script, install
  mise from a **pinned GitHub release tarball**, not the `curl https://mise.run | sh`
  one-liner.

## Working preferences

- **TDD-first.** Write a failing test before the implementation, make it pass, then
  verify the full suite is green before committing. Instrument and debug brittle
  tests rather than paper over them.
- **Adversarial review before committing.** When a plan/spec is finalized or a
  PR/diff is ready, run independent skeptical review — find what's wrong, not
  rubber-stamp. (See the `dev` plugin's `adversarial-review` skill.)
- **Never push or commit to `main` without explicit approval.** Gate irreversible or
  outward-facing actions — pushes, merges, branch/tag/worktree deletion — on an
  explicit go-ahead. Treat terse or ambiguous confirmations as needing clarification,
  not a green light.
- **Git history hygiene.** `git fetch` and rebase onto fresh `origin/main`, never a
  stale local `main`. Prefer fast-forward / linear history — one commit per
  reviewable unit; before review, squash doc-evolution thrash and fold in-branch
  reverts into their target. Never cite commit short-hashes in docs or PR bodies
  (rebases churn them). Before deleting branches/worktrees, verify merge status
  (including squash-merges); never remove the worktree the session runs inside.
- **Multi-task plans get a final cross-implementation review** — one symmetry pass
  over the full branch diff after per-task work, to catch type asymmetry between
  paired classes, parallel-structure drift, and cross-package coupling.
- **File creation: use Write/Edit, never `cat > file << EOF`** — heredoc-cat is
  forbidden everywhere, including `/tmp`. Brief subagents on this explicitly.
- **No `cd`-chained Bash** — `cd /path && cmd` triggers a permission prompt on the
  `cd`. Use `git -C`, `dart --directory`, a standalone `cd`, or brief subagents on
  cwd up front instead.
- **Never run destructive commands just to test them** — use dry-runs (`make -n`);
  destructive targets stay deny-listed / confirmation-gated.
- **Evidence before theories when diagnosing.** For environment / hardware / network
  issues, gather concrete evidence first (logs, exit codes, env diffs), then rank
  hypotheses by likelihood with the single cheapest disproving test for each.
- **Meaningful PR branch names** — rename to a descriptive `feat/…` / `fix/…` before
  pushing; never push an auto-generated `claude/<slug>` session branch.
