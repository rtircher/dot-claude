# Delegating adversarial review to the Workflow

**Delegate adversarial review to this plugin's Workflow when the Workflow tool
is available.** Where the phases in SKILL.md say "the `adversarial-review` skill",
dispatch `dev:gated-review` instead (`dev:review-workflow` for a single advisory
pass): it runs the review/fix/re-review loop to the confidence cap in SKILL.md (*Confidence gates*) and
returns one consolidated result, which suits the thin coordinator. Invoking it
is the sanctioned opt-in. It runs headless and forwards its args unchanged into
`dev:review-workflow`, so build them up front exactly as the adversarial-review
skill's `full.md` steps 1 and 2 do (artifact pin, digest, focus files,
`skillScriptsDir`), loading focus per its router's *Load focus* section, since
no router runs here. Only three things are specific to this skill: append any
phase focus to that loaded focus; pass `requireExternal: true` when the
`external-review` argument was given; and, for a PR, ask the user to check out
its branch first, since gated review commits fixes. The ping contract stays with
this coordinator: read the returned findings and stop per SKILL.md's *The ping contract* section.
If the Workflow tool is unavailable, use the `adversarial-review` skill as
written.
