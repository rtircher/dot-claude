Historical: written when this plugin was called `board`; it is now `quests`.

# `board` plugin: a shared, repo-local ticket board for Claude Code sessions

Status: draft for review · 2026-10-18

## Intent

One repo often has several Claude Code sessions open at once, each in its own git
worktree. Work fans out by yak-shaving: a session on task A hits side quest B, which
leads to C. Today that goes wrong in three ways:

1. **Side quests get lost.** The user already flags them in plain words ("park it
   for now", "side note to add to the next steps", "add a follow-up task", "flag it to
   the new session", "btw…"), but the flag lands in that one session's notes or a
   runbook on that session's branch, where no other session sees it. After an
   interruption the original task is forgotten.
2. **Sessions redo or re-check each other's work.** Each worktree has its own copy of
   the docs, so a checklist ticked in one branch is invisible to the others until it
   merges.
3. **"Where are we?" has no quick answer.** The user often asks "what's next?" and
   "where are we with task X / the project?" and has to read markdown files to find
   out. Those files are good records but hard to read at a glance.

The `board` plugin gives each repo one small ticket board that **every session of
that repo sees live**. Sessions read it at startup, claim the tickets they work on,
file side quests to it, and record findings on it. A pane in the Claude desktop app
shows the board at a glance.

## Goals

- One board per repo, shared live by every session and worktree of that repo.
- Visible at a glance in the desktop app's Code tab: project progress, what each
  session is on (including its side-quest chain), and what's next.
- Side quests captured as linked tickets without the user changing how they talk.
- Sessions check the board before starting work and don't duplicate claimed work.
- Tickets link to the markdown docs that hold the detail (runbooks, ADRs, plans)
  instead of copying them.
- Board history is kept (versioned), but never mixes into feature branches or PRs.
- Works in any repo, in local and cloud sessions alike (full read/write in both);
  ships in the public `dot-claude` repo.

## Non-goals

- Not a general project manager: no assignees beyond sessions, no due dates,
  estimates, sprints, or priorities beyond order.
- Not a replacement for runbooks, ADRs, or plans. Those stay as they are; the board
  points at them.
- No sync to GitHub Issues, Linear, etc.
- No migration of every existing `- [ ]` checklist into tickets. Seeding goals from
  existing plans is a one-off, user-approved step.

## Anti-goals (failure even if it technically works)

- **A noisy board.** If Claude files tickets on its own guesses, the board fills with
  junk and stops being glanceable. Claude never files silently on inference.
- **Branch churn.** Board writes must never show up as changes on the session's
  working branch or in its PRs.
- **A stale board.** Tickets claimed by sessions that died, or "in progress" for
  days, make the board lie. Stale claims must surface, not hide.
- **Leaking private data into the public repo.** The plugin repo contains no
  personal paths, hostnames, IPs, or real board content. Examples are generic.

## Prior art considered

- **Claude Code native Tasks** (`TaskCreate`/`TaskUpdate`, `owner`, `blockedBy`,
  `CLAUDE_CODE_TASK_LIST_ID`): the data model is right and this design borrows it.
  It is not used as storage because it lives outside the repo, has no links to docs,
  no goal/progress notion, and in the desktop Code tab the app replaces the task
  tools with its own per-turn checklist.
- **Backlog.md**: closest storage match (one markdown file per task in the repo, MCP
  server, kanban views) but committed on the working branch (drifts per worktree), no
  session awareness, and its board is a browser/TUI, not the Code tab.
- **Beads**: good "discovered while doing X" capture, but database storage, no UI.
- **claude-code-kanban** and similar: live browser viewers of native Tasks; not
  repo-local.

None covers live-shared-across-worktrees + session-aware + side-quest capture + a
Code-tab pane, which is the gap this fills.

## Decisions made with the user

### Storage: a dedicated board branch, checked out once, shared by all worktrees

- Each repo's board lives on an **orphan branch** (no shared history with the code;
  named `claude/board`, see designer calls).
- Locally it is checked out as **one extra git worktree at a fixed path** derived
  from the repo's common git dir, so every worktree of that repo resolves the same
  directory. All local sessions read and write that one checkout, so changes are
  visible immediately.
- Every board change is **committed on the board branch**, giving history without
  touching any feature branch.

### Location choice at setup: same repo or an external repo

- When a board is first set up for a repo, the user chooses where it lives:
  - **Same repo** (default): the orphan branch in the code repo's own remote.
  - **External repo**: the board branch lives in a separate git repo the user names
    (for example a private "boards" repo), because they may not want board content
    pushed to a shared code repo. One external repo can hold boards for several code
    repos (one branch per code repo, or one directory per code repo; builder's call).
- The choice is recorded in a small config the plugin can find from any worktree and
  from a cloud session. Where that pointer lives is the
  builder's call, but it must not require committing anything to the code repo's
  working branches, and a cloud session for the code repo must be able to discover
  it (e.g. a per-user plugin setting keyed by the code repo's remote URL).

### Sync: full read/write sync, including cloud sessions

The user works from cloud sessions often (especially on the go), so cloud sessions
are full participants: they read, claim, file and update tickets like local ones.

- **Before every change: fetch and rebase** the board branch onto its remote.
- **After every change: commit and push** immediately.
- If the push is rejected because another writer got there first, fetch, rebase and
  retry. Ticket data must be laid out so concurrent edits to different tickets
  rebase cleanly; a true conflict on the same ticket is resolved by re-applying the
  change on top of the latest version (the change is an operation like "append note"
  or "set status", not a file overwrite), never by dropping either side.
- **Offline / no remote reachable:** the change is committed locally and the push is
  retried on the next board operation; the startup summary says the board is
  unsynced so the user knows.
- Cloud sessions get the board by fetching the board branch (same repo or external
  repo) at `SessionStart`. If the external repo isn't reachable from the cloud
  environment (no credentials), the summary says so plainly instead of failing
  silently.
- Pushing makes board content (ticket titles, notes) visible to anyone with access
  to that remote. Setup states this when the user picks the location.

### Data model (borrowed from native Tasks, plus goals and links)

- **Goal**: a top-level outcome with a progress bar (e.g. "Services box", "Cameras",
  "Backups"). Has a title, optional link(s) to its plan/runbook doc, and an order.
- **Ticket**: title, status (`todo` · `in_progress` · `blocked` · `done` ·
  `dropped`), goal (optional), parent ticket (for side quests: "found while doing
  X"), `blockedBy`, owner (the claiming session), links (paths/anchors in the code
  repo, URLs), and a short append-only log of notes/findings with timestamps and the
  session that wrote them.
- Progress for a goal = done tickets / non-dropped tickets in that goal.

### Glance pane (approved layout: "A with B's session grouping")

A narrow pane in the desktop Code tab, top to bottom:

1. **Project** header with one progress bar per goal (`done/total`).
2. **In progress, grouped by session**: one block per session showing its
   side-quest chain (task › side quest › current), and the session state (active,
   idle for N, waiting on you). The session currently being viewed is listed first.
3. **Next up**: unclaimed, unblocked tickets in order, first few, "+N more".

Assumed interactions the user accepted: click a session name to jump to it; click a
ticket to open its detail (notes, links, history); click a goal to expand its
remaining tickets.

A **full board view** (generated HTML page: all goals, the side-quest tree, done
items, notes) is also produced from the same data for when the user wants to read
everything rather than glance.

### Session behaviour

- **Startup:** a `SessionStart` hook injects a short board summary (goals with
  progress, who holds what, next unclaimed items, and any stale claims) so sessions
  check the board without relying on Claude remembering to.
- **Claiming:** a session claims a ticket before starting it. If another live session
  holds it, the session says so instead of starting over. Claims are released on
  done/park, and go stale when the owning session ends or is idle past a threshold;
  stale claims are shown as such and can be taken over.
- **Findings:** facts worth keeping ("checked X, it's fine", "root cause was Y") are
  appended to the ticket's log so other sessions don't re-check.
- **Side-quest capture** (chosen from the user's actual prompt history):
  - The user's own cues file a ticket automatically, no special command: "park",
    "later", "side note", "follow up", "flag it", and similar. Claude files it,
    links it to the current ticket as parent, and confirms in one line.
  - A "btw" question gets answered first; if the answer turns into work, Claude
    offers a ticket in one line.
  - When Claude notices the session drifting off its ticket with no cue from the
    user, it asks in one line ("This looks like a side quest off X; ticket it and
    keep going?"). It never files silently on inference.
  - "What's next?" is answered from the board, not from whichever doc the session
    happened to read.
- **Goal seeding:** the first time a repo uses the board, Claude proposes goals from
  existing plans/runbooks; the user approves them. Those docs are linked from the
  goal, not copied.

### Packaging

- Everything ships as a new plugin `plugins/board/` in the public `dot-claude` repo:
  the board tool, hooks, skill/instructions for session behaviour, and the
  desktop-app pane (mod).
- The repo must stay clean for public use: no personal paths, hostnames, IPs,
  account names, or real board data in code, tests, fixtures, or docs. Examples use
  generic projects. Per-machine state goes under `${HOME}/.claude/state/board/`,
  never in the plugin dir.
- Follow the existing plugin shape: `plugins/board/.claude-plugin/plugin.json`
  (same author/license fields as `conventions` and `dev`), a `board` entry in
  `.claude-plugin/marketplace.json`, hooks in `plugins/board/hooks/hooks.json` using
  `${CLAUDE_PLUGIN_ROOT}`, skills under `plugins/board/skills/`, this doc in
  `plugins/board/docs/`, and a row in the README plugin table.
- Scripts in bash (`set -euo pipefail`) or stdlib-only python3, matching
  `conventions`; tests in the repo's existing styles (python `unittest` or the
  `*_test.sh` + shellcheck runner), with a CI workflow for the plugin's tests.
- Commits use the repo's scoped style (`board: ...`); no em or en dashes in
  deliverables.

## Constraints

- Must work from any worktree of a repo and from the main checkout, and resolve the
  same board.
- Concurrent writers: several sessions may write at the same moment. Writes must not
  lose updates or leave the board checkout mid-merge.
- Board operations must be fast enough to run in a `SessionStart` hook without
  noticeably delaying session start.
- The startup summary must be short (it costs context in every session).
- Follow the repo's existing plugin layout, script language, test and commit
  conventions.

## Calls made by the designer (not discussed with the user; easy to revisit)

- **Branch name is `claude/board`**, not bare `board`, so it can't collide with an
  existing branch. Bootstrap creates it only if absent; if it exists, the plugin
  adopts it only when it carries the board's marker file, and otherwise refuses with
  a clear message. It never rewrites or deletes an existing branch.
- **Language: stdlib-only python3** for the board tool and hook logic (locking,
  parsing and concurrency are awkward in bash), with thin bash wrappers only where
  the hook shape needs them.
- **Session liveness via heartbeats:** hooks (`SessionStart`, `UserPromptSubmit`,
  `Stop`, `SessionEnd`) touch a per-session heartbeat under
  `${HOME}/.claude/state/board/`. Heartbeats are per-machine and never committed.
  "Ended" = `SessionEnd` seen or heartbeat older than the stale threshold, since
  `SessionEnd` does not fire on a crash. "Waiting on you" comes from the app if the
  mod API exposes session state, otherwise from `Stop`/`Notification` heartbeats.
- **Session identity:** a claim records the session id. If a resumed session keeps
  its id, the claim carries over; if not, the old claim goes stale and the new
  session takes it over (with a one-line note in the ticket log). No transfer magic.
- **Current ticket** for a session = its most recent claim; side quests filed from
  that session get it as parent.
- **Side-quest cues:** behaviour is driven by skill instructions, plus a cheap
  `UserPromptSubmit` hook that matches the user's cue words and injects a one-line
  reminder (e.g. "user cue: park → file a ticket under <current>"). This makes cue
  capture testable and not dependent on Claude remembering the instructions.
- **Pane delivery order:** the builder's first task is a short spike confirming the
  desktop mod API can render the pane, refresh from files, and handle clicks (open
  ticket, jump to session). The data layer, hooks and the generated HTML board do
  not depend on the mod and ship regardless. If a capability is missing (e.g. jump to
  session), that interaction is dropped from the pane rather than worked around.

## Left to the builder

- Exact on-disk format of goals and tickets (the user wants it readable; one markdown
  file per ticket with frontmatter, or a single structured file, are both
  acceptable if diffs stay readable and concurrent edits stay safe).
- The fixed worktree path, and how it is kept out of the main checkout's
  `git status`.
- Locking / commit strategy for concurrent writes.
- How sessions are identified and how "idle" / "waiting on you" / "ended" are
  detected for the pane and for stale claims.
- The interface Claude uses (CLI script, MCP server, or skill + script), as long as
  it works in hooks and in sessions.
- How the pane gets its data and refreshes (file watch vs polling).
- Thresholds (idle time before a claim is stale, how many "next up" items).
