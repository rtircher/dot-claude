---
description: Adding an app library dependency must not load toolchain.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

Add the `zod` library to our API package and use it to validate the request body in src/routes/users.ts instead of the hand-rolled checks there. Just the validation swap, no new tooling or config changes.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
