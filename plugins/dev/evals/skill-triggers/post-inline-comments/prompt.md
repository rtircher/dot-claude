---
description: An explicit ask to post review comments must load post-review-comments.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

You just reviewed PR #42 and found three issues: a missing null check in src/auth/session.ts line 88, an N+1 query in src/api/orders.ts, and a flaky sleep in test/orders.test.ts. Please post those as inline comments on the PR now, marking which ones block merge.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
