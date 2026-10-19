---
name: board
description: Use the shared per-repo ticket board through the `board` CLI. Use when starting work in a repo that has a board (the session start summary says "Board:"), when the user asks "what's next" or "where are we", when the user parks something with a side-quest cue (park it, later, side note, follow up, flag it, btw), or when the user asks to "set up a board".
---

# Board

A shared ticket board per repo, kept on a git branch, visible to every session. Drive it with the `board` CLI. Always answer board questions from the CLI, not from docs you happened to read.

## Invoking the CLI

- `board` is on PATH when SessionStart could export it.
- Otherwise use the absolute path from the `Board CLI: <path>; session: <id>` startup line.
- If `BOARD_SESSION_ID` and `CLAUDE_CODE_SESSION_ID` are both unset, pass `--session <id>` (the id from that line) on every command.
- Add `--json` for machine-readable output.

## Exit codes

- 0: ok.
- 2: no board for this repo. Offer setup (see below).
- 3: claim refused, another session holds the ticket. Tell the user who holds it. Do not start the work.
- 4: setup refused. Report the message verbatim. Change nothing.
- 5: busy, another board command is running. Retry once.
- 1: any other error (one line). Report it.

## During work

1. Before starting: run `board next` or `board summary`. Then `board claim <id>`. If no ticket fits, create one first with `board add "<title>"`, then claim it.
2. A stale claim shown in the summary may be taken over with `board claim <id>`. The CLI performs the takeover only when the claim is stale, otherwise it exits 3.
3. Record findings worth keeping with `board note <id> "<text>"`.
4. Link docs instead of copying them: `board link <id> <path-or-url>`.
5. Change status with `board status <id> todo|in_progress|blocked|done|dropped`. Mark `done` when finished. `board release <id>` gives a ticket back.
6. If a write prints `(unsynced: will push on next sync)`, mention it to the user once. Do not repeat it.

## Questions

"What's next?" and "where are we?": answer from `board summary` (and `board next`), not from docs.

## Side quests

- On a user cue (park it, later, side note, follow up, flag it): `board add "<title>" --parent <current ticket>` and confirm in one line.
- On "btw": answer first. If it turned into work, offer a ticket in one line.
- If you notice drift without a cue, ask in one line: `This looks like a side quest off <current>; ticket it and keep going?` Never file silently on inference.

## Setup ("set up a board")

1. Ask: same repo or an external repo?
2. Say that pushed board content is visible to anyone with access to that remote.
3. External: ask for the repo URL, and say cloud sessions need `CLAUDE_BOARD_REPO=<url>` in their environment.
4. Run `board init --mode same` or `board init --mode external --url <url>`.
5. Propose goals from existing plans and runbooks. Create only the ones the user approves: `board goal add "<title>" --link <doc>`.

## Command reference

`board summary | next | sync | show <id> | add <title> [--goal G] [--parent ID] [--link L] | claim <id> | release <id> | status <id> <status> | note <id> <text> | link <id> <link> | goal add <title> [--link L] | goal list | init --mode same|external [--url URL]`
