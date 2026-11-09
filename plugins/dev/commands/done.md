---
description: Close out this session: check its work is committed and pushed, finish anything left, then archive it
argument-hint: "[--keep to check without archiving]"
disable-model-invocation: true
---

The user is asking: are we done here, is every change committed and pushed, is
anything left to do, and if not, archive this session. Typing `/dev:done` is
their consent to archive this session, and only this one, once the checks below
pass. With `--keep` in `$ARGUMENTS`, run the checks and report but do not
archive.

Judge only this session's own work: the repos and paths its transcript touched.
Other sessions may share checkouts (a personal config repo above all), so a
dirty file this session never wrote is not yours to commit and does not block
the archive.

1. **Commits and pushes.** For each repo this session changed (its working
   directory or worktree, plus any config repo where it wrote memory, settings,
   hooks or skills):
   - Uncommitted changes this session made: commit them per that repo's rules
     (its AGENTS.md / CLAUDE.md, or a jj repo's local instructions), naming
     paths so other sessions' files stay out.
   - Commits not on the remote: in a git repo, compare against the upstream, or
     against `origin/<default>` for a session branch whose work went straight to
     the default branch (`git log origin/main..HEAD` empty means done; the
     unpushed `rtr/<slug>` branch itself does not matter). In a jj repo, check
     that the session's bookmarks are pushed. Push what is missing, following
     the SCM rules (never push an auto-generated branch name, never open a PR
     without asking).
2. **Live work.** Background tasks or subagents still running; linked sessions
   still working (`list_sessions` with `linked: true`); a PR this session
   opened that is still open (say its state: CI, review). Steps on the task
   list not completed. A follow-up promised in this session that was never done
   or handed off.
3. **Delivered against the ask.** Re-read the user's requests in this session,
   the first one and every later one, plus any plan, spec or handover file the
   session wrote or followed (`docs/superpowers/{plans,specs}/`, a handover
   doc): list each requirement or plan step and mark it done (with the commit
   or evidence), handed off (to which session or ticket), or open. Anything
   claimed done but never verified (a change not yet seen working, a test not
   run) counts as open.
4. **Verdict. Archive only when sure.** A wrong archive costs more than a
   needless "not yet", so any doubt means do not archive. Stop and report what
   is left in a short list if any of these hold: step 1 needed a decision from
   the user (a PR to open, a commit whose scope is unclear, a conflict); step 2
   found live or unfinished work; step 3 has any item open or unclear. Name
   the one thing that would clear each item.

   For every PR this session opened or pushed to, list its unresolved review
   threads: `bash "${CLAUDE_PLUGIN_ROOT}/skills/pr-comments/scripts/unresolved-threads.sh" <pr-url>`.
   A thread the session addressed (fix pushed, or pushback given) but left open
   is unfinished: reply if it has no reply yet, then resolve it, per the
   `pr-comments` skill. A thread nobody has addressed blocks as
   an unresolved review comment. A human thread awaiting the user's own reply
   is listed, not resolved.

   An open PR waiting for review is done for this session: it does not block,
   and the close-out names it. It blocks only when the session still owes it
   something: failing CI, requested changes or unresolved review comments, or
   a pushed branch the PR does not yet carry. CI still running does not block;
   say so in the close-out.
5. **Archive.** Otherwise send a two-line close-out (what shipped, with commit
   SHAs or PR links; anything deliberately left), then call
   `mcp__ccd_session_mgmt__archive_session` with `session_id: "self"` and a
   short reason. Load it with ToolSearch first if it is deferred. The plugin's
   PreToolUse hook auto-allows that self-archive and leaves archiving any other
   session to the normal permission flow. The conversation ends with that call,
   so the close-out goes before it, and skip the wrap-up box.
