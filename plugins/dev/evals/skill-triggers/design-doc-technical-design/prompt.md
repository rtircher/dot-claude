---
description: A request for the technical design of a feature must load design-doc.
tags: [skill-triggers]
max_turns: 4
allowed_tools: [Read, Glob, Grep, Skill]
---

We're going to add rate limiting to the public API (services/gateway, currently nothing but an nginx limit). Can you write up the technical design for it before we build anything? Needs to cover per-key vs per-IP limits, where state lives (we have Redis already), and how we roll it out without breaking existing customers.

Load whatever skill you would use for this, print one line `skill: <name>` (or `skill: none` if you would use none) as your first line, then stop: do not do the work or call tools beyond reading the skill.
