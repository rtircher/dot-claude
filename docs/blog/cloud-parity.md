# Making cloud agent sessions behave like my laptop

If you run an AI coding agent in more than one place, you've probably hit this: the agent is sharp on your laptop and strangely dumb in the cloud. Same repo, same model, different behavior. It forgets conventions, skips your skills, runs commands your local setup would never run.

That gap has a cause, and it's fixable. Here's the "cloud parity" setup I built so a fresh cloud session behaves like my local one, and why each piece exists.

## The problem: a cloud session starts cold

Locally, my agent is rich with context. Shared plugins inject my working conventions at session start. Custom skills are on disk. Git hooks are wired. A pre-commit gate catches mistakes. None of that is in the repo, it's in my machine's configuration, built up over time.

A cloud session gets none of it for free. It boots a clean Ubuntu sandbox, clones the repo, and starts the agent. If the plugins that carry my conventions aren't present, the session silently runs without them. Not with an error, just quietly worse. That silence is the dangerous part: you don't notice the agent is missing half its instructions until it does something it would never do locally.

So the goal isn't "copy my whole laptop to the cloud." It's narrower: make sure a cold session loads the same conventions, the same skills, and the same guardrails, with no manual setup, and fail loudly when it can't.

## The shape of the fix: one canonical seed, vendored into each repo

The setup is a small set of scripts that live in one canonical place (my shared config repo) and get copied (vendored) into each consumer repo with a provenance stamp. A single command does the copy:

```
/dev:init-cloud-parity
```

It drops four byte-identical scripts into a single `.claude/cloud/` directory, writes a starter recipe file beside them, and merges two keys into `.claude/settings.json`. Everything the setup owns lives under that one directory, so all the cloud plumbing sits in one place instead of scattered across the repo. Crucially, it touches only what it owns: the marketplace registration and a session-start hook entry. It never edits which plugins are enabled, your permissions, or your other hooks. The repo stays in control of its own policy; the seed just carries the plumbing.

Because the files are stamped with the commit they came from, drift is detectable. A `--check` mode compares each vendored file against the live canonical version and exits non-zero on any difference. That check runs in CI, so a repo can't silently fall behind the seed.

## The two-stage trick: build-time setup, then in-session rescue

The interesting part is when things run. A cloud environment gives you two moments, and they have different powers.

Stage one runs once, as root, at container-build time, and gets cached. This is where system packages and the expensive marketplace clone happen. Two repo-agnostic steps live here:

* Fix apt. The base image pre-bakes some third-party PPAs whose host is off the trusted network tier and returns 403, which makes `apt-get update` report a partial failure. The script disables those PPAs first and keeps update/install non-fatal, so a flaky repo can't abort the whole setup.
* Pre-warm the marketplace clone, so my plugins are on disk before the session takes its snapshot of available skills and hooks. It adds the marketplace (a harmless clone) but deliberately does not `install`, because install writes a global enable that would leak my plugins into every other repo on the cached image.

Stage two runs in-session, as the normal user, every cold start. This is the rescue. The build-time pre-warm only fires if the agent CLI is on PATH at setup time, and in some environments it isn't. So a session-start hook re-attempts the clones, detached, so it never blocks the session. The harness lazy-registers a plugin mid-session once its clone lands.

Splitting the work this way matters because the two stages can't substitute for each other. Root-at-build-time work (apt packages, native toolchains) can't run in the non-root in-session hook. And anything that needs to recover from a missed snapshot can't run only at build time. You need both.

## Plugins as data, not code

The list of plugins a repo needs is a flat recipe file (`.claude/cloud/cloud-parity-recipes`):

```
marketplace-add rtircher/dot-claude
install superpowers@claude-plugins-official
```

The rescue script reads this file and clones what's listed. That keeps the script itself byte-identical across every repo. A repo that needs no cloud plugins just ships no recipe file. And the `--check` gate cross-references this list against the repo's enabled plugins, so it warns when a plugin is enabled but has no clone recipe, exactly the silent-missing-skill failure the whole design exists to prevent.

## Failing loud, in the right places

A theme runs through all of it: swallow the failures that should never block a session, surface the ones you'd otherwise never notice.

* The session-start hook swallows its own errors. A broken hook should never wedge a session.
* But if a previous session's detached rescue logged a failure (say, GitHub was unreachable), the next session reads that log and puts a visible warning in context, with a pointer to a doctor script (`.claude/cloud/cloud-plugin-doctor.sh`). A detached process that fails silently is worthless; you have to carry its failure forward.
* Repo-specific root setup is not wrapped in `|| true`. A real install failure there should fail the build loudly rather than cache a broken image. The genuinely best-effort steps mark themselves.

There's also a conventions backstop. My shared conventions normally arrive through a plugin's own session-start hook. If that plugin's clone lands after the session's hook-registration snapshot, the hook never fires and the session runs without the conventions. So the seed hook checks whether the conventions file is on disk and, only if it's absent, injects a pointer plus the few cross-project rules inline. Belt and suspenders, but the failure it guards against is exactly the invisible one.

## The trust boundary

The recipe file drives `marketplace add` and `install` of whatever it names, on every cold session, unattended. That's real power, so it gets treated like any other committed code: changes go through PR review, and only trusted marketplaces go in. My own config repo is pinned to live HEAD, which is an accepted exposure I've made eyes-open.

## What I'd take away from this

Three things generalize beyond my particular setup:

1. The dangerous failure is the silent one. An agent that's quietly missing its instructions looks like it's working. Most of this design is machinery to make that condition visible.
2. Know which stage owns which work. Build-time-root and in-session-user are different capabilities. Map each task to the stage that can actually do it, and accept that some tasks need both.
3. Configuration as code, with a drift gate. Vendoring a stamped seed plus a CI check beats documentation that says "remember to set up the cloud environment." The check is what keeps parity real over time instead of true on day one and rotted by month three.

Parity isn't a one-time setup. It's a property you have to keep enforcing, which is why the most valuable single piece here turned out to be the boring one: the `--check` that fails CI when a repo drifts.
