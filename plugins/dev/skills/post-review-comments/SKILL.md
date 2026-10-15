---
name: post-review-comments
description: Post review findings as inline GitHub PR comments that land on the right lines (SHA-pinned anchors, one comment per finding, verified via diff_hunk), each tagged [required], [optional], or [follow-up], with optional ones capped at 5. Use when the user says "post these comments", "post the review", or "post inline comments on the PR", after any review (adversarial-review, a manual read, or another review skill). Posts only on an explicit ask.
---

# Posting review comments

Reference for turning a finding list into inline GitHub review comments that land on the
**right lines**. Used after `adversarial-review` (either tier) or any other review whose findings the user asks to post. Work-agnostic (any GitHub repo).

## Why this exists

Naive posting misplaces comments. Two independent traps, both observed in production
(7 of 11 comments landed on wrong or blank lines in one review):

1. **The batch reviews endpoint anchors by diff `position`, not file line.** `POST
   /repos/{o}/{r}/pulls/{n}/reviews` with `comments[].line` is unreliable, it can be
   interpreted as a diff-position offset, so comments drift or land on blank `+` lines.
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
| `[optional]` | Their call, no reply needed | A verified minor on changed code, a Simplify `cut now` item, or a non-blocking question (body opens with "Question:") |
| `[follow-up]` | Not this PR; a ticket or a "no" is enough | Code the PR does not change, work beyond the PR's goal, a Simplify `follow-up` item |

A blocker or major is `[required]` only when it is verified and no skeptic contested it.
Confirm a speculative, contested, or `unverified (single reviewer, manual path)` one against
the code at the pinned SHA first; if you cannot, post it as an `[optional]` question.

## What gets posted

Every `[required]` and `[follow-up]` posts. At most **5** `[optional]` post, taken in the
review's rank order; the rest are **held**. Never posted:

- a speculative minor;
- a trade-off or gap the PR description already discloses, unless the finding shows the
  disclosure is wrong or understates the risk;
- a preference with no consequence.

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
have no resolved state to track, an issue-comment review was observed being silently skipped
while every inline comment on the same PR got fixed. A finding with no single obvious line
still goes inline, anchored on the most load-bearing line in the diff (the mock definition,
the import line, the function signature).

## The procedure

**1. Pin the head SHA first, and re-pin if the branch moves.**
```bash
gh pr view <n> --json headRefOid -q .headRefOid
```
The branch can advance mid-review (multiple pushes). Compute all anchors against ONE sha
and pass it as `commit_id`; a comment pinned to a sha stays correctly anchored even if a
newer push arrives (GitHub marks it outdated, not misplaced).

**2. Get line numbers from the real file content at that sha, never from `gh pr diff`.**
`<remote>` is the git remote whose URL matches the PR's repo, per the router (`SKILL.md`), never an assumed `origin`.
```bash
git fetch -q <remote> <sha>
git show <sha>:<path> | grep -nE '<pattern for the line>'
```
`git show <sha>:<file>` is authoritative: its line numbers ARE the file lines GitHub's
`line` parameter expects. Match on the code text, not a remembered number.

**3. Post each comment individually with `line` + `side`, not the batch endpoint.**
```bash
gh api repos/{o}/{r}/pulls/<n>/comments --method POST --input - <<payload-via-file>
# body: {commit_id, path, line, side:"RIGHT", body}
```
The individual `/pulls/{n}/comments` endpoint uses file-line semantics reliably. Build the
JSON with a file + `--input` (no heredoc). `side:"RIGHT"` is the new version; use `"LEFT"`
only to comment on a deleted line.

**4. Verify EVERY comment via `diff_hunk` before trusting it.** The last line of a
comment's `diff_hunk` is the line it actually attached to:
```bash
gh api "repos/{o}/{r}/pulls/<n>/comments?per_page=100" \
  -q '.[] | select(.user.login=="<me>") | "\(.path):\(.line)\t\((.diff_hunk|split("\n")|last)[0:60])"'
```
If the anchor line doesn't contain the code you meant, the comment is misplaced, delete
and repost. A comment on a blank `+` line is always wrong.

## Grouping vs individual comments

- **One combined review** (summary + inline comments, submitted as `event: COMMENT`) reads
  best, but the batch endpoint is the fragile one. If you use it, verify all anchors and be
  ready to fix, see the trade-off below.
- **Individual comments** are anchor-reliable but appear ungrouped. Prefer these when
  correctness matters more than tidiness.
- A **submitted** review cannot be deleted (only *pending* ones can). If a submitted review
  has misplaced comments, delete the individual bad comments
  (`DELETE /pulls/comments/{id}`) and repost them via step 3, you cannot re-add them to the
  already-submitted review, so they become standalone. Anchors correct beats grouping tidy.

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
