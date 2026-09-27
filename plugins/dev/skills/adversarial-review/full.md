# Full tier

The router (`SKILL.md`) has already resolved the input, loaded focus, and picked
this tier; this procedure runs the full panel from there.

## Procedure

**The Claude lens panel always runs; a third-party model is only ever added on
top of it.** Every artifact type (spec, plan, and diff) gets its lens panel, and
it is never skipped, even when the user explicitly asks for external review.

Use the **Workflow path** (step 2) whenever the `Workflow` tool is available.
Use the **manual path** (steps 3 to 5) only when it is not (cloud sessions have
no Workflow tool) or when the workflow run itself errors, never because the
manual path feels quicker. The manual path needs the `Agent` tool. If neither
`Workflow` nor `Agent` is available (as in `dev:coder`, `dev:reviewer`,
`dev:researcher` subagents), do not attempt a single-pass substitute review: stop
and tell the caller, naming the artifact, that the review must run from the main
session (or `/dev:review-panel` there). Both paths run the same panel and end in
the same Output. `<plugin>` below is the `dev` plugin root: two levels above this
skill's base directory (shown when the skill loads). Substitute its absolute path
into commands; `${CLAUDE_PLUGIN_ROOT}` may be unset when this loads as a skill.

### 1. Pin the artifact

The router has already resolved the artifact (spec, plan, or diff) and, for a
PR, run `gh pr view`. A PR URL for a repo other than the one in cwd: a caller
that invokes this skill with `unattended: true` (no user to answer) fails
closed with a clear error; otherwise ask once (or use an obvious local clone
of it).

For a diff, settle `<repoDir>` (absolute; the repo toplevel for a local diff)
and `<range>`: every git command below runs as `git -C <repoDir> ...`, since the
Bash cwd resets between calls. Prefer a COMMITTED range of the exact form
`<ref>...HEAD` (Codex reviews only that form; other shapes drop the Codex vote
with a refusal), and pin `pinnedSha` with `git -C <repoDir> rev-parse --short
HEAD`. For an UNCOMMITTED working-tree diff, warn that any write between digest
and review (this session, an editor autosave, a hook) will drop the external
votes, and offer to commit or stash first.

For a **GitHub PR**, `<remote>` is the `git remote` whose URL matches the PR's
repo, not an assumed `origin`. Always `git fetch <remote> <baseRefName>` and set
`<range>` to `<remote>/<baseRefName>...HEAD` and `pinnedSha` to `headRefOid`. If
HEAD already equals `headRefOid`, `<repoDir>` is this checkout. Otherwise never
check out or switch branches in the user's tree (some machines' hooks deny it):
`git fetch <remote> <headRefOid>` (`pull/<n>/head` for a fork head or if that
fails), then `git worktree add --detach <tmp> <headRefOid>` with `<tmp>` outside
the repo (the session scratchpad or `mktemp -d`), and `<repoDir>` is `<tmp>`. A
branch that is not checked out works the same way (a detached worktree at its
tip, `<range>` = `<trunk>...HEAD`), or ask. Run `git worktree remove --force
<tmp>` on every exit path: after the review returns, after a workflow error only
once the manual fallback finishes, and on abort. Gated review commits fixes, so
it needs the PR branch checked out in the working tree: if HEAD is not the PR
head, ask the user to check it out with their own tooling (e.g. `gt co`) rather
than switching it yourself.

Compute the digest, the hex before the space in the output (`shasum -a 256`
where `sha256sum` is missing). It pins the exact bytes every external reviewer
must have reviewed:

    git -C <repoDir> diff <range> | sha256sum      # diff
    sha256sum <absolute path to the file>           # spec/plan

For an uncommitted diff, re-run it immediately before dispatch (this narrows the
pin-to-review window; a committed range has none). The digest goes only into the
Workflow args or your own comparison in step 4, NEVER into any prompt, agent
instruction, or chat text. A digest a courier or reviewer has seen proves nothing.

### 2. Workflow path

Dispatch the whole pass as `Workflow` with `name: "dev:review-workflow"` and args:

- `artifactType`; `artifactPath` for a spec/plan; `diffRange`, `pinnedSha`, and
  `repoDir` for a diff (`diffRange` = `<range>`); `focus` / `outOfScope` when given.
- `focusFile` / `outOfScopeFile`: only when `focus` / `outOfScope` is
  non-empty, write that text to `<scratchpad>/review-focus.md` /
  `review-oos.md` (the session scratchpad, else `mktemp -d`) and pass its
  absolute path, alongside the `focus` / `outOfScope` text above; the courier
  passes the path to `external-review.mjs`. Never write or pass a `*File` arg
  for an empty text arg: the workflow throws on a file without matching text.
- `expectedArtifactSha256`: the digest from step 1.
- `skillScriptsDir`: `<plugin>/skills/adversarial-review/scripts`, absolute.
- `externalReview` defaults to **true**; pass `false` only on an explicit "no
  external" / "claude only" from the user. Consent (step 4) is the caller's job
  and comes BEFORE the dispatch; the workflow runs reviewers, it never asks.
- `requireExternal: true` when the user explicitly asked for external review, so
  a machine with none configured reports the shortfall instead of a quiet
  Claude-only panel.
- `externalReviewers`: the `names` printed by
  `node <plugin>/skills/adversarial-review/scripts/external-review.mjs --list`,
  so each reviewer runs as its own `external:<name>` courier step. If the command
  fails, omit the arg: one `external` courier runs them all and reports the
  config error.
- `tiers`: normally omitted. `DEFAULT_TIERS` in
  `<plugin>/workflows/adversarial-review.js` names every slot
  (mechanical lenses sonnet, reasoning lenses and the verify skeptics fable) and
  accepts only `fable`/`opus`/`sonnet`; no slot inherits the session model. An override
  replaces one key (a lens key or `verify`; values `{model, effort}`) and needs a
  concrete reason about this artifact. Never downgrade the verify skeptics.

The workflow runs the lens panel, every configured external reviewer (couriers
pinned to sonnet at low effort), schema-validated findings, a skeptic verify pass
on uncorroborated blocker/major findings, and synthesis blind to model identity.
Present its result per the Output section. `/dev:review-panel` is a thin command
over this path.

**Extra lens.** When the loaded focus declares `Extra lens: <skill>`, run one
direct agent alongside the Workflow (or the manual panel), the way a declared
extra lens always ran alongside the panel: agent type, model, and tools per
the declared skill's Dispatch section (e.g. a lens that writes model files
needs a writing agent); default to `dev:reviewer` with `model: "sonnet"` only
when the skill names none. This overrides any same-message instruction in the
skill's Dispatch section. Dispatch from that skill's gate and prompt template
at `~/.claude/skills/<name>/SKILL.md`, with `repoDir` set to `<repoDir>` from
step 1. The main session applies the skill's gate before dispatch, as in the
quick tier. If that path does not exist, print `extra lens: <name>: not_run
(skill not found)`. Either way, print the mandatory `extra lens:` line (see
Output).

### 3. Manual path: dispatch the lens panel

The lenses live in one place: `LENS_PANELS` in
`<plugin>/workflows/adversarial-review.js`, with each lens's model in
`DEFAULT_TIERS` in the same file. Read the artifact type's panel there and use
each lens's `key` and `brief`. Each lens is a distinct failure mode, not a
redundant copy, and all of a type's lenses run.

Dispatch one `Agent` per lens, **all in a single message** so they run
concurrently with fresh, independent context, each as a read-only `dev:reviewer`
agent with `model:` from `DEFAULT_TIERS` for its key (never omitted, never
inherited from the opus session). Its definition carries the adversarial stance and the findings schema,
so the prompt needs only the artifact (the file path, or for a diff: run
`git -C <repoDir> diff <range>` and read files by absolute path under
`<repoDir>`), its one lens `key` and `brief`, and any focus and
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

    node <plugin>/skills/adversarial-review/scripts/external-review.mjs --list
    git -C <repoDir> diff <range> | node <plugin>/skills/adversarial-review/scripts/external-review.mjs --type diff --target "<range> @ <pinnedSha>" --cwd <repoDir> --range <range>

For a spec/plan, pipe `cat <absolute path>` with `--type spec|plan --target
"<path> @ <type>"` and no `--cwd`/`--range`. Pass `--focus-file` /
`--out-of-scope-file`, only when the corresponding text is non-empty, with the
same focus/out-of-scope files the Workflow path writes to the scratchpad
(never pass either flag pointing at an empty file), and `--only <name>`
(repeatable) to run only the reviewers the user consented to. The script prints
`{configured, artifactSha256, votes:[vote | {name, __error} | {name, skipped}]}`.
Count a vote only if its `artifactSha256` equals your `expected` digest and it
has a boolean `verdict.ship`, a `verdict.reason`, and findings with every schema
field. Anything else (an error, a skip such as Codex on a spec, a digest
mismatch, a malformed vote) is one dropped reviewer with its reason.
`configured: false` means none is configured.

**Bind every external run to the same artifact**: the same path or range in the
same repo and the pinned SHA (and, on the manual path, the same focus and
out-of-scope notes). A vote counts
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
   confidence · location · suggested fix · corroboration. Mark every blocker or
   major raised by only one reviewer `unverified (single reviewer, manual path)`:
   the Workflow path sends exactly these to skeptics, and the manual path skips
   that pass to bound agent spend, so callers must weigh them as unverified.
5. **Report each reviewer's verdict**: each lens's ship / don't-ship, and each
   external reviewer's. Never invent a verdict for a reviewer that gave none.

## Output

Present per the router's output contract (`SKILL.md`), full-tier lines. Item 2
(the panel line) carries this full-tier detail: on the Workflow path, ALWAYS
surface `external.ran`, `external.dropped` (each absent reviewer with its
reason), and `external.shortfall` (external review was on, the machine
configures external reviewers, and nothing external voted; it fires even on
caller config drops, so a Claude-only degradation is never silent); on the
manual path, report the same facts from your own fold. `external.configured:
false` is a Claude-only panel, not a failure unless the user asked for
external review; then append step 4's setup hint. Item 3 is the mandatory
extra-lens line above. The step 5 `unverified (single reviewer, manual path)`
mark feeds the contract's punch list on the manual path.

Then stop. Do not edit the artifact, do not block any next step, do not
re-review. The user decides what to act on. If they ask you to address findings,
that's a separate task.
