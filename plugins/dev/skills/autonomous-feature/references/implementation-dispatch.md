# Phase 5 and 6 dispatch detail

Execute the clean plan. Prefer your subagent-driven execution skill for
plans with independent tasks; use a plan-execution skill or inline
implementation when that fits better, use judgment, and say which you chose and
why. When dispatching subagents, pick the agent type per task rather than
defaulting: `dev:coder` (worktree-isolated) for implementer tasks
that edit files in parallel, `dev:reviewer` for review tasks (adversarial
stance and findings schema baked in), `dev:researcher` or `Explore` for
read-only research and search. Tiers follow the conventions' routing table
(pass `model: sonnet` by default, `model: fable` for hard reasoning, `model: opus` only as
an escalation, each remapped through `DOT_CLAUDE_MODEL_MAP` when it is set);
review phases route themselves. Follow the
project's own conventions (TDD, verification) as those skills direct.

**Every implementer dispatch brief carries the simplicity contract.** Subagents
never see this skill, so the *Bias to simplicity* rules must travel in the
brief itself: implement only what the task names;
before writing new code, reuse an existing helper, then stdlib, then a native
platform feature, then an installed dependency, and only then the smallest
working implementation; no new dependencies without reporting back; anything
beyond the task is a report-back, not a bonus. An implementer building more
than its brief describes is the scope-expansion ping firing one level down -
surface it, don't merge it.

## Phase 6 detail

Run the `adversarial-review` skill on the completed work (the branch diff). Its
diff panel runs correctness, simplicity & YAGNI, testing, and duplication lenses,
beside an advisory prose lens whose findings never gate. External reviewers run per *Third-party review* above. For a **multi-task** plan, also run the final cross-implementation
symmetry pass (`model: sonnet`, `opus` for a large or subtle diff) over the full branch diff to catch type asymmetry,
parallel-structure drift, undocumented behavior, and cross-package coupling that
per-task work misses.
