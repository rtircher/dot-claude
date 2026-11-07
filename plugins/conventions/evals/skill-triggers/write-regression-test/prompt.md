---
description: Adding a regression test for a bug must load testing.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

Users report that `parseDuration("1h30m")` in src/lib/time.ts returns 3600000 instead of 5400000, it drops the minutes part. I want to fix it, but first add a regression test in test/time.test.ts that reproduces it. There are already a bunch of parseDuration tests in there, so figure out where it fits.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
