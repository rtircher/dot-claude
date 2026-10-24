---
name: log
description: Use the shared per-repo quest log through the `quest` CLI. Use when starting work in a repo that has a quest log (the session start summary says "Quests:"), when the user asks "what's next" or "where are we", when the user parks something with a side-quest cue (park it, later, side note, follow up, flag it, btw), or when the user asks to "set up quests".
---

# Quests

A shared quest log per repo, kept on a git branch, visible to every session. Goals are "main quests"; tickets are "quests". Drive it with the `quest` CLI. Always answer quest log questions from the CLI, not from docs you happened to read.

## Invoking the CLI

- `quest` is on PATH when SessionStart could export it.
- Otherwise use the absolute path from the `Quests CLI: <path>; session: <id>` startup line.
- If `QUESTS_SESSION_ID` and `CLAUDE_CODE_SESSION_ID` are both unset, pass `--session <id>` (the id from that line) on every command.
- Add `--json` for machine-readable output.

## Exit codes

- 0: ok.
- 2: no quest log for this repo (or, for `quest side`, no current quest). Offer setup (see below), or use `quest add` for a side quest.
- 3: take refused, another session holds the quest. Tell the user who holds it. Do not start the work.
- 4: setup refused. Report the message verbatim. Change nothing.
- 5: busy, another quest command is running. Retry once.
- 1: any other error (one line). Report it.

## During work

1. Before starting: run `quest next` or `quest log`. Then `quest take <id>`. If no quest fits, create one first with `quest add "<title>"`, then take it.
2. A stale claim shown in the log may be taken over with `quest take <id>`. The CLI performs the takeover only when the claim is stale, otherwise it exits 3.
3. Record findings worth keeping with `quest note <id> "<text>"`.
4. Link docs instead of copying them: `quest link <id> <path-or-url>`.
5. Finish with `quest done <id>`. If it prints `Back to: <id> <title>`, offer to return with the `quest take <id>` command it shows. `quest drop <id>` gives a quest back. Other statuses: `quest status <id> todo|in_progress|blocked|done|dropped`.
6. If a write prints `(unsynced: will push on next sync)`, mention it to the user once. Do not repeat it.

## Questions

"What's next?" and "where are we?": answer from `quest log` (and `quest next`), not from docs.

## Side quests

- On a user cue (park it, later, side note, follow up, flag it): `quest side "<title>"` and confirm in one line. It files under the quest this session is on. If it exits 2 because there is no current quest, use `quest add "<title>"`.
- On "btw": answer first. If it turned into work, offer a side quest in one line.
- If you notice drift without a cue, ask in one line: `This looks like a side quest off <current>; log it and keep going?` Never file silently on inference.

## Setup ("set up quests")

1. Ask: same repo or an external repo?
2. Say that pushed quest content is visible to anyone with access to that remote.
3. External: ask for the repo URL, and say cloud sessions need `CLAUDE_QUESTS_REPO=<url>` in their environment.
4. Run `quest init --mode same` or `quest init --mode external --url <url>`.
5. Propose main quests from existing plans and runbooks. Create only the ones the user approves: `quest main add "<title>" --link <doc>`.
6. A repo that still has the old `claude/board` branch is migrated automatically at session start, or by hand with `quest migrate`.

## Command reference

`quest log [--next-limit N] | next | sync | show <id> | add <title> [--main G] [--parent ID] [--link L] | side <title> [--link L] | take <id> | drop <id> | done <id> | status <id> <status> | note <id> <text> | link <id> <link> | main add <title> [--link L] | main list | init --mode same|external [--url URL] | migrate`
