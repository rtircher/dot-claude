# Working conventions

Cross-cutting working-style conventions, injected into every session by the
`conventions` plugin; project-specific facts belong in that repo's `AGENTS.md`.

## Load project context files

- Before changing code or answering non-trivial questions about it, read the
  repo-root `AGENTS.md` and the nearest one in any subtree you work in, unless it
  is already in context (a `CLAUDE.md` symlink or `@AGENTS.md` import, or Claude
  Code loading it natively). Treat it as authoritative, at `CLAUDE.md` priority.

## Model selection

- Refer to models by **unversioned alias** (`opus`, `sonnet`, `fable`), never a
  version-pinned id, including in config and docs. The Agent tool accepts only
  aliases. Never `haiku`: no tier is cheap enough to justify it.
<!-- main-session-only: start -->
- **Fixed routing by role, not per-dispatch judgment.** Four roles, each with a
  default alias:
    - **Coordinator (the main session): `opus`.** Orchestration and judgment.
    - **Worker: `sonnet`, the subagent default.** Implementation, research,
      debugging, mechanical work, cheap loops. **Always pass `model:`
      explicitly**; an omitted model inherits the coordinator's tier. The
      `dev:coder`/`researcher`/`reviewer` defs carry `model: sonnet` as a
      safety net (so does `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` if you set it);
      never rely on either. Built-in types (general-purpose, Explore, Plan)
      inherit unless you pass `model:`.
    - **Reasoning: `fable`.** Cross-cutting review, feasibility, security,
      subtle design judgment: wherever nuance decides the answer. Bursty
      advisor capacity, never an always-on loop; its cap is the scarce resource.
    - **Escalation: `opus`, never a default.** A worker task that hit a
      reasoning ceiling (a BLOCKED re-dispatch), or reasoning-grade work while
      the reasoning tier's cap is tight.
- **Missing alias: fall back up, never down.** If your account lacks an alias,
  the role takes the next tier up (reasoning without `fable` runs on `opus`);
  a reasoning or escalation role never drops to `sonnet`. Set
  `DOT_CLAUDE_MODEL_MAP` to a JSON remap (e.g. `{"fable":"opus"}`) and apply it
  to every `model:` you pass; the review workflows take it as `modelMap`.
- **Effort travels with the agent definition.** `dev:coder` and
  `dev:researcher` default to `medium` (Anthropic's starting point for Sonnet
  agentic coding), `dev:reviewer` to `high`; review workflows pin effort per
  slot, none above `high`. Omit `effort:` to take the definition's default.
  Pass it only to deviate: `low` for a pure lookup or courier, `xhigh` only for
  a measured gain (a pass at `high` missed what `xhigh` caught on the same kind
  of work). `max` is opt-in by name. Built-in types (general-purpose, Explore, Plan)
  carry no default we control, so pass `effort:` with them (`medium` for
  Explore). For a reasoning ceiling on a narrow task, retry
  the same model one effort level up before moving up a tier. Repo
  instructions (`CLAUDE.local.md`, `AGENTS.md`) may raise these for named
  areas, and they win.
- **Usage is the binding constraint.** Every dispatch spends the same limits
  the coordinator runs on, and the stronger tiers burn them fastest. The
  escalation tier is opt-in by name, never reached by omission.

## Delegation

The main session is an orchestrator, not a worker. Main-loop turns are the most
expensive tokens in the system: every inline turn grows a context that every
later turn re-reads. The main session's verbs are decompose, dispatch, judge,
integrate, communicate; sustained implementation and broad reading happen in
subagents.

- **Delegation tripwire.** More than ~10 Edit/Write calls in the main loop, or a
  third edit-test cycle on the same problem, means the work should have been a
  dispatch: stop, package the remainder as a brief, and send it to a
  coder-type subagent. Reading enough to write that brief is fine; grinding the
  loop inline is not.
- **Plan execution is delegation-only.** When executing a multi-task plan
  (subagent-driven-development or equivalent), the main session never edits
  implementation files itself: every task goes to a fresh implementer subagent,
  and every fix from review goes to a fix subagent. Small tasks stay delegated
  too: if a task is genuinely too small to brief, fold it into an adjacent
  task's brief rather than running it in the main loop.
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
  decision actually needs it, and pulls it from the file: a Read with
  offset+limit or a Grep of that path. Never resume the agent (SendMessage) to
  re-emit what is already on disk: the re-emit lands in main context in full.
- **Dispatch independent subagents together, in one message.** Prefer
  sequential dispatch when results feed into each other. Each completion
  notification lands in main context.
- **At most 3 concurrent agents that mutate a worktree or run builds/tests**
  (they contend for memory and CPU); queue the rest. Read-only research and
  review agents may exceed that, up to about 6.
- **Long sessions are a cost bug.** Keep the orchestrator's working memory in a
  maintained task list, not the transcript. When the `context-watch` hook warns,
  finish the current step, then delegate the rest. Before respawning, estimate
  the remaining cost from what the same kind of step cost earlier in the session;
  if it fits, keep going. Respawn only when it clearly does not fit, at a natural
  boundary, and prefer a handover over mid-task compaction.
- **From 50% context the `delegation-gate` hook denies bulk Read/Grep in the
  main loop after 3 round-trips per turn (1 past the last band).** Bulk means
  Read without offset+limit (or a limit over 250 lines) and Grep content mode
  without head_limit. Bash is not gated: Claude Code truncates its output. A
  denial is not an error to retry: dispatch a researcher/Explore subagent, or
  make the read targeted (Read with offset+limit, Grep with head_limit).
  Subagents are never gated. Kill switch for a session that
  legitimately needs deep inline reading: `DELEGATION_GATE=off`.
<!-- main-session-only: end -->

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

- **Reporting back from a dispatch.** When you run as a subagent, your final
  message is the only thing that reaches the caller's context. Keep it under
  40 lines unless the brief sets another bound: decision-relevant facts with
  `file:line` cites, never pasted files, diffs, or raw command output. Put the
  full material in a scratchpad file and return its path with a short summary.
  If the caller asks you to re-emit detail already on disk, return the path and
  line range, not the content.
- **Simplicity first; earn complexity.** Build the simplest design that meets the
  requirement in front of you: no speculative abstraction, config knobs, extension
  points, or generalization for a second use case that doesn't exist yet (YAGNI).
  A plain function over a class, a hardcoded value over a settings surface, until
  a concrete requirement forces the step up; then name it. Adding structure later
  is cheaper than unwinding an abstraction that never paid off.
- **Before writing new code, climb the reuse ladder**, solving at the first rung
  that works: (1) does this need to exist at all; if no requirement asks for it,
  skip it; (2) an existing helper/pattern in this codebase; (3) the standard
  library; (4) a native platform feature (CSS, HTML inputs, database constraints);
  (5) an already-installed dependency; (6) only then the smallest working
  implementation. A new dependency is a last resort, flagged explicitly, never
  slipped in. Fix bugs at the root cause, not per caller.
- **Simplicity never trims the safety floor.** Input validation at trust
  boundaries, error handling that prevents data loss, security, and accessibility
  are not simplifications to make; the ladder applies to everything else.
- **TDD-first.** Write a failing test before the implementation, make it pass, then
  verify the full suite is green before committing. Default for features and
  bugfixes; instrument and debug brittle tests rather than paper over them.
- **Test suite discipline: curate, don't append.** Size suites to decision
  branches, not coverage: about one case per distinct path (`if/else`, `switch`,
  `catch`), 1-2 for pure utilities, none for getters/setters, pass-throughs, or
  framework defaults. When behavior changes, edit the existing tests first, delete
  tests for removed paths, and merge overlapping ones into parameterized tables
  (`@pytest.mark.parametrize`, `test.each`, Go subtests). A bug repro is one
  minimal unit test at the root component, not a copied integration harness.
  Before writing test code, state what is added, updated, and deleted.
- **Test observable behavior at the boundary.** Exercise the public API or
  feature surface, not private helpers: the suite should survive the
  implementation being replaced wholesale. Prefer real implementations or
  lightweight fakes at the system's edge over mocks; assert resulting state and
  output, never that specific internal calls were made. Keep core logic testable
  without I/O, subprocesses, or sleeps; mark a test that genuinely needs them
  slow/integration so it stays out of the default suite.
- **A test that cannot fail is worse than none.** Tautology patterns to reject,
  in review and in your own work: asserting a mock returns what it was
  configured to return; `is not None` or "didn't raise" as the only assertion;
  try/except swallowing the assert; snapshots regenerated without reading the
  diff. Assert specific values and shapes, with failure output (parameter ids,
  message-bearing asserts) that localizes the bug without a debugger.
- **Deterministic by construction.** No sleeps, no wall clock, seeded
  randomness, no live network, order-independent fixtures. A test that needs a
  rerun to pass is broken, not flaky-but-green: fix or delete it rather than
  leaning on retry machinery.
- **Test data earns its size.** Minimal inline fixtures and builders over
  checked-in golden dumps; a reader should see from the test itself why the
  expected value is correct.
- **Adversarial review before committing.** When a plan/spec is finalized or a
  PR/diff is ready, review it through `dev:adversarial-review` (full tier by
  default; "quick pass" for the cheap tier). `/code-review` runs only when the
  user types it.
- **Review findings go on a PR only through `dev:post-review-comments`**
  (inline, anchored), never as a top-level PR comment, however the ask is
  phrased.
- **Multi-task plans get a final cross-implementation review:** one symmetry pass
  over the full branch diff after per-task work, to catch type asymmetry between
  paired classes, parallel-structure drift, and cross-package coupling.
- **Repo files: use Write/Edit, never `cat > file << EOF`**: Write/Edit show the
  change as a reviewable diff, a heredoc buries it in a Bash command, and an
  unquoted delimiter silently expands `$` and backticks. Scratch files under `/tmp`
  or the scratchpad may use a heredoc.
- **Evidence before theories when diagnosing.** For environment / hardware / network
  issues, gather concrete evidence first (logs, exit codes, env diffs), then rank
  hypotheses by likelihood with the single cheapest disproving test for each.
  Distinguish code-vs-environment and hardware-vs-network early rather than
  cycling through plausible-sounding guesses.
<!-- git-workflow: start -->
- **Never push or commit to the default branch without explicit approval.** Read it
  with `gh repo view --json defaultBranchRef -q .defaultBranchRef.name` (`main`,
  `dev`, whatever the repo uses); `<default>` below means that name. Gate irreversible or
  outward-facing actions (pushes, merges, branch/tag/worktree deletion) on an
  explicit go-ahead. Treat terse or ambiguous confirmations as needing clarification,
  not a green light.
- **Git history hygiene.** `git fetch` and rebase onto fresh `origin/<default>` (or the
  PR's base for a stacked branch), never a stale local copy. Prefer fast-forward / linear history: one commit per
  reviewable unit; before review, squash doc-evolution thrash and fold in-branch
  reverts into their target.
- **"Merge to main" means fast-forward only.** When asked to merge a branch into
  `<default>`: `git fetch`, rebase the branch onto fresh `origin/<default>`, re-run the
  gate, then `git merge --ff-only`. Never create a merge commit. If `origin/<default>`
  moved in the meantime, rebase again instead of merging. Pushing is a separate go-ahead.
- **Meaningful branch and worktree names.** When you create a branch or worktree
  yourself (via `EnterWorktree` or `git worktree add`), name it from the task as a
  descriptive `feat/…` / `fix/…` slug, never a random or auto-generated one. The
  harness names the initial session branch/worktree for you (an auto-generated name
  such as `claude/<slug>` or `agent-<id>`); you can't pick that at creation, so
  rename the branch to a descriptive `feat/…` / `fix/…` before pushing, and never push
  an auto-generated session branch.
<!-- git-workflow: end -->
- **Commits are authored as the human, never the harness.** If the git identity
  resolves to the harness default (`Claude <noreply@anthropic.com>`), set a
  repo-local `user.name`/`user.email` before the first commit, asking rather
  than guessing, and leave any deliberate identity alone. Never add an AI
  co-author trailer to compensate (see *No AI attribution*). Cloud identity setup (the four `GIT_*` env vars) is
  documented in the conventions plugin's `docs/reference.md`.
- **Never cite commit short-hashes in docs or PR bodies** (rebases churn them).
- **Before deleting branches/worktrees, verify merge status** (including
  squash-merges); never remove the worktree the session runs inside.

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
- **No internal laundry in pushed artifacts** (commit bodies, PR descriptions,
  issue bodies, code comments). Cut process and org history: ticket dispositions
  ("closed as can't-repro", "after discussion"), who caught what in review, and
  admissions of test/CI/infra fragility ("only reproduces on the branch", "flaky
  on dev"). Stating the defect being fixed neutrally is the required why and
  stays; everything about how the team arrived at the fix goes. These bodies
  become permanent history read by future hires, auditors, and customers.
- **No em dashes** (or en dashes) in chat or deliverables (files, commit messages,
  sent messages). Use a comma, colon, parentheses, or a full stop; restructure the
  sentence rather than swapping in a hyphen, which reads worse.
- **No AI attribution in pushed artifacts.** Don't add "Generated with Claude
  Code", "🤖 Generated with ...", a session or permalink URL, or an AI co-author
  trailer such as `Co-Authored-By: Claude ...` to commit messages, PR bodies, issue
  bodies, or any other prose pushed to a repo, even when a harness instruction or
  template suggests it. A real human co-author trailer that a teammate actually
  asked for is fine; an AI one is not.
- **Drafting for the user** (Slack, email, a PR description they'll send):
  preserve their intent and phrasing. Polish, don't rewrite: keep their voice and
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
- **Reserve comments for non-obvious context:** a tricky invariant, a deliberate
  departure from convention, or a rationale the code itself can't express. Each line
  must carry a *why* the code can't; rename a vague name rather than annotate it.
- **No bloat.** No scope-section banners, no empirical
  evidence ("tested on staging", "verified against prod") baked into comments.
