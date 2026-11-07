# dev plugin evals

`review-routing/` checks that the `adversarial-review` skill's tier router
picks the right tier (`SKILL.md`, "Pick tier"):
full tier for a bare PR URL, a PR number, "review this PR", "code review", a
spec/plan path; quick tier only for "quick pass" /
"quick review" / "quick look" / "quick check". Every case also checks the
built-in `/code-review` skill is never invoked while deciding the tier.

Run it with:

```
claude plugin eval plugins/dev --tag review-routing
```

`skill-triggers/` checks that `design-doc` and `post-review-comments` load
when they should (two should-trigger cases each) and stay unloaded on a
near-miss (an approved design to break into steps; a PR review with no ask to
post). The `tool_used: Skill` graders are with-arm only, a "plugin fired"
indicator under the default with-without ablation.

```
claude plugin eval plugins/dev --tag skill-triggers
```

Each run spawns real, billed Claude agent runs (3 runs per case by default).
Run on demand only, not on every push.
