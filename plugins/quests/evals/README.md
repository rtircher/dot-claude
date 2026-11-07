# quests plugin evals

`skill-triggers/` checks that the `log` skill loads on "set up quests" and on
a side-quest cue, and stays unloaded when the ask is a plain code comment. The
cases avoid needing a pre-existing quest log. The `tool_used: Skill` graders
are with-arm only, a "plugin fired" indicator under the default with-without
ablation.

```
claude plugin eval plugins/quests --tag skill-triggers
```

Each run spawns real, billed Claude agent runs. Run on demand only, not on
every push.
