---
description: A cloud setup script that installs tools must load toolchain.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

I'm writing scripts/cloud-setup.sh for our cloud sessions. It needs Ruby 3.3 and Python 3.12 plus shellcheck available before the tests run. Currently there's a .ruby-version file and nothing else. Draft the install steps.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
