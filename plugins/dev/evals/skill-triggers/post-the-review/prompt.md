---
description: Post the review must load post-review-comments.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

The review of PR #17 on rtircher/dot-claude looks right to me. Go ahead and post the review on GitHub, one comment per finding anchored on the right lines.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
