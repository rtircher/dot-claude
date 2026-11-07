---
description: Judging a diff's test coverage must load testing.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

I just finished the retry logic in src/http/client.ts and wrote tests in test/http/client.test.ts. Can you look over the tests and tell me if they're actually any good? I'm worried a couple of them just assert that the mock got called and would pass even if I broke the backoff.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
