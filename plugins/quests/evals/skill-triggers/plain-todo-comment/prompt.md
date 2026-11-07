---
description: A plain code comment must not load log.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

In src/http/client.ts, add a one-line code comment above the retry loop explaining why we cap at 5 attempts (the upstream rate limit resets every 5 requests). No other changes.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
