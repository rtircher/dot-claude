---
description: The phrase "quick pass" on a PR URL must route to the quick tier.
tags: [review-routing]
max_turns: 5
allowed_tools: [Read, Glob, Grep, Skill]
---

quick pass on https://github.com/rtircher/dot-claude/pull/20

Only decide and print the tier line as your first line, then stop: do not dispatch reviewers, run workflows, or call external tools beyond reading the skill.
