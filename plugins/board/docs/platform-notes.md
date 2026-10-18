# Platform notes for the board plugin

Facts later tasks rely on. Each answer says how it was checked:
**local** (throwaway plugin run via `claude -p --plugin-dir`, CLI 2.1.283),
**desktop** (observed inside a desktop-app session), **docs** (plugin-authoring
skill or code.claude.com hooks reference), **unverified**.

## Limits of the spike

`claude -p` could not complete a model turn (the CLI login was expired, so the
run printed `Failed to authenticate`). Hooks for `SessionStart`,
`UserPromptSubmit` and `SessionEnd` still fired, so stdin and env were checked.
Anything that needs a model turn is **unverified locally** and falls back to docs:
the `Stop` hook firing, `CLAUDE_ENV_FILE` exports reaching a later Bash call, and
`additionalContext` reaching the model. Re-run those once the CLI is logged in.

## Part A: the desktop-app pane (a "mod")

Source: plugin-authoring skill (`SKILL.md`, `reference.md`, `types/claude-code.d.ts`). All **docs**.

- **Can a mod ship inside a marketplace plugin?** Yes. A mod is a plugin whose
  `hooks/hooks.json` is `{ "modules": ["./register.tsx"] }`. It installs like any
  plugin (`/plugin install <name> --marketplace <owner>/<repo>`, or in the desktop
  app: + next to the prompt, Plugins, Add marketplace). A mod installed at user
  scope loads in local desktop sessions and its `ui.render` hooks draw for the
  `desktop` surface. A plugin can carry hooks.json command hooks and a module side
  by side (the manifest and layout are the same plugin layout; not tested together).
  `/plugin` itself does not run inside a desktop session; install from a terminal.
- **Scope of a pane:** per session. `$.ui.open({ id, title })` opens a pane in
  the session the module runs in; a `ui.render` hook on
  `{ component: 'Pane', requestId: id }` draws it. It is not an app-wide sidebar.
  It resolves `{ isPlaced }`; unasked it only places from 144 columns, so open it
  from a command or press (`$.command.register` + `command.run`), not silently.
- **Getting data:** `$.process.run(argv)` (no shell, 30 s default timeout, output
  up to 4 MiB) runs a command, so the pane can shell out to the board CLI by
  absolute path. `$.fs.read/list/stat/exists` read files (4 MiB cap). `$.http.fetch`
  exists. `$.fs` has no watch API.
- **Refresh:** poll with `$.clock.every(ms, fn)` then `$.ui.invalidate(...)` to
  redraw; or keep values in `$.state` atoms and `update()` them (writes redraw
  readers). `SessionStart` hookSpecificOutput `watchPaths` exists for classic
  `FileChanged` hooks, not for a pane. Plan on polling.
- **Open a file or URL on click:** Yes for URLs and files via `Markdown`: its
  `https:`, `http:` and `file:` links open as the surface opens links (or give
  `onLinkPress` to take over). For anything else a `Button` `onPress` can call
  `$.process.run(['open', path])` (macOS). Not tested.
- **Switch to or open a session by id:** No API found. The `$` nouns cover the
  current session (`$.session.id/cwd/messages/send`), no list/switch/focus call.
  `$.session.send({ to: { sessionId }, text })` messages another session but does
  not navigate to it. The desktop host has a separate id,
  `CLAUDE_CODE_HOST_SESSION_ID` (`local_<uuid>`, not the CLI session id), so a
  deep link would need the host's own scheme, which the docs do not describe.
  Treat "jump to session" as unavailable; show the id and let the user pick it.
- **Session state (waiting on user) of other sessions:** No. A mod sees its own
  session (`turn.*`, `AgentStatus`, `$.session.id()`), not other sessions. The
  board's own files must carry state (written by hooks).
- **Current session id inside the module:** `await $.session.id()`.

## Part B: hooks (command hooks in a plugin)

- **(a) stdin JSON.** local, SessionStart / UserPromptSubmit / SessionEnd:
  - all carry `session_id`, `transcript_path`, `cwd`, `hook_event_name`
  - `SessionStart` adds `source` (`startup` observed)
  - `UserPromptSubmit` adds `prompt_id`, `permission_mode`, `prompt`
  - `SessionEnd` adds `prompt_id`, `reason` (`other` observed for `-p` exit)
  - `Stop`: not observed (no model turn). Docs: common fields plus
    `last_assistant_message`; `session_id` and `cwd` are common to all events.
- **Hook env vars (local):** `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`,
  `CLAUDE_PROJECT_DIR`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_ENTRYPOINT`
  were set in every hook. `CLAUDE_CODE_SESSION_ID` equals the stdin
  `session_id` in all three hook events (checked by comparing both, local).
- **`CLAUDE_CODE_SESSION_ID` in the Bash tool (desktop):** set in the desktop
  session's Bash tool env, with `CLAUDE_CODE_ENTRYPOINT=claude-desktop`. The
  desktop session's Bash env had no `CLAUDE_ENV_FILE` and no
  `CLAUDE_CODE_REMOTE`. So identity may not need `CLAUDE_ENV_FILE` at all; the
  CLI should read `CLAUDE_CODE_SESSION_ID` first. Whether the Bash tool in a
  plain terminal CLI and in cloud also sets it is **unverified**.
- **(b) `CLAUDE_ENV_FILE`.** local: set only in `SessionStart` hooks (a path
  under the per-session env dir); unset in `UserPromptSubmit` and `SessionEnd`.
  Docs: available to SessionStart, Setup, CwdChanged and FileChanged only; an
  `export` appended with `>>` is sourced before each later Bash command. The
  end-to-end visibility in a later Bash call was **not verified** (no model turn).
  Desktop and cloud: **unverified in cloud**; the desktop path was not exercised
  beyond the env var being set (the `claude -p` run inherited a desktop host).
- **(c) Cloud marker.** docs: `CLAUDE_CODE_REMOTE=true` in remote web
  environments, unset in the local CLI (confirmed unset locally and in the
  desktop Bash env). **Unverified in cloud.**
- **(d) `additionalContext`.** docs: `UserPromptSubmit` can inject
  `hookSpecificOutput.additionalContext` alongside the prompt; Claude Code wraps
  it in a system reminder read on the next model request. Locally my hook emitted
  it, but the model turn failed, so the codeword round trip is **unverified**.

## Fallback (if CLAUDE_ENV_FILE or the session env var is missing, e.g. cloud)

The `SessionStart` summary always prints the CLI's absolute path and the
session id. The skill tells Claude to pass `--session <session-id>` when
`BOARD_SESSION_ID` is unset. Hooks themselves always have the id from stdin
`session_id`, so only Bash-tool calls need the fallback.

## Implications for later tasks

- Task 6 (hooks): read `session_id` and `cwd` from stdin; do not depend on
  `CLAUDE_ENV_FILE` working; keep the fallback above.
- Task 9 (pane): ship as a plugin module; shell out to the CLI for data; poll
  with `$.clock.every`; no session jump, so show ids as text.
