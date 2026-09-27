---
name: adversarial-review
description: Use when you want independent, adversarial review of a plan, spec/design doc, or PR/diff before committing to it; reviewers are prompted to find what's wrong, not rubber-stamp. Triggers on "adversarial review", "independent review", "poke holes in this", "red-team this plan/spec/PR", or when a plan/spec is finalized and about to become implementation. Also triggers on a bare PR URL or number, "review this PR", "code review", "deep review", "full review", "quick pass", "quick review", "quick look", or "quick check". Full tier is the default; quick is opt-in.
---

# Adversarial Review

## What it is

Run independent, skeptical reviewers against a plan, spec, or diff and return one deduped, severity-ranked list of objections. Advisory only: this skill never edits files and never blocks. Two tiers: full (default) and quick (opt-in), below.

## Tier budgets

Hard caps this skill states and enforces.

| Tier | Context | Agents |
|---|---|---|
| Quick | main session | at most 3 area reviewers, one message, never more than 3 in parallel; +1 focus-declared extra lens as a second wave after they return = 4 max; 1 when the diff is small |
| Quick | subagent | 0 (inline single pass) |
| Full | Workflow path | 4 + N + 12 for a diff or spec, 3 + N + 12 for a plan (N = external names), +1 when the extra lens fires |
| Full | manual / cloud path | 3 to 4 lens agents; externals run through Bash |
| Gated | | at most 3 rounds, 50 + 3N total |

Rounds exist only in gated review; the full tier's per-invocation budget is not multiplied by rounds.

- Every review prints its tier and actual agent count on the first line.
- Quick never escalates to full on its own; it offers escalation and states the cost, for example "full panel: about 20 agents".
- Full offers nothing cheaper automatically. Its output ends with a one-line hint that "quick pass" exists, so the cheap path is discoverable without full picking it for the user.

## Step 0: resolve input

`<plugin>` below is the `dev` plugin root: two levels above this skill's base directory. Substitute its absolute path into commands; `${CLAUDE_PLUGIN_ROOT}` may be unset when this loads as a skill.

Determine the artifact type: **spec** (a requirements or design document), **plan** (an implementation plan: steps, sequencing, tasks), or **diff** (code changes: a branch diff or GitHub PR).

An explicit artifact is required: a file path, a diff range like `main...HEAD`, a branch, or a PR number or URL. The only allowed inference is a bare invocation on a branch with one unambiguous diff against the trunk (use `<trunk>...HEAD`). Anything else: ask which artifact, once, then proceed. Never infer by recency or pick the "most recently written" spec or plan.

1. **Resolve.** Run `gh pr view <n|url> --json number,url,headRefOid,headRefName,baseRefName,files,additions,deletions,isDraft,title`. A URL for a repo other than cwd: the quick tier proceeds remotely (2b); the full tier needs a checkout, reading via a detached worktree, see `full.md` step 1 (fails closed under `unattended: true`, else asks once).
2. **Quick reads, no checkout:**
   - a. In a clone: `<remote>` is the `git remote` matching the PR's repo, never an assumed `origin`. `git fetch <remote> <headRefOid>` (fall back to `pull/<n>/head`) and fetch the base. Reviewers read slices with `git diff <remote>/<base>...<headRefOid> -- <files>` and context with `git show <headRefOid>:<path>`. Save the full `git diff` once to the scratchpad, unused unless the extra lens (`quick.md`) fires.
   - b. Not in a clone (including cloud on a different repo): save `gh pr diff <n>` once to the scratchpad; each area reviewer gets that path plus its file list. Context files come from `gh api repos/{o}/{r}/contents/<path>?ref=<headRefOid>`.
3. **Local diff, no PR:** `git diff <remote>/<default>...HEAD` in cwd, where `<default>` is `gh repo view --json defaultBranchRef -q .defaultBranchRef.name` and `<remote>` is `origin`. The size gate uses `--numstat`.

## Load focus

A `## Review focus` heading in an existing root context file. Check, in order, `CLAUDE.local.md`, then `AGENTS.md`, then `CLAUDE.md`; the **first one with the heading wins**, no concatenation.

Tracked files are always read at the PR's base, never head, never whatever is checked out: in a clone (2a), `git show <remote>/<baseRefName>:<file>`; no clone (2b), `gh api repos/{o}/{r}/contents/<file>?ref=<baseRefName>`; local diff (3), `git show <remote>/<default>:<file>`; full's worktree, the same base read. If the base ref is not present locally, fetch it first; if that fetch fails, read the tracked file from the working tree and print `focus: read from working tree`.

`CLAUDE.local.md` is untracked, so it is read from disk at the cwd repo root whatever is on disk right now, including in the full-tier worktree case (read from the original cwd repo root, not the detached worktree, which would not carry an untracked file). In the no-clone case there is no disk to read it from: it is skipped, Areas/Migrations/Extra lens fall back to none declared, and the tier line prints `focus: unavailable (no clone)`.

The section is prose bullets plus optional `Areas:`, `Migrations:`, `Extra lens: <skill>` lines. Split those three out; pass the rest verbatim as `focus`. `Areas:`/`Migrations:` feed only the quick tier's bucketing; `Extra lens:` feeds the gated extra agent on either tier. Warn, never truncate, past 40 lines.

Caller-supplied focus (an explicit `focus` arg from `dev:gated-review` or autonomous-feature) is appended to the section above.

## Pick tier

Top to bottom, first match wins.

| Signal | Tier |
|---|---|
| Called by `dev:gated-review`, `dev:review-workflow`, autonomous-feature, or `/dev:review-panel` | full |
| Artifact is a spec, plan, or design doc | full (quick is diff-only) |
| The user says adversarial, independent, red-team, poke holes, panel, external, "full review", or "deep review" | full |
| A bare PR URL or number, "review this PR", "code review" | full |
| The user says "quick pass", "quick review", "quick look", or "quick check" | quick |
| Anything else that asks to review a diff | full |

- A bare PR URL or number defaults to full; quick fires only on its explicit phrase and never escalates on its own.
- The tier choice is printed, so a misroute costs one correcting sentence.
- `/code-review` (the built-in) runs only when the user types it.

## Contexts

| Context | Quick | Full |
|---|---|---|
| Local main session | as designed | Workflow path |
| Cloud main session (no `Workflow`) | as designed; uses only `Agent`, `gh`, `git` | manual path: lens agents, externals via Bash when configured, no verify; single-reviewer blockers marked `unverified (single reviewer, manual path)` |
| Subagent (no `Agent`) | inline single pass, labelled `tier: quick (inline, 0 agents)`; only for someone else's PR, never a self-review (hand back instead) | stop and tell the caller to run it from the main session |
| Gated review | n/a | local only |

- A single pass is honest only when labelled: quick's subagent row is the one place this design lets a single pass stand in, and only because it says so.
- Self-review stays refused either way; it defeats the adversarial stance.
- Cloud without `gh` auth: quick falls back to the local-diff step above, or reports it cannot read the PR.

## Run the tier

Read `full.md` or `quick.md` (absolute path beside this file, in this skill's base directory) and follow it.

## Output contract

1. First line: `tier: quick|full · agents: N · <single-pass|areas: a, b, c> · externals: <who | none (quick) | shortfall (reason)>`. `N` includes the focus-declared extra lens when it fired.
2. Full tier only: `panel: dispatched N lenses, returned M; missing: …`. A missing lens caps the verdict at don't-ship-yet.
3. Whenever the focus declares an `Extra lens:`, a mandatory line: `extra lens: <name>: ran | not applicable (<reason>) | not_run (<reason>)`.
4. A reviewer orientation list of 3 to 6 `file:line` spots, written by the main session from the PR metadata and diff it already fetched, emitted in the same message as the dispatch, before agents return.
5. A punch list, blocker / major / minor. Within a severity, verified before speculative. Duplicates collapse into one entry marked `x2`.
6. A `## Simplify` section with `cut now` or `follow-up` per item; these never move the verdict.
7. A verdict, led by verified findings. Quick: `ship (quick, unverified)` or `don't-ship (quick)`, never a bare `ship`. Full: `ship` or `don't-ship`.
8. The next-step offer. Full tier: end with `Cheaper next time: say "quick pass" (1 to 4 agents, unverified).`

Chat only. Nothing is posted without an explicit "post"; on that, follow `posting.md` in this directory.

## Anti-patterns

- **Agreeable review.** "Looks good, minor nits" means the framing was too soft. Reviewers must hunt for real problems.
- **Redundant lenses.** Three reviewers finding the same class of issue wastes the panel. Keep lenses distinct.
- **Sequential dispatch.** Reviewers must be independent: dispatch them in one message, never feed one reviewer's output to the next.
- **Phantom third-party review.** Never imply an external reviewer weighed in when it was unavailable, errored, or dropped; a vote without a matching digest and a well-formed verdict is dropped, never counted.
- **Same-family "third party".** An endpoint running a Claude model never counts as cross-family corroboration. Independence is the model family, not the tool.
- **Prestige-weighted scoring.** Score blind to model identity; the signal is corroboration count and cross-family agreement, not the brand name.
- **Third-party instead of the panel.** An external reviewer never substitutes for the Claude lens panel; "use external" means add it, not swap it. A run with only external findings skipped the panel and is wrong.
