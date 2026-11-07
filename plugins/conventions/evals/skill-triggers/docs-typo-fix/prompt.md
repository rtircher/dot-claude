---
description: A pure docs typo fix must not load testing.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

There's a typo in docs/getting-started.md, it says "instal the CLI" in the second paragraph and "configuation" in the heading of the config section. Please fix both, nothing else in the file needs to change.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
