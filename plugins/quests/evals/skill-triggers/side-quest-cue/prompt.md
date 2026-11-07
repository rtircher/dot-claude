---
description: A side-quest cue must load log.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

Keep going on the retry logic in src/http/client.ts. Btw, park it for later: the date formatter in src/lib/format.ts breaks on Feb 29, someone should look at that, but not now.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
