# conventions plugin evals

`skill-triggers/` checks that the `testing` and `toolchain` skills load when
they should (two should-trigger cases each) and stay unloaded on a near-miss
(a docs typo fix; adding an app library dependency). The `tool_used: Skill`
graders are with-arm only, a "plugin fired" indicator under the default
with-without ablation.

```
claude plugin eval plugins/conventions --tag skill-triggers
```

Each run spawns real, billed Claude agent runs. Run on demand only, not on
every push.
