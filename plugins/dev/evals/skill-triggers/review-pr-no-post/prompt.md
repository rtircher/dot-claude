---
description: A review request with no ask to post must not load post-review-comments.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

Review PR #12 on rtircher/dot-claude. It touches the session hook and the install docs. Just tell me what you think here in the chat, I'll decide myself what goes on the PR.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
