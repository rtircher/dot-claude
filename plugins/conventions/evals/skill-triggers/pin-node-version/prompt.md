---
description: Pinning a runtime must load toolchain.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

Our CI keeps picking a different Node than what I run locally. Right now package.json has an engines field saying >=18 and the GitHub workflow in .github/workflows/ci.yml uses setup-node with 20. I want one source of truth for Node 22 and pnpm for local, CI, and our cloud setup script.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
