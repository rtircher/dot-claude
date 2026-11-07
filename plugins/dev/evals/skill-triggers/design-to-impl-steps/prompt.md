---
description: Breaking an approved design into steps must not load design-doc.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

The design in docs/design/rate-limiting.md was approved yesterday, no changes needed. Break it into an ordered list of implementation steps with small PR-sized chunks, so I can hand them out to the team.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
