---
name: adversarial-review
description: Use when you want independent, adversarial review of a plan, spec/design doc, or PR/diff before committing to it — reviewers prompted to find what's wrong, not rubber-stamp. Triggers on "adversarial review", "independent review", "poke holes in this", "red-team this plan/spec/PR", or when a plan/spec is finalized and about to become implementation.
---

# Adversarial Review

Run independent, skeptical reviewers against a plan, spec, or diff and return one
deduped, severity-ranked list of objections. Reviewers are told to find what is
**wrong** — not to approve. Advisory only: this skill never edits files and never
blocks.

## When this applies

- A plan, spec, or design doc is finalized and about to drive implementation.
- A PR / branch diff is ready and you want a hostile read before merge.
- The user explicitly asks to red-team / poke holes in / independently review an
  artifact.

If the user just wants a quick opinion, that's not this — this dispatches
multiple independent reviewers and costs tokens. Use it when the artifact
matters.

## Procedure

**The Claude lens panel always runs; a third-party model is only ever added on
top of it.** Every artifact type (spec, plan, and diff) gets its lens panel, and
it is never skipped, even when the user explicitly asks for external review.

Use the **Workflow path** (step 2) whenever the `Workflow` tool is available.
Use the **manual path** (steps 3 to 5) only when it is not (cloud sessions and
subagents have no Workflow tool) or when the workflow run itself errors, never
because the manual path feels quicker. Both paths run the same panel and end in
the same Output. `${CLAUDE_PLUGIN_ROOT}` below is the `dev` plugin root, two
levels above this skill's directory.

### 1. Identify and pin the artifact

Determine what is under review and its type: **spec** (a requirements or design
document), **plan** (an implementation plan: steps, sequencing, tasks), or
**diff** (code changes: a branch diff or GitHub PR).

An explicit artifact is required: a file path, a diff range like `main...HEAD`,
a branch, or a PR number or URL. The only allowed inference is a bare invocation on a branch with
one unambiguous diff against the trunk (use `<trunk>...HEAD`). Anything else: ask
which artifact, once, then proceed. Never infer by recency or pick the "most
recently written" spec or plan.

For a diff, prefer a COMMITTED range of the exact form `<ref>...HEAD` (Codex
reviews only that form; other shapes drop the Codex vote with a refusal), and pin
its SHA with `git rev-parse --short HEAD`. For an UNCOMMITTED working-tree diff,
warn that any write between digest and review (this session, an editor autosave,
a hook) will drop the external votes, and offer to commit or stash first.

A **GitHub PR number or URL** is a `diff`. Resolve it with
`gh pr view <num|url> --json number,headRefOid,headRefName,baseRefName,url`; a URL
for a repo other than this checkout means ask once (or use an obvious local clone
of it). If HEAD already equals `headRefOid`, review this checkout as is.
Otherwise never check out or switch branches in the user's tree (some machines'
hooks deny it): `git fetch origin <headRefOid>` (or `pull/<n>/head` if that
fails), `git fetch origin <baseRefName>`, then
`git worktree add --detach <scratch path> <headRefOid>`. Set `repoDir` to that
worktree, the range to `origin/<baseRefName>...HEAD`, and `pinnedSha` to
`headRefOid`; compute the digest below from inside it, and
`git worktree remove <scratch path>` once the review returns. Gated review
commits fixes, so it needs the PR branch checked out in the working tree: if HEAD
is not the PR head, ask the user to check it out with their own tooling (e.g.
`gt co`) rather than switching it yourself.

Compute the digest from the repo root. It pins the exact bytes every external
reviewer must have reviewed:

    expected="$(git diff main...HEAD | sha256sum | cut -d' ' -f1)"   # diff: the exact range
    expected="$(sha256sum "docs/plans/the-plan.md" | cut -d' ' -f1)" # spec/plan: the file

For an uncommitted diff, re-run it immediately before dispatch (this narrows the
pin-to-review window; a committed range has none). The digest goes only into the
Workflow args or your own comparison in step 4, NEVER into any prompt, agent
instruction, or chat text. A digest a courier or reviewer has seen proves nothing.

### 2. Workflow path

Dispatch the whole pass as `Workflow` with `name: "dev:review-workflow"` and args:

- `artifactType`; `artifactPath` for a spec/plan; `diffRange`, `pinnedSha`, and
  `repoDir` for a diff; `focus` / `outOfScope` when given.
- `expectedArtifactSha256`: the digest from step 1.
- `skillScriptsDir`: `"${CLAUDE_PLUGIN_ROOT}/skills/adversarial-review/scripts"`.
- `externalReview` defaults to **true**; pass `false` only on an explicit "no
  external" / "claude only" from the user. Consent (step 4) is the caller's job
  and comes BEFORE the dispatch; the workflow runs reviewers, it never asks.
- `requireExternal: true` when the user explicitly asked for external review, so
  a machine with none configured reports the shortfall instead of a quiet
  Claude-only panel.
- `externalReviewers`: the `names` printed by
  `"$(command -v node || bash -lc 'command -v node')" "${CLAUDE_PLUGIN_ROOT}/skills/adversarial-review/scripts/external-review.mjs" --list`,
  so each reviewer runs as its own `external:<name>` courier step. If the command
  fails, omit the arg: one `external` courier runs them all and reports the
  config error.
- `tiers`: normally omitted. `DEFAULT_TIERS` in
  `${CLAUDE_PLUGIN_ROOT}/workflows/adversarial-review.js` names every slot
  (mechanical lenses sonnet, reasoning lenses and the verify skeptics fable) and
  rejects any other alias; no slot inherits the session model. An override
  replaces one key (a lens key or `verify`; values `{model, effort}`) and needs a
  concrete reason about this artifact. Never downgrade the verify skeptics.

The workflow runs the lens panel, every configured external reviewer (couriers
pinned to sonnet at low effort), schema-validated findings, a skeptic verify pass
on uncorroborated blocker/major findings, and synthesis blind to model identity.
Present its result per the Output section. `/dev:review-panel` is a thin command
over this path.

### 3. Manual path: dispatch the lens panel

The lenses live in one place: `LENS_PANELS` in
`${CLAUDE_PLUGIN_ROOT}/workflows/adversarial-review.js`, with each lens's model in
`DEFAULT_TIERS` in the same file. Read the artifact type's panel there and use
each lens's `key` and `brief`. Each lens is a distinct failure mode, not a
redundant copy, and all of a type's lenses run.

Dispatch one `Agent` per lens, **all in a single message** so they run
concurrently with fresh, independent context, each as a read-only `dev:reviewer`
agent with `model:` from `DEFAULT_TIERS` for its key (never omitted, never
`opus`). Its definition carries the adversarial stance and the findings schema,
so the prompt needs only the artifact (the file path, or for a diff the range,
repo, and `git diff` command), its one lens `key` and `brief`, and any focus and
out-of-scope notes. Where `dev:reviewer` is unavailable, fall back to
`dev:researcher`, then general-purpose, and paste this framing and the schema
into the prompt:

> Your job is to find what is wrong with this artifact through the lens of
> {lens}: {brief}. Assume the author is over-confident. Surface real problems,
> not style nits. Be specific — point to the exact part. When you are uncertain
> whether something is a problem, flag it rather than letting it pass. End with
> a single verdict: ship or don't-ship, with one sentence why.

Findings are
`{ objection, severity (blocker | major | minor), confidence (verified | speculative), location, suggested_fix }`.
**verified** = the reviewer opened the artifact / traced the code and confirmed
it; **speculative** = inferred from a smell or a partial read. Every finding
carries a label: a confident-sounding hunch that was never checked is the
panel's main failure mode.

### 4. External reviewers (additive; consent and binding apply on both paths)

**Additive, never a replacement.** "Use external", or the `external-review`
flag, means **add** third-party reviewers to the Claude panel, not swap it out. A
different model family is the most independent reviewer you can add because it
shares none of Claude's blind spots; a missing or failing one never blocks the
Claude panel.

**Which reviewers run is per-machine config, never the plugin's.**
`EXTERNAL_REVIEWERS` (in the machine's `settings.json` env, typically its
dotfiles) is a JSON array and the complete list:

```json
"EXTERNAL_REVIEWERS": "[{\"name\":\"codex\",\"kind\":\"codex\"},{\"name\":\"qwen\",\"model\":\"qwen3.8:27b-q8_0\",\"baseUrl\":\"http://gpu-box:11434/v1\",\"private\":true},{\"name\":\"gpt\",\"model\":\"gpt-5\",\"baseUrl\":\"https://api.openai.com/v1\",\"apiKeyEnv\":\"OPENAI_API_KEY\"}]"
```

Entries are `{name?, kind?, model, baseUrl, apiKeyEnv?, private?, family?, serialize?}`.
`kind` is `openai-compatible` (default: the script calls the endpoint) or `codex`
(via `codex-review.mjs`; diffs of the form `<ref>...HEAD` only). Set
`"private": true` only on an endpoint running on hardware the user controls: no
API key, no consent stop. Loopback is always private; anything else is a hosted
vendor, which needs `apiKeyEnv` and consent. `"[]"` means none. When unset, the
legacy `EXTERNAL_REVIEW_MODEL` / `_BASE_URL` / `_API_KEY` vars count as one
entry, plus Codex if its companion is installed. The default is **all
configured** reviewers that apply to the artifact.

**Independence lives in the model family, not the harness.** Codex runs OpenAI
models, so it is always cross-family. An `openai-compatible` entry is only as
independent as the model it points at: a Claude model there is not a third-party
reviewer and never counts as cross-family corroboration (the script refuses
Claude-family models unless `--allow-same-family`). Record the *model family*
that ran, not the tool name, in the private source bookkeeping.

**One request per model host.** A self-hosted model server often has the memory
for one review at a time, so the script queues requests to each private endpoint
on a per-`host:port` lock shared by every process on the machine (`serialize`
overrides: on for private, off for hosted; Codex never queues). Queue time has
its own cap, `EXTERNAL_REVIEW_MAX_WAIT_MS` (default 240000), apart from the
per-request `EXTERNAL_REVIEW_TIMEOUT_MS` (default 300000); keep the two summed
under the 10-minute Bash cap. The lock sees only this machine, so still set
`OLLAMA_NUM_PARALLEL=1` (or the equivalent) on a shared model host.

**Get consent before any artifact leaves the environment.** A hosted reviewer
sends the diff or document to its provider (OpenAI for Codex, the `baseUrl`
vendor for an endpoint entry); name that destination, not the tool. Confirm with
the user first, especially for private repos, proprietary code, or diffs that may
carry secrets or tenant data, and offer to redact or skip. Without approval, run
the Claude panel only and report it as Claude-only. Never send an artifact to a
third party silently. A private or loopback entry sends nothing off the user's
hardware, so no consent stop; still report which model ran and that it was
local. Consent can come ahead of time: an orchestrator or invocation flag that
pre-authorized third-party review, or the user explicitly asking for external
review in this run, is the confirmation. Either way, report that each reviewer
ran and where the artifact went.

**Manual path: run the script.** `scripts/external-review.mjs` is the single
external entry point: it runs every selected entry in parallel (Codex via
`codex-review.mjs`), is read-only, refuses oversized artifacts rather than
truncating, and needs only `node` (>= 18). List the configured names, then run it
on the same bytes you hashed in step 1, with the Bash timeout at 600000 ms:

    node="$(command -v node || bash -lc 'command -v node')"
    s="${CLAUDE_PLUGIN_ROOT}/skills/adversarial-review/scripts/external-review.mjs"
    "$node" "$s" --list
    git diff main...HEAD | "$node" "$s" --type diff \
      --target "main...HEAD @ $(git rev-parse --short HEAD)" \
      --cwd "$(git rev-parse --show-toplevel)" --range main...HEAD

For a spec/plan, pipe `cat <file>` with `--type spec|plan --target "<path> @
<type>"` and no `--cwd`/`--range`. Pass `--focus` / `--out-of-scope` when the
panel has them, and `--only <name>` (repeatable) to run only the reviewers the
user consented to. The script prints
`{configured, artifactSha256, votes:[vote | {name, __error} | {name, skipped}]}`.
Count a vote only if its `artifactSha256` equals your `expected` digest and it
has a boolean `verdict.ship`, a `verdict.reason`, and findings with every schema
field. Anything else (an error, a skip such as Codex on a spec, a digest
mismatch, a malformed vote) is one dropped reviewer with its reason.
`configured: false` means none is configured.

**Bind every external run to the same artifact**: the same path or range in the
same repo, the same focus and out-of-scope notes, the pinned SHA. A vote counts
only on digest equality; one whose scope does not match the panel's is dropped,
never folded in as agreement.

**External review requested but no reviewer can run.** When the user asked for
external review and none could vote (none configured, tool missing,
unauthenticated, or errored), run the Claude panel as always and say loudly that
it is Claude-only; never quietly substitute a lower-friction reviewer or report
the ask as satisfied. Close with a one- or two-sentence setup hint, not a bare
"unavailable": point at `/dev:setup-local-reviewer`, whose appendix lists the
non-Claude model families, the cheapest route to each, and why a cloud session
should use a hosted key rather than a local model.

**Blind scoring.** Each counted external vote is one more independent reviewer.
Record which source raised each finding as private bookkeeping (to count
independent sources and detect cross-family agreement), but never carry model
identity into scoring. A lone finding from another family is exactly the blind
spot you enlisted it to catch, but *which* model said it must not move its rank:
naming a prestige source biases the synthesizer. The count and the
cross-family-ness are the signal, the brand name is not.

### 5. Manual path: synthesize

Strip model names first and work from anonymized handles (Reviewer A/B/C…) plus
each finding's lens. Re-attach names only after ranking is fixed, and only if the
user asks who said what. The reviewers are the lens panel plus every counted
external vote.

1. **Account for who actually voted.** State the panel that returned versus the
   panel you dispatched — e.g. "5 of 6 reviewers returned; external:qwen queued
   past max wait and was dropped." A failed reviewer is a missing *vote*, not a
   missing finding; never imply a fuller panel than weighed in.
2. **Dedup** overlapping objections into one entry, recording **how many
   independent reviewers** raised it and **whether they span model families**
   (cross-family agreement is the strongest signal; agreement across lenses
   within one model is weaker).
3. **Rank** by severity (blocker → major → minor), and within a severity put
   **verified before speculative**. Rank on merit and corroboration count, never
   on which model spoke.
4. Produce **one prioritized list**: each entry = objection · severity ·
   confidence · location · suggested fix · corroboration.
5. **Report each reviewer's verdict**: each lens's ship / don't-ship, and each
   external reviewer's. Never invent a verdict for a reviewer that gave none.

## Output

Present to the user:

- **The panel that actually voted**, up front: dispatched vs returned, and which
  reviewers were dropped and why. On the Workflow path, ALWAYS surface
  `external.ran`, `external.dropped` (each absent reviewer with its reason), and
  `external.shortfall` (external review was on, the machine configures external
  reviewers, and nothing external voted; it fires even on caller config drops, so
  a Claude-only degradation is never silent); on the manual path, report the same
  facts from your own fold. `external.configured: false` is a Claude-only panel,
  not a failure unless the user asked for external review; then append step 4's
  setup hint.
- The ranked objection list, verified findings first and speculative ones grouped
  after, each with its corroboration rather than model names.
- The verdicts: per lens, plus per external reviewer. Source attribution only on
  request.

Then stop. Do not edit the artifact, do not block any next step, do not
re-review. The user decides what to act on. If they ask you to address findings,
that's a separate task.

## Anti-patterns

- **Agreeable review.** If reviewers come back with "looks good, minor nits,"
  the framing was too soft. Reviewers must hunt for real problems.
- **Redundant lenses.** Three reviewers finding the same class of issue wastes
  the panel. Keep lenses distinct.
- **Sequential dispatch.** Reviewers must be independent — dispatch them in one
  message, never feed one reviewer's output to the next.
- **Phantom third-party review.** Never imply an external reviewer weighed in
  when it was unavailable, errored, or dropped; a vote without a matching digest
  and a well-formed verdict is dropped, never counted.
- **Same-family "third party".** An endpoint running a Claude model never counts
  as cross-family corroboration. Independence is the model family, not the tool.
- **Prestige-weighted scoring.** Score blind to model identity; the signal is
  corroboration count and cross-family agreement, not the brand name.
- **Third-party instead of the panel.** An external reviewer never substitutes
  for the Claude lens panel; "use external" means add it, not swap it. A run with
  only external findings skipped the panel and is wrong.
