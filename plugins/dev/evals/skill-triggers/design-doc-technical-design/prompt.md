---
description: A technical design request must load design-doc.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

Draft an RFC for moving our nightly billing export (jobs/billing_export.py) from a cron script to a queue-based worker. The finance team depends on the CSV format so I want the risks and alternatives written down properly.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
