# Coordinator discipline: detail

Read from the main skill's *Coordinator discipline* section. The coordinator is a thin
coordinator, not a worker; these are the working rules.

- **Delegate by default; read raw material only when a decision needs it.** Don't
  open files, diffs, or logs in the main session "just to check." Dispatch a
  sub-agent and let its summary come back. The coordinator reads raw material
  directly only when a ping decision genuinely turns on a detail a summary can't
  carry.
- **Sub-agents persist, the coordinator points.** Bulky artifacts (the spec, the
  plan, per-review findings) are written to files by the sub-agent that produces
  them. The coordinator passes *paths* to the next phase, not inline text, so the
  artifact is never re-pasted into the main context.
- **Verification runs in a sub-agent.** Run the project's verification commands in
  a sub-agent that returns pass/fail plus failures only. Full build/test logs
  should not land in the main session.
- **Phase 1 stays in the main session.** Brainstorming is an interactive
  conversation with the human and can't be delegated. Still write its output to a
  spec file rather than carrying the spec inline.
