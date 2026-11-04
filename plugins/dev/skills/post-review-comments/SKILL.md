---
name: post-review-comments
description: Post review findings as inline GitHub PR comments that land on the right lines (SHA-pinned anchors, one comment per finding, verified via diff_hunk), each tagged [required], [optional], or [follow-up], with optional ones capped at 5 per PR across rounds. Use when the user says "post these comments", "post the review", or "post inline comments on the PR", after any review (adversarial-review, a manual read, or another review skill). Posts only on an explicit ask.
---

# Posting review comments

Reference for turning a finding list into inline GitHub review comments that land on the
**right lines**. Used after `adversarial-review` (either tier) or any other review whose findings the user asks to post. Work-agnostic (any GitHub repo).

## Why this exists

Naive posting misplaces comments, for two independent reasons:

1. **A comment without `commit_id` and `side` anchors by diff `position`.** Without them,
   `comments[].line` can be read as a diff-position offset, so comments drift or land on
   blank `+` lines. With `commit_id`, `line` and `side`, the batch reviews endpoint anchors
   as reliably as the single-comment one.
2. **Line numbers parsed from `gh pr diff` drift by 1 to 3 lines** vs the actual file. The
   `+N` hunk arithmetic is easy to miscount (context lines, `@@` bases), and the drift is
   silent, the comment still posts, just on the wrong line.

## Tags

Every posted comment opens with one tag that tells the author what to do. Severity words
(blocker, major, minor), lens names, confidence labels, and reviewer or model names never
appear in the body; after the tag comes the problem, why it matters, and the fix.

| Tag | Author's move | Findings |
|---|---|---|
| `[required]` | Fix before merge | A blocker or major on code this PR adds or changes |
| `[optional]` | Their call, no reply needed | A verified minor on changed code, a Simplify `cut now` item, a non-blocking question (body opens with "Question:"), or a Prose entry on a comment, docstring, or doc line (ranked after all the others; one on the PR description or a commit message has no diff line and is never posted) |
| `[follow-up]` | Not this PR; a ticket or a "no" is enough | Code the PR does not change, work beyond the PR's goal, a Simplify `follow-up` item |

A blocker or major is `[required]` only when it is verified and no skeptic contested it.
**Test findings: critical ones inline, the rest as one comment.** A test that cannot fail on
the PR's core behaviour, or a missing test on a path that can break in production, posts
inline on its line as its own `[required]`. Every other test-quality finding (structure, a
missing edge case, a test that repeats another, a fixture that hides the code under test)
goes into a single `[required]` comment on the first changed line of the main test file,
one bullet per finding with its `file:line`. On a re-review, only test findings on lines
changed since the last round go in, as a new comment that links the earlier one.

## What gets posted

Every `[required]` and `[follow-up]` posts. At most **5** `[optional]` post per PR, across
all rounds, taken in the review's rank order; the rest are **held**. Never posted:

- a speculative minor;
- a trade-off or gap the PR description already discloses, unless the finding shows the
  disclosure is wrong or understates the risk;
- a preference with no consequence;
- a nitpick: naming, style, wording, a duplicated constant or helper, an assert that could
  be stronger. An `[optional]` posts only when it shows a real risk: a bug, or a missing
  test on a path that can break in production.

**A re-review posts less.** Before building the plan, list the top-level inline comments
this account already left on the PR (`gh api repos/{o}/{r}/pulls/{n}/comments --paginate`,
your login, `in_reply_to_id` null). If there are any, this round is a re-review:

- A finding already raised, resolved or not, is never posted again in new words. When the
  fix for it is wrong, post that as a new `[required]` that links the earlier comment.
- `[required]` posts when not already raised.
- `[optional]` and `[follow-up]` post only on lines changed since the previous round, and
  `[optional]` only while slots remain: 5 minus the `[optional]` comments already on the PR.
  The rest are held.

Name the reason in the plan line: `held: #7 (PR optional cap)`, `held: #8 (unchanged since
last round)`, `not posted: #3 (raised earlier)`.

Number every finding `#1..#n` (the review's numbering when it has one) and write one plan
line:

    post plan: [required] #1, #2 · [follow-up] #6 · [optional] #3, #4, #5, #7, #9 · held: #10, #11 · not posted: #8 (disclosed in PR description), #12 (speculative)

`dev:adversarial-review` prints this line with its findings, so "post" posts the plan as
shown; "post + #10" adds a held or skipped finding, "post - #4" drops one. The plan line is
the only prompt: never ask about findings one by one. After a review that printed no plan (a
manual read, another review skill), build the plan, post it, and report the line so the user
can add held findings.

## Inline only, no issue-level comments

Every posted finding is an **inline review comment** (file + line). Never post findings as a
top-level/issue PR comment: authors' fix workflows key off review threads, and issue comments
have no resolved state to track. A finding with no single obvious line
still goes inline, anchored on the most load-bearing line in the diff (the mock definition,
the import line, the function signature).

## The procedure

Post a round's comments as **one review** with `scripts/post-review.sh` (beside this file):
one notification for the author instead of one per comment. Write each body, tag first, to a
file, list them in a plan file (`[{path, pattern, body_file, side?}]`), then run from a clone
of the PR's repo:

```bash
post-review.sh --pr <n> --remote <remote> --plan <plan.json> --summary-file <file> [--sha <sha>]
```

It locates every line the way `post-comment.sh` does, stages the comments as a pending
review (visible only to you), checks each comment's `diff_hunk`, then submits the review as
`COMMENT`. If any comment landed on the wrong line, it deletes the pending review, prints
where each landed and exits 3: fix the pattern and rerun. It refuses to start while you have
another pending review on the PR (see Pending-review collision).

Use `scripts/post-comment.sh` for a single comment, or to repost one bad comment of a
submitted review:

```bash
post-comment.sh --pr <n> --remote <remote> --path <file> --pattern '<ERE for the line>' \
  --body-file <file> [--sha <sha>]
```

`<remote>` is the git remote whose URL matches the PR's repo, never an assumed `origin`. The
script runs the fixed sequence:

1. **Pin the head SHA.** The branch can advance mid-review, so pass the SHA the first call
   printed as `--sha` on the rest to anchor every comment of one review to the same commit.
   A comment pinned to a SHA stays anchored when a newer push arrives (GitHub marks it
   outdated, not misplaced).
2. **Locate the line** in `git show <sha>:<path>`, matching the code text with `--pattern`
   (it must match exactly one line). That file's line numbers are what GitHub's `line`
   parameter expects; never use line numbers from `gh pr diff`.
3. **Post** to the single-comment endpoint `/pulls/{n}/comments` with `line` and
   `side: RIGHT`. For a comment on a deleted line, make the same
   `gh api` call by hand with `side: LEFT` and the old-file line.
4. **Verify** via the last line of the comment's `diff_hunk`, which is the line it attached
   to. Exit 3 means it landed elsewhere: the script prints the delete command; delete and
   repost. A comment on a blank `+` line is always wrong.

`--dry-run` prints the `gh api` call and checks, read-only, that the located line sits
inside a diff hunk of the PR, without posting.

## Grouping vs individual comments

- **One review per round** is the default: `post-review.sh`. Its pending-stage check means
  a misplaced comment never reaches the author.
- **Individual comments** (`post-comment.sh`) are for a single finding, or a fix to a
  submitted review.
- A **submitted** review cannot be deleted (only *pending* ones can). If a submitted review
  has a misplaced comment, delete that comment (`DELETE /pulls/comments/{id}`) and repost it
  with `post-comment.sh`; it becomes standalone.

## Pending-review collision

Only one pending review per user per PR. Before staging a new review, check for an existing
pending one, it may be a **human draft you didn't create**:
```bash
gh api repos/{o}/{r}/pulls/<n>/reviews -q '.[] | select(.user.login=="<me>" and .state=="PENDING") | .id'
```
If found, inspect its comments before touching it. Never delete a draft you didn't author
without the human's say-so, surface it and let them choose (fold in / they submit first /
delete).

## Consent

Posting to a PR writes to an external service. Post only when the human explicitly asked you
to post (not merely "review it" / "draft comments"). "Draft" means output to chat; "post"
means write to GitHub.
