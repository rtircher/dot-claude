# Working conventions

Cross-cutting working-style conventions, injected into every session (local and
cloud) by the `conventions` plugin's SessionStart hook. This file is the single
source of truth: edit here, and every project that enables the plugin picks it
up on its next session. Project-specific facts belong in that repo's `AGENTS.md`,
not here.

## Load project context files

At the start of work in any repository, before making changes or answering
non-trivial questions about the code:

- If an `AGENTS.md` exists at the repo root, **read it first.** It holds project
  conventions (package boundaries, command quirks, supply-chain rules, do/don't
  lists) that are not otherwise auto-loaded into context.
- When working inside a specific package or subdirectory, also read the nearest
  `AGENTS.md` in that subtree if one exists; it refines the root conventions for
  that area.
- Treat these `AGENTS.md` files as authoritative project instructions, at the
  same priority you would give a `CLAUDE.md`.

## Model selection

- Refer to models by **unversioned alias** (`opus`, `sonnet`, `haiku`), never a
  version-pinned id (including when naming a model in config or docs). The alias
  always resolves to the latest release of that tier, so nothing needs editing
  when a new version ships.
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
  verify the full suite is green before committing. Default for features and
  bugfixes; instrument and debug brittle tests rather than paper over them.
- **Adversarial review before committing.** When a plan/spec is finalized or a
  PR/diff is ready, run independent skeptical review: find what's wrong, not
  rubber-stamp. (See the `dev` plugin's `adversarial-review` skill.)
- **Never push or commit to `main` without explicit approval.** Gate irreversible or
  outward-facing actions (pushes, merges, branch/tag/worktree deletion) on an
  explicit go-ahead. Treat terse or ambiguous confirmations as needing clarification,
  not a green light.
- **Git history hygiene.** `git fetch` and rebase onto fresh `origin/main`, never a
  stale local `main`. Prefer fast-forward / linear history: one commit per
  reviewable unit; before review, squash doc-evolution thrash and fold in-branch
  reverts into their target. Never cite commit short-hashes in docs or PR bodies
  (rebases churn them). Before deleting branches/worktrees, verify merge status
  (including squash-merges); never remove the worktree the session runs inside.
- **Autonomous pipeline for low-risk features.** For a feature you flag as
  low-risk, the `dev` plugin's `/autonomous-feature` skill runs spec →
  adversarial-review → plan → adversarial-review → implement → adversarial-review
  of the code hands-off, pinging only on its contract. Explicitly invoked only;
  never auto-launch it.
- **Multi-task plans get a final cross-implementation review:** one symmetry pass
  over the full branch diff after per-task work, to catch type asymmetry between
  paired classes, parallel-structure drift, and cross-package coupling.
- **File creation: use Write/Edit, never `cat > file << EOF`.** Heredoc-cat is
  forbidden everywhere, including `/tmp`. Brief subagents on this explicitly.
- **No `cd`-chained Bash.** `cd /path && cmd` triggers a permission prompt on the
  `cd`. Use `git -C`, `dart --directory`, a standalone `cd`, or brief subagents on
  cwd up front instead.
- **Never run destructive commands just to test them.** Use dry-runs (`make -n`);
  destructive targets stay deny-listed / confirmation-gated.
- **Evidence before theories when diagnosing.** For environment / hardware / network
  issues, gather concrete evidence first (logs, exit codes, env diffs), then rank
  hypotheses by likelihood with the single cheapest disproving test for each.
  Distinguish code-vs-environment and hardware-vs-network early rather than
  cycling through plausible-sounding guesses.
- **Meaningful branch and worktree names.** When you create a branch or worktree
  yourself (via the `using-git-worktrees` skill or `EnterWorktree`), name it from the
  task as a descriptive `feat/…` / `fix/…` slug, never a random or auto-generated one.
  The harness names the initial session branch/worktree for you (`claude/<slug>`, e.g.
  `claude/zealous-wiles-65e0d5`); you can't pick that at creation, so rename the branch
  to a descriptive `feat/…` / `fix/…` before pushing, and never push an auto-generated
  `claude/<slug>` session branch.

## Writing style

How to write prose: chat responses, commit messages, PR bodies, docs, and any
message drafted on Renaud's behalf. Code comments follow these too, refined by the
*Code comments* section below.

- **Concise and natural.** No corporate filler, no preamble, no restating the
  question back. Say the thing.
- **Diplomatic and collaborative**, especially when raising a concern or
  disagreeing: name the problem, propose the fix, skip the lecture.
- **No em dashes** (or en dashes). Use a comma, colon, parentheses, or a full stop
  instead. (This file follows its own rule.) A `PreToolUse` hook enforces this only
  on text written as the user, the content of a Write/Edit, a commit message, a sent
  message, denying the call before the dash lands so it gets rewritten. Conversation
  with Claude is not checked, only deliverables. There is no inline override marker
  (it would pollute the file or message). For a file that genuinely needs a dash,
  such as one quoting verbatim, add its path to the `ALLOWLIST` in `block-emdash.py`.
- **Exclamation marks only when the tone is genuinely celebratory.** Default to a
  period.
- **Don't open a message with "I"** as the first word.

When drafting a message for Renaud (Slack, email, a PR description he'll send):

- **Match the channel.** Slack is conversational; email is slightly more
  structured.
- **Preserve his intent and phrasing.** Polish, don't rewrite: keep his voice and
  original wording wherever it already works.

## Code comments

Comments describe the **final production state**, not the process that produced it.
If a comment wouldn't still be true to a fresh contributor reading the file with no
git history, drop it. Apply this when reviewing your own writes before committing.

- **No process narration.** Don't reference a monkeypatch, a test, "extracted from
  X", "we used to do Y", or "TODO refactor later"; that's git's job, not the
  code's.
- **Prefer self-documenting code.** A clear name beats a comment explaining a vague
  one; rename rather than annotate.
- **Reserve comments for non-obvious context:** a tricky invariant, a deliberate
  departure from convention, or a rationale the code itself can't express. Each line
  must carry a *why* the code can't.
- **Terse and direct.** Clarity > brevity, but the comment itself stays concise;
  sacrifice grammar for clarity where it helps. Skip anything a good name or the
  code already makes obvious.
- **No bloat.** No scope-section banners, no PR/branch/host references, no empirical
  evidence ("tested on H100", "verified against prod") baked into comments.
- **Doc comments** (dartdoc, docstrings, JSDoc, …) follow the language's idiomatic
  style, kept minimal and focused on args/returns/raises. Per-project rules (e.g.
  "all public API members need a doc comment") live in that repo's `AGENTS.md`.
