# Third-party review (`external-review` argument)

The adversarial-review phases inherit external-on by default from
`dev:review-workflow`: every available, applicable cross-family reviewer
runs alongside the Claude panel without a per-phase consent stop. The local
endpoint reviewer always runs (nothing leaves the machine, no consent needed);
Codex runs under the user's standing CLAUDE.md consent for their own explicit
requests, and an autonomous-feature invocation is itself user-initiated, so it
counts. A code diff (Phase 6) is the strongest case for a different model
family.

The `external-review` argument is therefore **force/confirm**, not an enable
switch: `/dev:autonomous-feature external-review` (or `/dev:autonomous-feature pause
external-review`) demands that external reviewers actually ran while the pinned
digest was fresh. It is SATISFIED BY ROUND-1 external participation: round 1
runs against the digest-fresh artifact, and once a fix pass mutates the
artifact the once-pinned digest is stale by design, so rounds 2+ dropping
external votes on digest mismatch is the documented degradation, reported but
never pinged. A round-1 `external.shortfall` in a forced run IS ping-worthy.
