# Conventions reference: mechanics

Operational detail extracted from `conventions.md` to keep the per-session
injection small. The conventions file states each rule; this file holds the
setup and mechanics for the sessions that actually need them.

## Cloud git identity (the four GIT_* env vars)

Cloud containers boot with the harness git identity
(`Claude <noreply@anthropic.com>`); the owner's identity is deliberately never
written into a repo. Each cloud environment carries it instead, as env vars set
once in the environment settings at claude.ai/code: all four of
`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`,
`GIT_COMMITTER_EMAIL`. Git honors them natively, so nothing else is needed;
author vars alone leave the committer field as the harness.

Repos carrying the cloud-parity seed warn in the session-start pulse when the
vars are missing and the identity is the harness default. In that case set a
repo-local `user.name`/`user.email` before the first commit, asking rather than
guessing, and leave any deliberate identity alone. Only the git author changes;
never add an AI co-author trailer to compensate.

## Testing-rule sources

The `testing` skill's "Test observable behavior at the boundary" rule distills matklad's
"How to Test" (https://matklad.github.io/2021/05/31/how-to-test.html):
test features at observable boundaries (the suite should survive an
implementation swap), prefer real implementations/fakes over interaction
mocks, and keep logic sans-I/O so the default suite stays fast. Deliberately
not adopted from the article: expect/snapshot testing as a default (invites
snapshot sprawl outside languages with strong tooling for it), the shared
`check`-function pattern, coverage marks, and its skepticism of TDD for
small-scale design (our TDD-first rule is workflow discipline, not design
methodology; the two coexist).

## Opting out of the git workflow rules

The branch, push, history, and branch-naming bullets in `conventions.md` sit between
`git-workflow` region markers. The commit-identity, short-hash and merge-status rules
sit after the end marker, so they load either way. A user whose own instructions already cover
those rules sets `DOT_CLAUDE_CONVENTIONS_SKIP_GIT=1` in the `env` block of their
`settings.json`; `scripts/inject-conventions.sh` then drops the region from both the
main-session and the subagent injection. Any other value, or unset, keeps it.

## Model map override

`DOT_CLAUDE_MODEL_MAP` holds a JSON remap for accounts missing an alias, e.g.
`{"fable":"opus"}`. Apply it to every `model:` you pass; the review workflows
take it as `modelMap`. A reasoning or escalation role never drops to `sonnet`.

## Delegation hooks

`context-watch` (PostToolUse) reports context use at fixed bands and says what
to do at each: finish the step and delegate the rest, or estimate the remaining
cost from what the same kind of step cost earlier and respawn only when it
clearly does not fit.

Both read the budget cap and bands from `context-budget.json` (300k, bands
60/85/100); the dot-files status line reads the same file.

`delegation-gate` (PreToolUse on Read and Grep) applies from the first band: after
3 bulk round-trips in one main-loop turn (1 past the last band) it denies
further bulk reads. Bulk means Read without offset+limit (or a limit over 250
lines) and Grep content mode without head_limit. Bash is not gated, since
Claude Code truncates its output, and subagents are never gated. Set
`DELEGATION_GATE=off` for a session that legitimately needs deep inline reading.
