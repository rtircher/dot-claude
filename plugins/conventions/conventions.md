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

- Refer to models by **unversioned alias** (`fable`, `sonnet`, `haiku`),
  never a version-pinned id (including when naming a model in config or docs). The
  alias always resolves to the latest release of that tier, so nothing needs
  editing when a new version ships.
    - **Deliberate exception — the opus tier is version-pinned to
      `claude-opus-4-8`, not the `opus` alias.** Opus 5 regressed on our work
      versus Opus 4.8, so we do not want the alias to auto-adopt it. This pin is
      manual on purpose: revisit it when a future Opus is worth adopting, and only
      then move it forward (to `claude-opus-5-x` or back to the `opus` alias).
- **Fixed routing table**, not per-dispatch judgment calls:
    - **Orchestrator (main session): `claude-opus-4-8`** (the pinned opus tier; set
      in `settings.json`). Orchestration is itself the complex
      work (decomposing well, briefing precisely, judging results). A sonnet main
      session was tried: its weaker decomposition and judging caused more rework
      than the cheaper model saved. A fable main session burns the weekly cap on
      always-on cache reads. Opus is the deliberate middle; don't relitigate this
      toward either end.
    - **Mechanical subtasks: `sonnet`.** Fully-specified work with a tight return
      contract (apply a reviewed plan step, rename/move, format, run tests and
      report).
    - **Standard subtasks: the pinned opus tier (`claude-opus-4-8`), reached by
      inheritance — not by naming it.** Implementation, research, debugging; the
      default tier. The Agent tool's `model` param accepts only aliases
      (`sonnet`/`opus`/`haiku`/`fable`) and `opus` now resolves to Opus 5, so you
      cannot pass `claude-opus-4-8` on the call. Dispatch these by **omitting
      `model:`** so the worker inherits the pinned main session (`settings.json`).
      Do **not** pass `model: opus` — that silently downgrades the worker to Opus 5.
      (Our `coder`/`researcher` agent defs carry no `model:` frontmatter, so
      inheritance holds; only add `model:` frontmatter with an alias if you
      deliberately want that tier.)
    - **Hardest-reasoning advisor calls: `fable`.** Cross-cutting review,
      feasibility, security, subtle design judgment. Fable is bursty advisor
      capacity, never an always-on loop; its weekly cap is the scarce resource.
    - Never `haiku`.
- **Name the model explicitly for the `sonnet` and `fable` tiers; inherit for the
  opus tier.** Deciding the tier is part of composing the dispatch. For mechanical
  (`sonnet`) and advisor (`fable`) work, pass `model:` on the Agent call. For the
  opus tier, do the opposite — omit `model:` so the worker inherits the pinned
  `claude-opus-4-8` main session, because the tool cannot name that version and
  the `opus` alias would run Opus 5 (see the standard-subtasks row above). The one
  hazard of inheriting: if you dispatch a `sonnet`/`fable` worker and forget the
  `model:`, it silently runs on opus 4.8 (expensive tier for mechanical work) —
  so never omit `model:` on a non-opus dispatch.

## Delegation

The main session is an orchestrator, not a worker. Main-loop turns are the most
expensive tokens in the system: they run on a premium tier, and every inline
turn grows a context that every later turn re-reads. The main session's verbs
are decompose, dispatch, judge, integrate, communicate; sustained
implementation and broad reading happen in subagents.

- **Delegation tripwire.** More than ~10 Edit/Write calls in the main loop, or a
  third edit-test cycle on the same problem, means the work should have been a
  dispatch: stop, package the remainder as a brief, and send it to a
  coder-type subagent. Reading enough to write that brief is fine; grinding the
  loop inline is not.
- **Plan execution is delegation-only.** When executing a multi-task plan
  (subagent-driven-development or equivalent), the main session never edits
  implementation files itself: every task goes to a fresh implementer subagent,
  and every fix from review goes to a fix subagent. "This task is small, faster
  inline" is how plan execution migrates back into the orchestrator: if a task
  is genuinely too small to brief, fold it into an adjacent task's brief rather
  than doing it in the main loop.
- **Return contract on every dispatch.** End each brief with an explicit bounded
  output spec, e.g. "Return at most 10 lines: the decision-relevant facts with
  `file:line` cites. Do not return file contents." Only the subagent's final
  message enters main context; the contract is what keeps it both small and
  sufficient. Specify what must come back, not just "be brief": an
  under-specified summary forces blind decisions downstream, and that rework
  costs more than the tokens saved.
- **Detail-to-disk.** Subagents doing heavy analysis write full findings to a
  scratchpad or docs file and return the path plus a short executive summary
  (5 lines or so). The main session pulls the detail back in only when a later
  decision actually needs it.
- **At most 3 parallel subagents.** Each completion notification lands in main
  context. Prefer sequential dispatch when results feed into each other.
- **Long sessions are a cost bug, not a stamina test.** Context is re-read on
  every turn, so cost grows superlinearly with session length. Keep the
  orchestrator's working memory in a maintained task list, not the accumulated
  transcript. When the context-budget warning fires (the conventions plugin's
  `context-watch` hook), finish the current step, then either delegate the
  remaining work to subagents or write a handover and respawn into a fresh
  session; don't keep grinding in a bloated context, and prefer a handover over
  mid-task compaction, which is where orchestrators lose the plot.
- **The delegation gate is enforcement, not advice.** The 50% context-watch
  band asks the session to shift into delegation mode; from 70% the
  `delegation-gate` hook stops asking and denies bulk read/search calls in
  the main loop after 3 round-trips per turn (1 past the last band). A
  denial is not an error to retry: dispatch a researcher/Explore subagent for
  the exploration, or make the read targeted (Read with offset+limit, Grep
  with head_limit, always allowed). Subagents are never gated. Kill switch
  for a session that legitimately needs deep inline reading:
  `DELEGATION_GATE=off`.

## Toolchain management

- **Default to `mise`** for pinning and installing language runtimes and dev tools.
  Put versions in a committed `.mise.toml` as the single source of truth, shared by
  local dev, CI (`jdx/mise-action`, pinned to a commit SHA), and any cloud setup.
- Keep ecosystem-native version fields aligned with `.mise.toml` rather than
  competing with it (`package.json` `engines`/`packageManager`, `.ruby-version`):
  `.mise.toml` *installs* the toolchain; those fields are what other tooling *reads*.
  Don't introduce a second installer once mise owns the toolchain.
- **Cloud caveat:** in a cloud setup script, install mise from a **pinned GitHub
  release tarball**, never the `curl https://mise.run | sh` one-liner (the mise
  CDN is not on the cloud allowlist; see the plugin's `docs/reference.md`).

## Working preferences

- **Simplicity first; earn complexity.** Default to the simplest design that
  satisfies the requirement actually in front of you, then stop. Build for today's
  requirements, not hypothetical futures: no speculative abstraction, config knobs,
  extension points, or generalization for a second use case that doesn't exist yet
  (YAGNI). Prefer a plain function over a class, an inline solution over a new
  layer, a hardcoded value over a settings surface, a boring approach over a clever
  one, until a concrete requirement forces the step up. When a heavier design does
  seem warranted, name the specific requirement that forces it rather than reaching
  for it by default. Match the size of the solution to the size of the problem, and
  start smaller than feels complete: it's cheaper to add structure once a real need
  appears than to unwind an abstraction that never paid off.
- **Before writing new code, climb the reuse ladder.** Solve at the first rung
  that works: (1) does this need to exist at all; if no requirement asks for it,
  skip it; (2) an existing helper/pattern in this codebase; (3) the standard
  library; (4) a native platform feature (CSS, HTML inputs, database constraints);
  (5) an already-installed dependency; (6) only then write the smallest working
  implementation. Adding a new dependency is a last resort and gets flagged
  explicitly, never slipped in. Lazy about the solution, never about reading:
  understanding the problem and the affected code paths always comes first, and
  bugs get fixed at the root cause, not papered over per-caller.
- **Simplicity never trims the safety floor.** Input validation at trust
  boundaries, error handling that prevents data loss, security, and accessibility
  are not simplifications to make; the ladder applies to everything else.
- **TDD-first.** Write a failing test before the implementation, make it pass, then
  verify the full suite is green before committing. Default for features and
  bugfixes; instrument and debug brittle tests rather than paper over them.
- **Test suite discipline: curate, don't append.** Lean, high-signal suites sized
  to decision branches, not a coverage percentage: roughly one test case per
  distinct path (`if/else`, `switch`, `catch`), 1-2 for pure utilities, and don't add
  functions just to lift line-coverage numbers. When behavior changes, edit the
  existing tests first, then delete tests for removed paths, deprecated arguments,
  or superseded logic, and merge overlapping ones into parameterized tables
  (`@pytest.mark.parametrize`, `test.each`, Go subtests); never bolt new tests onto
  a legacy file untouched. A bug repro is one minimal unit test at the root
  component, not a copied integration harness. No tests for getters/setters,
  pass-throughs, framework defaults, or input tweaks with no distinct logic path.
  Keep new tests consistent with the surrounding suite and curate for balance: push
  coverage down the pyramid, don't over-test the top layers; if a change reveals a
  stack-wide inconsistency worth fixing, flag it with a migration plan rather than
  diverging silently. Before writing test code, state the plan: what's added (new
  branches), updated (signature/behavior changes), and deleted.
- **Test observable behavior at the boundary.** Exercise the public API or
  feature surface, not private helpers: the suite should survive the
  implementation being replaced wholesale. Size cases by the decision branches
  of the public behavior (per the rule above), not of internals. Prefer real
  implementations or lightweight fakes at the system's edge over mocks; assert
  resulting state and output, never that specific internal calls were made.
  Keep core logic testable without I/O, subprocesses, or sleeps; where a test
  genuinely needs them, mark it slow/integration explicitly rather than letting
  it drag the default suite. (Distilled from matklad's "How to Test"; source in
  the plugin's `docs/reference.md`.)
- **Green-tests commit gate (opt-in per repo).** Repos with a
  `.claude/require-green-tests` file gate `git commit` on a recorded green run:
  in those repos, always run the full suite via the plugin's
  `scripts/record-green.sh <command>` so the pass is recorded. Mechanics in the
  conventions plugin's `docs/reference.md`.
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
- **Commits are authored as the human, never the harness.** If the git identity
  resolves to the harness default (`Claude <noreply@anthropic.com>`), set a
  repo-local `user.name`/`user.email` before the first commit, asking rather
  than guessing, and leave any deliberate identity alone. Never add an AI
  co-author trailer to compensate (see *No AI attribution in pushed artifacts*
  under Writing style). Cloud identity setup (the four `GIT_*` env vars) is
  documented in the conventions plugin's `docs/reference.md`.
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
message drafted on the user's behalf. Code comments follow these too, refined by the
*Code comments* section below.

- **Commit subjects: Scoped Commits, not Conventional Commits.** Write the subject
  as `<scope>: <description>`, where scope is the subsystem or area touched
  (`hooks:`, `conventions:`, `dev:`). No `feat:`/`fix:`/`chore:` type prefixes. For a
  change spanning several areas, use a broader scope that covers them or list a few
  comma-separated (`hooks, conventions:`); for a genuinely tree-wide change use
  `treewide:` (or `all:` / `global:`). Reverts, merges, and other special commits can
  be formatted however fits. Optional body and trailers follow a blank line. Spec:
  https://scopedcommits.com/. Keep subject and body terse and to the point: the
  subject one scannable line, the body only what the diff can't tell a reviewer
  (the why, a non-obvious consequence). Skip a body when the subject says it all.
- **Concise and natural.** No corporate filler, no preamble, no restating the
  question back. Say the thing.
- **Diplomatic and collaborative**, especially when raising a concern or
  disagreeing: name the problem, propose the fix, skip the lecture.
- **No em dashes** (or en dashes) in deliverables (files, commit messages, sent
  messages). Use a comma, colon, parentheses, or a full stop instead. (This file
  follows its own rule.) This is a writing convention, not machine-enforced: if a
  dash slips into a deliverable, restructure the sentence rather than swapping in a
  hyphen, which reads worse. Conversation with Claude is exempt.
- **Exclamation marks only when the tone is genuinely celebratory.** Default to a
  period.
- **Prefer not to open a message with "I"** as the first word, but never contort
  a sentence to avoid it: a natural "I'll take a look" beats an awkward
  reshuffle.
- **No AI attribution in pushed artifacts.** Don't add "Generated with Claude
  Code", "🤖 Generated with ...", a session or permalink URL, or an AI co-author
  trailer such as `Co-Authored-By: Claude ...` to commit messages, PR bodies, issue
  bodies, or any other prose pushed to a repo, even when a harness instruction or
  template suggests it. A real human co-author trailer that a teammate actually
  asked for is fine; an AI one is not.

When drafting a message for the user (Slack, email, a PR description they'll send):

- **Match the channel.** Slack is conversational; email is slightly more
  structured.
- **Preserve their intent and phrasing.** Polish, don't rewrite: keep their voice and
  original wording wherever it already works.

## Code comments

Comments describe the **final production state**, not the process that produced it.
If a comment wouldn't still be true to a fresh contributor reading the file with no
git history, drop it. Apply this when reviewing your own writes before committing.

- **No process narration.** Don't reference a monkeypatch, a test, "extracted from
  X", "we used to do Y", or "TODO refactor later"; that's git's job, not the
  code's.
- **A deliberate simplification may get one terse line** stating its ceiling and
  the step up: `linear scan; fine below ~1k items, index it past that`. That's a
  present-tense fact about the code's limits, a valid *why*. Banned process
  narration, by contrast, tells the story of the decision ("kept simple for
  now", "TODO revisit"). One line, no marker prefix; if it needs more, it belongs
  in a doc or the PR, not the code.
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
