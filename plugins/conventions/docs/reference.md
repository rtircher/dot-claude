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

## Green-tests commit gate mechanics

A repo opts in by committing a `.claude/require-green-tests` file at its root
containing its canonical full-suite command (e.g. `make test`). In opted-in
repos, a PreToolUse hook denies `git commit` unless the current worktree
matches the fingerprint recorded at the last green run. Record a run by
executing the suite through the conventions plugin's
`scripts/record-green.sh <command>` from the repo root. Staging changes never
invalidates a recorded run; editing any file does.

## Testing-rule sources

The "Test observable behavior at the boundary" rule distills matklad's
"How to Test" (https://matklad.github.io/2021/05/31/how-to-test.html):
test features at observable boundaries (the suite should survive an
implementation swap), prefer real implementations/fakes over interaction
mocks, and keep logic sans-I/O so the default suite stays fast. Deliberately
not adopted from the article: expect/snapshot testing as a default (invites
snapshot sprawl outside languages with strong tooling for it), the shared
`check`-function pattern, coverage marks, and its skepticism of TDD for
small-scale design (our TDD-first rule is workflow discipline, not design
methodology; the two coexist).

## mise in cloud setup scripts

`mise.run` and the mise CDN are NOT on the Claude-Code-web Trusted allowlist,
but `github.com` and `nodejs.org` are. In a cloud setup script, install mise
from a pinned GitHub release tarball, not the `curl https://mise.run | sh`
one-liner.
