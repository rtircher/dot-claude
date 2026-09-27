---
description: The phrase "code review" must route to the full tier.
tags: [review-routing]
max_turns: 5
allowed_tools: [Read, Glob, Grep, Skill]
---

Do a code review of PR 20 in rtircher/dot-claude.

Only decide and print the tier line as your first line, then stop: do not dispatch reviewers, run workflows, or call external tools beyond reading the skill.
