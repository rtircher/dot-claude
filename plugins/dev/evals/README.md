# dev plugin evals

`review-routing/` checks that the `adversarial-review` skill's tier router
picks the right tier (design doc `docs/design/unified-review.md` section 4.2):
full tier for a bare PR URL, a PR number, "review this PR", "code review", a
spec/plan path, or `/dev:review-panel`; quick tier only for "quick pass" /
"quick review" / "quick look" / "quick check". Every case also checks the
built-in `/code-review` skill is never invoked while deciding the tier.

Run it with:

```
claude plugin eval plugins/dev --tag review-routing
```

Each run spawns real, billed Claude agent runs (3 runs per case by default).
Run on demand only, not on every push.
