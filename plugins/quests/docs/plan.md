Historical: written when this plugin was called `board`; it is now `quests`.

# `board` Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `plugins/board/`, a shared ticket board per repo that every Claude Code session (local or cloud) reads at startup, claims work from, files side quests to, and that the desktop app shows at a glance.

**Architecture:** Board data is plain files (one markdown file per ticket and goal) on an orphan git branch, in the code repo's remote or an external repo. Each machine keeps one clone of that branch under `${HOME}/.claude/state/board/`. Every change is an *operation* appended to a local journal, then synced: fetch, hard-reset to the remote tip, replay the journal, commit, push, retry on rejection. That is "rebase before every change, push after every change" without textual merge conflicts. A python CLI (`board`) does all of it; hooks call the same library; a skill tells Claude how to behave; the pane and the HTML page render one JSON summary.

**Tech Stack:** python3 stdlib only (no third-party packages), git CLI, bash wrappers, python `unittest`, GitHub Actions. Pane: the desktop-app mod API (confirmed in Task 1).

**Spec:** `plugins/board/docs/design.md`

**Deviation from the spec (flagged for approval):** the spec puts the local board in "one extra git worktree at a fixed path derived from the repo's common git dir". This plan uses one *clone* of the board branch per machine under the state dir instead. It is still a single shared copy for all local sessions, but it works the same way for same-repo and external boards and in cloud sessions, and it never appears in the code repo's `git worktree list` or `git status`.

## Global Constraints

- Public repo: no personal paths, hostnames, IPs, emails (other than the existing noreply author), account names, or real board data anywhere, including tests and fixtures. Fixtures use generic projects ("Example goal", "Set up backups").
- Per-machine state only under `${BOARD_STATE_DIR:-$HOME/.claude/state/board}`; never written inside the plugin dir or the code repo's working tree.
- Never commit to, reset, or rewrite the session's working branch. Never rewrite or delete an existing branch the plugin didn't create (spec: adopt only with marker file, else refuse).
- Plugin shape: `plugins/board/.claude-plugin/plugin.json` with the same `author`/`license` fields as `plugins/conventions`; entry in `.claude-plugin/marketplace.json`; hooks in `plugins/board/hooks/hooks.json` via `${CLAUDE_PLUGIN_ROOT}`; row in the README plugin table.
- Hooks must never fail a session: every hook catches all exceptions, prints nothing harmful, exits 0. Hook syncs use a 4 s fetch budget, a 6 s push floor and a 2 s lock wait, under the SessionStart hook's declared 15 s timeout.
- Startup summary: at most 25 lines.
- Commits: scoped style `board: <Imperative description>`; no `Co-Authored-By`; no em or en dashes in any deliverable.
- Statuses are exactly `todo`, `in_progress`, `blocked`, `done`, `dropped`. Goal progress = `done` / (all tickets in goal except `dropped`).
- Branch names: same-repo mode `claude/board`; external mode `board/<slug>` in the external repo.
- Thresholds: local session stale after 2 h without heartbeat or after `SessionEnd`; a claim held by a session with no local heartbeat (other machine or cloud) is stale when its ticket's `updated` is older than 24 h. "Next up" shows 5 items then "+N more".

## Review Focus

1. **Two writers change the board at the same moment** (two local sessions, or local + cloud): both changes survive; nothing is silently dropped. Tests in Task 4.
2. **No network at session start** (offline, VPN down, remote unreachable): the SessionStart hook returns within its timeout, still prints the last known board marked unsynced, and queued changes push on the next successful sync. Tests in Tasks 4 and 6.
3. **Session started outside a git repo, or in a repo with no board / no remote:** hooks print at most one line and exit 0; the CLI says what to do instead of a traceback. Tests in Tasks 5 and 6.
4. **A branch named `claude/board` (or `board/<slug>`) already exists without the marker:** `init` refuses, names the branch, and touches nothing. Test in Task 5.
5. **Ticket titles and notes with colons, quotes, `---`, unicode, or newlines** round-trip through the file format unchanged (newlines in notes become ` / `). Test in Task 2.

---

### Task 1: Spike the platform (throwaway, notes only)

Confirms the platform facts later tasks rely on. No product code.

**Files:**
- Create: `plugins/board/docs/platform-notes.md`

**Interfaces:**
- Produces: a notes file answering each question below with "yes / no / how", which Tasks 6 and 9 read.

- [ ] **Step 1:** Using the `plugin-authoring` skill, find out how a desktop-app mod renders a pane: how it's packaged (can it ship inside a plugin in this marketplace, or must it be installed per machine?), how it gets data (run a command? read a file? watch a file?), how it refreshes, whether it can open a file/URL on click, and whether it can switch to or open a session by id.
- [ ] **Step 2:** With a throwaway local plugin, confirm: (a) hook stdin JSON carries `session_id` and `cwd` for `SessionStart`, `UserPromptSubmit`, `Stop`, `SessionEnd`; (b) `CLAUDE_ENV_FILE` is set for `SessionStart` and exports written there reach later Bash tool calls, in both the desktop app and a cloud session; (c) which env var marks a cloud session (expected `CLAUDE_CODE_REMOTE=true`); (d) `UserPromptSubmit` JSON `hookSpecificOutput.additionalContext` reaches the model.
- [ ] **Step 3:** Write the answers to `plugins/board/docs/platform-notes.md` (public-clean). If (b) fails anywhere, record the fallback: the SessionStart summary prints the CLI's absolute path and the session id, and the skill tells Claude to pass `--session`.
- [ ] **Step 4:** Commit: `board: Record platform facts for hooks and the pane mod`.

---

### Task 2: Plugin skeleton and the file format

**Files:**
- Create: `plugins/board/.claude-plugin/plugin.json`, `plugins/board/lib/board/__init__.py`, `plugins/board/lib/board/store.py`, `plugins/board/tests/test_store.py`, `.github/workflows/board-tests.yml`
- Modify: `.claude-plugin/marketplace.json` (add `{"name":"board","source":"./plugins/board","description":"Shared, repo-local ticket board every session sees"}`), `README.md` (plugin table row)

**Interfaces:**
- Produces (`board.store`):
  - `@dataclass Owner(session: str, label: str, where: str, claimed_at: str)` (`where` is `"local"` or `"cloud"`)
  - `@dataclass LogEntry(at: str, session: str, text: str)`
  - `@dataclass Ticket(id: str, title: str, status: str, goal: str | None, parent: str | None, blocked_by: list[str], owner: Owner | None, links: list[str], created: str, updated: str, log: list[LogEntry])`
  - `@dataclass Goal(id: str, title: str, order: int, links: list[str])`
  - `@dataclass Board(meta: dict, goals: dict[str, Goal], tickets: dict[str, Ticket])`
  - `load_board(root: Path) -> Board`, `write_ticket(root: Path, t: Ticket) -> Path`, `write_goal(root: Path, g: Goal) -> Path`, `write_meta(root: Path, meta: dict) -> Path`
  - `new_id(prefix: str, existing: set[str]) -> str`: `prefix + "-" + 5 random chars from [a-z0-9]`, retried until unused. Prefixes: `t` tickets, `g` goals.
  - Timestamps: UTC ISO 8601 to the second with `Z` (`2026-10-18T10:00:00Z`).
- On disk (inside the board checkout):
  - `board.json`: `{"schema": 1, "code_repo": "<key>"}` (the marker)
  - `goals/<id>.md`, `tickets/<id>.md`: frontmatter between `---` lines, one `key: <JSON value>` per line, keys in fixed order (`id, title, status, goal, parent, blocked_by, owner, links, created, updated` for tickets; `id, title, order, links` for goals). Then a body `# <title>` and, for tickets, `## Log` with one line per entry: `- <at> (<session>) <text>`, newlines in text replaced by ` / `.

- [ ] **Step 1: Write failing tests** in `tests/test_store.py`: `test_ticket_round_trip` (write then load equals original, including owner and two log entries); `test_awkward_titles_round_trip` with titles `'OPNsense: "quoted" --- é'` and a note `"line1\nline2"` loading back as `"line1 / line2"`; `test_frontmatter_key_order_is_stable` (file text matches an expected literal for a fixture ticket); `test_new_id_format` (matches `^t-[a-z0-9]{5}$`, avoids a given existing set); `test_load_empty_board` (only `board.json` gives empty goals and tickets).
- [ ] **Step 2:** Run `python3 -m unittest discover -s plugins/board/tests -t plugins/board` → FAIL (import error).
- [ ] **Step 3:** Implement `board.store` per Interfaces. Tests put `plugins/board/lib` on `sys.path` via a `tests/__init__.py` helper.
- [ ] **Step 4:** Run the same command → PASS.
- [ ] **Step 5:** Add `plugin.json`, the marketplace entry, the README row, and `.github/workflows/board-tests.yml` (on PRs touching `plugins/board/**`; ubuntu-latest; `actions/checkout` pinned by SHA like `cloud-parity-tests.yml`; `git config --global user.name/email` to a generic CI identity; run the unittest command above).
- [ ] **Step 6:** Commit: `board: Add plugin skeleton and the ticket file format`.

---

### Task 3: Operations and views

**Files:**
- Create: `plugins/board/lib/board/ops.py`, `plugins/board/lib/board/views.py`, `plugins/board/tests/test_ops.py`, `plugins/board/tests/test_views.py`

**Interfaces:**
- Consumes: `board.store` (Task 2).
- Produces (`board.ops`):
  - An op is a dict with `op`, `at`, `session`, plus fields. Ops and fields:
    `create_goal{id,title,order,links}`, `create_ticket{id,title,goal,parent,links}`, `claim{id,owner}` (owner as `Owner` dict), `release{id}`, `set_status{id,status}`, `note{id,text}`, `add_link{id,link}`, `set_goal{id,goal}`.
  - `apply_op(root: Path, op: dict) -> list[str]`: applies to files, returns human-readable warnings. IDs are chosen by the caller, so replay is deterministic.
  - Rules: every op sets `updated = op["at"]`. `set_status` to `done`/`dropped` clears `owner`. `claim` on a ticket owned by a *different* session is not applied: it appends log `claim by <session> lost to <owner.label>` and returns a warning. Ops on an unknown id return a warning and change nothing. `create_ticket` with an id that already exists is a no-op (idempotent replay).
- Produces (`board.views`):
  - `@dataclass SessionState(session: str, label: str, where: str, state: str, last_seen: str)` (`state` is `active` · `waiting` · `ended`)
  - `summary(board: Board, sessions: dict[str, SessionState], now: datetime, current_session: str | None, synced: bool, next_limit: int = 5) -> dict` returning exactly:
    `{"repo": str, "synced": bool, "goals": [{"id","title","done","total"}], "sessions": [{"session","label","where","state","chain": [{"id","title"}]}], "next": [{"id","title","goal"}], "next_more": int, "stale": [{"id","title","owner_label"}]}`
  - Session `state` in the output adds two derived values: `idle` (local, `active` but `last_seen` older than 15 min) and `remote` (owner has no local heartbeat). `chain` is the session's most recently claimed in-progress ticket and its ancestors via `parent`, root first. The current session's entry comes first. Stale claims (Global Constraints thresholds) are listed in `stale` and their session is omitted from `sessions`.
  - `next`: tickets with status `todo`, no owner, and every `blocked_by` ticket `done`; ordered by goal `order`, then `created`.
  - `render_text(s: dict) -> str`: at most 25 lines; first line `Board: <repo>` plus ` (unsynced)` when `synced` is false.

- [ ] **Step 1: Write failing tests:** `test_apply_create_and_note`; `test_done_releases_owner`; `test_claim_lost_race_logs_and_warns`; `test_replay_is_idempotent` (applying the same op list twice gives identical files); `test_unknown_id_warns`; `test_goal_progress_excludes_dropped` (goal with done, todo, dropped gives `done=1,total=2`); `test_next_skips_blocked_and_owned`; `test_chain_root_first` (A ← B ← C claimed by S gives chain `[A,B,C]`); `test_stale_local_and_remote` (heartbeat 3 h old gives stale; remote owner with ticket updated 25 h ago gives stale, 23 h does not); `test_render_text_max_25_lines` (40 tickets).
- [ ] **Step 2:** Run unittest → FAIL.
- [ ] **Step 3:** Implement `board.ops` and `board.views` per Interfaces.
- [ ] **Step 4:** Run unittest → PASS.
- [ ] **Step 5:** Commit: `board: Add board operations and the summary view`.

---

### Task 4: Locate, checkout and sync

**Files:**
- Create: `plugins/board/lib/board/locate.py`, `plugins/board/lib/board/sync.py`, `plugins/board/tests/gitfixture.py`, `plugins/board/tests/test_locate.py`, `plugins/board/tests/test_sync.py`

**Interfaces:**
- Consumes: `board.ops.apply_op` (Task 3).
- Produces (`board.locate`):
  - `state_dir() -> Path`: `$BOARD_STATE_DIR` or `~/.claude/state/board`.
  - `repo_key(cwd: Path) -> str | None`: `None` outside git. From `origin` URL normalized to `host/owner/name` (strip scheme, user, `.git`; `git@host:o/n` and `https://host/o/n` give the same key); with no `origin`, `local-` + first 10 hex chars of sha1 of the absolute common git dir.
  - `slug(key: str) -> str`: `[^a-z0-9]+` replaced by `-`, lowercased.
  - `@dataclass BoardRef(key: str, mode: str, url: str, branch: str)` (`mode` is `"same"` or `"external"`)
  - `resolve(cwd: Path) -> BoardRef | None`, in order: entry for the key in `state_dir()/config.json`; else if `$CLAUDE_BOARD_REPO` is set: external, `branch=board/<slug>`, only if that branch exists on that remote; else same-repo `claude/board` if it exists on `origin` or locally (url = `origin` URL, or the common git dir path when no origin); else `None`.
  - `save_config(ref: BoardRef) -> None`.
- Produces (`board.sync`):
  - `checkout_dir(ref) -> Path` = `state_dir()/checkouts/<slug(key)>`
  - `@dataclass SyncResult(synced: bool, warnings: list[str])`
  - `submit(ref: BoardRef, op: dict, timeout: float = 5, lock_wait: float | None = None, push_min: float = PUSH_MIN) -> SyncResult`: under lock, append op to `state_dir()/journal/<slug>.jsonl`, then `_sync`.
  - `sync(ref: BoardRef, timeout: float = 5, lock_wait: float | None = None, push_min: float = PUSH_MIN) -> SyncResult`: under lock, `_sync`.
  - `_sync` algorithm: ensure checkout exists (clone single branch, or reuse); `git fetch` with timeout; if fetch fails, reset the working copy to the last known remote tip, replay the journal into it without committing, and return `synced=False` (so local readers see pending changes). If fetch succeeds: `git reset --hard origin/<branch>`, replay each journal op with `apply_op`, one commit per op (`board: <op> <id>`, author from the user's git config), `git push` with the remaining budget but at least a floor (`push_min`, default 10 s, since an interrupted push can still land); if the replay leaves HEAD at the fetched tip, skip the push and treat it as success; on non-fast-forward rejection retry the whole fetch/reset/replay up to 5 times; on success truncate the journal and return `synced=True` with collected warnings; on network failure keep the journal and return `synced=False`.
  - Lock: `fcntl.flock` on `state_dir()/locks/<slug>.lock`, waiting up to 20 s (longer than the default fetch budget plus push floor), then raise `BoardBusy`.
- Test fixture (`tests/gitfixture.py`): `make_remote(tmp) -> Path` (bare repo), `make_code_repo(tmp, origin: Path | None) -> Path`, and a context manager setting `BOARD_STATE_DIR` and `HOME`-independent git identity per test.

- [ ] **Step 1: Write failing tests:** `test_repo_key_normalizes_ssh_and_https`; `test_repo_key_none_outside_git`; `test_resolve_order_config_then_env_then_same` (each source wins over the next); `test_submit_pushes_and_clears_journal`; `test_two_clones_concurrent_notes_both_survive` (two state dirs simulating two machines each submit a note to the same ticket; after both sync, the remote has both log lines); `test_two_local_sessions_share_lock` (two threads submitting 20 ops each, all 40 present on the remote); `test_offline_keeps_journal_and_shows_pending` (remote path made unreachable: `synced` false, local checkout shows the change, journal non-empty; after restoring, `sync` pushes and clears); `test_push_rejection_retries` (a commit pushed by a second clone between fetch and push is kept).
- [ ] **Step 2:** Run unittest → FAIL.
- [ ] **Step 3:** Implement `board.locate` and `board.sync` per Interfaces, all git calls through one `run_git(args, cwd, timeout) -> CompletedProcess` helper.
- [ ] **Step 4:** Run unittest → PASS.
- [ ] **Step 5:** Commit: `board: Sync board changes by replaying a journal on the remote tip`.

---

### Task 5: The `board` CLI, including setup

**Files:**
- Create: `plugins/board/bin/board` (bash: `exec python3 "$(dirname "$(realpath "$0")")/../lib/board_cli.py" "$@"`), `plugins/board/lib/board_cli.py`, `plugins/board/lib/board/cli.py`, `plugins/board/lib/board/setup.py`, `plugins/board/tests/test_cli.py`

**Interfaces:**
- Consumes: `store`, `ops`, `views`, `locate`, `sync`.
- Produces:
  - `board.setup.init(cwd: Path, mode: str, url: str | None) -> BoardRef`. Same mode: branch `claude/board` on `origin` (or the local repo when no origin). External: `branch=board/<slug>` on `url`; saves config. If the target branch exists: adopt when it has `board.json` with `schema: 1`, else raise `SetupRefused("branch <name> exists and is not a board; nothing changed")`. New board: orphan commit with `board.json`, pushed.
  - `board.cli.main(argv: list[str]) -> int`. Session identity from `--session` or `$BOARD_SESSION_ID`, label from `$BOARD_SESSION_LABEL`, `where` from `$BOARD_WHERE` (default `local`). Exit codes: `0` ok, `2` no board for this repo (prints `No board for this repo. Run: board init --mode same|external [--url URL]`), `3` claim refused (prints owner label), `4` setup refused, `5` busy.
  - Commands (all accept `--json`): `init --mode same|external [--url URL]`; `summary`; `show ID`; `next`; `add TITLE [--goal G] [--parent ID] [--link L]...` (prints new id); `claim ID` (refuses with exit 3 if a non-stale other session owns it); `release ID`; `status ID todo|in_progress|blocked|done|dropped`; `note ID TEXT`; `link ID LINK`; `goal add TITLE [--link L]...`; `goal list`; `sync`; `html [--out PATH]` (Task 8).
  - Every write command prints `(unsynced: will push on next sync)` when `SyncResult.synced` is false.

- [ ] **Step 1: Write failing tests** (run `main` in temp repos via the Task 4 fixture): `test_no_board_exit_2_with_hint`; `test_outside_git_exit_2`; `test_init_same_then_add_and_summary_json` (summary JSON matches the Task 3 schema); `test_init_refuses_foreign_branch` (pre-create `claude/board` with an unrelated commit: exit 4, branch tip unchanged); `test_init_adopts_existing_board`; `test_init_external_writes_config_and_branch_name` (`board/github-com-example-repo` for origin `git@github.com:example/repo.git`); `test_claim_refused_when_owned` (exit 3, message names the owner label); `test_add_side_quest_with_parent` (chain in summary shows parent first).
- [ ] **Step 2:** Run unittest → FAIL.
- [ ] **Step 3:** Implement `board.setup` and `board.cli` with `argparse`.
- [ ] **Step 4:** Run unittest → PASS; also `bash -n plugins/board/bin/board` and `shellcheck --severity=warning plugins/board/bin/board` (skip if shellcheck absent).
- [ ] **Step 5:** Commit: `board: Add the board CLI and setup`.

---

### Task 6: Hooks (startup summary, heartbeats, cue capture)

**Files:**
- Create: `plugins/board/hooks/hooks.json`, `plugins/board/lib/board_hooks.py`, `plugins/board/lib/board/hooks.py`, `plugins/board/lib/board/cues.py`, `plugins/board/tests/test_hooks.py`, `plugins/board/tests/test_cues.py`

**Interfaces:**
- Consumes: `locate.resolve`, `sync.sync`, `views.summary`/`render_text`, platform facts from `docs/platform-notes.md` (Task 1).
- Produces:
  - `hooks.json`: `SessionStart` → `python3 "${CLAUDE_PLUGIN_ROOT}"/lib/board_hooks.py session-start` (timeout 15); `UserPromptSubmit` → `... prompt` (timeout 5); `Stop` → `... stop`; `SessionEnd` → `... end`.
  - Heartbeat file `state_dir()/sessions/<session_id>.json`: `{"session","label","where","repo_key","state","last_seen"}`. `session-start`/`prompt` set `active`, `stop` sets `waiting`, `end` sets `ended`. `views` reads these as `SessionState`.
  - `session_label(cwd: Path) -> str`: current branch with everything up to the last `/` removed and a trailing `-[0-9a-f]{6}` removed; detached HEAD gives the worktree directory name.
  - `session-start`: write heartbeat; if `$CLAUDE_ENV_FILE` is set, append `export BOARD_SESSION_ID=...`, `BOARD_SESSION_LABEL=...`, `BOARD_WHERE=...`, and `PATH="${CLAUDE_PLUGIN_ROOT}/bin:$PATH"`; resolve the board; if none, print one line `Board: none for this repo (say "set up a board" to create one).`; else `sync` (4 s fetch budget, 6 s push floor) and print `render_text`, followed by the line `Claim a ticket before starting work; file side quests with \`board add --parent\`.` If `CLAUDE_ENV_FILE` is unavailable (per Task 1), also print `Board CLI: <abs path>; session: <id>`.
  - `board.cues.match(prompt: str) -> str | None`: returns `"park"` for the park/later/side-note/follow-up/flag-it family, `"btw"` for `btw`/`by the way`/`sidenote` used as a question, else `None`. Patterns, case-insensitive, word-bounded: `park (it|this|that)`, `(for|until) later`, `(do|handle|address|look at|deal with)( it| this| that)? later`, `side ?note`, `follow[- ]?up (task|item|ticket)`, `add (a )?follow[- ]?up`, `flag (it|this|that)`, `\bbtw\b`, `by the way`.
  - `prompt`: heartbeat; on `"park"` emit `hookSpecificOutput.additionalContext` = `Board cue: the user is parking something. File it with \`board add --parent <your current ticket>\` and confirm in one line.`; on `"btw"` = `Board cue: answer the btw first; if it turns into work, offer a ticket in one line.`; no network.
  - All entry points wrap everything in `try/except Exception`, write the error to `state_dir()/hook-errors.log`, exit 0.

- [ ] **Step 1: Write failing tests:** `test_cues` table (`"Ram I will address later so park it for now"` gives `park`; `"side note to add to the next steps"` gives `park`; `"add a follow up task to set up DNS"` gives `park`; `"btw can I ssh in?"` gives `btw`; `"the later version is fine"`, `"park the car"`, `"follow the steps"` give `None`); `test_session_label` (`team/utm-backups-a095ad` gives `utm-backups`, `main` gives `main`); `test_session_start_no_repo_prints_one_line_exit_0`; `test_session_start_offline_within_timeout` (unreachable remote: returns in under 8 s, output starts `Board: ... (unsynced)`); `test_session_start_writes_env_file`; `test_prompt_emits_additional_context_json`; `test_hook_swallows_exceptions` (corrupt `board.json`: exit 0, error logged); `test_stop_and_end_update_heartbeat_state`.
- [ ] **Step 2:** Run unittest → FAIL.
- [ ] **Step 3:** Implement per Interfaces.
- [ ] **Step 4:** Run unittest → PASS.
- [ ] **Step 5:** Commit: `board: Inject the board at session start and catch side-quest cues`.

---

### Task 7: The board skill (session behaviour and setup flow)

**Files:**
- Create: `plugins/board/skills/board/SKILL.md`, `plugins/board/README.md`
- Modify: `plugins/board/tests/test_hooks.py` (add a frontmatter test)

**Interfaces:**
- Consumes: CLI commands and exit codes (Task 5), cue reminders (Task 6).
- Produces: skill `board:board`, description triggering on: starting work in a repo with a board, "what's next", "where are we", side-quest cues, "set up a board".

Content the skill must state (the spec's session behaviour, as instructions):
- Before starting work: `board next` / `board summary`, then `board claim <id>` (create the ticket first if none fits). On exit code 3, tell the user who holds it and don't start.
- Record findings worth keeping with `board note`. Mark `done` when finished.
- Side quests: on the user's cues, `board add "<title>" --parent <current>` and confirm in one line. On "btw", answer first, then offer a ticket in one line if it turned into work. On noticed drift without a cue, ask in one line (`This looks like a side quest off <current>; ticket it and keep going?`); never file silently on inference.
- "What's next?" / "where are we?": answer from `board summary`, not from docs the session happened to read.
- Link docs instead of copying them (`board link`).
- Setup ("set up a board"): ask same repo vs external repo; state that pushed board content is visible to anyone with access to that remote; for external, ask for the URL and say cloud sessions need `CLAUDE_BOARD_REPO=<url>` in their environment; run `board init`; then propose goals from existing plans/runbooks, create only the ones the user approves (`board goal add --link <doc>`).
- When a CLI write prints `unsynced`, mention it once.

- [ ] **Step 1: Write failing test** `test_skill_frontmatter` (SKILL.md exists, frontmatter has `name: board` and a non-empty `description`, file contains no em/en dashes and no `/Users/`).
- [ ] **Step 2:** Run unittest → FAIL.
- [ ] **Step 3:** Write `SKILL.md` and `plugins/board/README.md` (what it does, setup, cloud env var, public-visibility note, CLI reference).
- [ ] **Step 4:** Run unittest → PASS.
- [ ] **Step 5:** Commit: `board: Add the board skill and plugin README`.

---

### Task 8: Full-board HTML page

**Files:**
- Create: `plugins/board/lib/board/render_html.py`, `plugins/board/tests/test_render_html.py`
- Modify: `plugins/board/lib/board/cli.py` (`html` command)

**Interfaces:**
- Consumes: `Board`, `views.summary`.
- Produces: `render_html(board: Board, s: dict) -> str`, a self-contained page (inline CSS, no external requests, light and dark via `prefers-color-scheme`) with: goal progress bars; in progress grouped by session with chains; next up; then every goal expanded into its ticket tree (side quests nested under parents), done and dropped collapsed; each ticket's links and log. All text HTML-escaped. `board html` writes to `--out` or `state_dir()/html/<slug>.html` and prints the path.

- [ ] **Step 1: Write failing tests:** `test_html_escapes_titles` (`<script>` in a title appears escaped); `test_html_has_no_external_urls` (no `http` in `src=`/`href=` except ticket links); `test_html_nests_side_quests` (child ticket appears inside parent's element).
- [ ] **Step 2:** Run unittest → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run unittest → PASS.
- [ ] **Step 5:** Commit: `board: Render the full board as an HTML page`.

---

### Task 9: Glance pane (desktop mod)

**Files:** per `plugins/board/docs/platform-notes.md` (Task 1); test file alongside in the repo's node `*.test.mjs` style if the mod is JS.

**Interfaces:**
- Consumes: `board summary --json` (Task 3 schema; the pane never reads board files directly), `board html` (Task 8) for "open full board".
- Produces: the pane from the approved layout, top to bottom: `Project · <repo>` with one progress bar per goal (`done/total`); `In progress · N sessions` with one block per session (label, state badge `active` / `idle` / `waiting on you` / `remote`, chain with earlier items muted and the current one bold), current session first; `Next up` with 5 items and `+N more`; an "unsynced" badge when `synced` is false; a "full board" action opening the HTML page. Clicks: ticket opens its `board show` detail; session jumps to that session; goal expands its remaining tickets. Any click the mod API can't do (per Task 1) is left out, not faked.

- [ ] **Step 1: Write failing test** for the pure render function (summary JSON fixture → expected section order, bar fractions, `+3 more` for 8 next items, current session first, `waiting on you` label for state `waiting`).
- [ ] **Step 2:** Run it → FAIL.
- [ ] **Step 3:** Implement render function and the mod wiring (data via `board summary --json`, refresh per the platform notes).
- [ ] **Step 4:** Run the test → PASS; then load the mod in the desktop app against a scratch repo with a board and screenshot the pane.
- [ ] **Step 5:** Commit: `board: Add the glance pane`.
