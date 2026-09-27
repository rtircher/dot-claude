---
description: The phrase "review this PR" must route to the full tier.
tags: [review-routing]
max_turns: 5
allowed_tools: [Read, Glob, Grep, Skill]
---

Please review this PR: https://github.com/rtircher/dot-claude/pull/20

Only decide and print the tier line as your first line, then stop: do not dispatch reviewers, run workflows, or call external tools beyond reading the skill.
