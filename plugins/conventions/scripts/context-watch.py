#!/usr/bin/env python3
"""PostToolUse hook: warn when the session context crosses budget bands.

Reads the transcript's most recent assistant usage block, computes the live
context size (input + cache-read + cache-creation tokens), and when it crosses
a new band emits a nudge to delegate or respawn (see conventions.md,
"Delegation"). Each band warns once per session.

The cap and bands live in ../context-budget.json, the one home for them: this
hook, delegation-gate and the dot-files status line all read it.

The budget is min(effective session window, cap). The window is derived from
the model id on the same transcript entry the usage comes from: models with a
native 1M window count as 1M, everything else — including unknown or future
ids — falls back to 200k (conservative: warns early, never late). A "[1m]"
marker in the model id also counts as 1M, though in practice the API echo
strips that suffix, so a 200k-native model running the 1m beta is treated as
200k. The cap is a cost budget, not the physical window: on 1M-window
models the whole context is still re-read every turn, so the cap bounds the
per-turn spend instead of letting the session grow to the window.

Three bands, three distinct messages: the lowest (60) only asks the
session to shift into delegation mode — it says nothing about wrapping up,
because delegation is most valuable while most of the budget is still
unspent. The middle band (85) says stop taking on new inline work and to
estimate, from measured per-step cost, whether the rest still fits before
respawning (a respawn is not free and a mid-task handover loses momentum); the
last (100) says wrap up and respawn, at the cap itself. The wrap-up bands stay high because the fixed
session baseline (system prompt, MCP schemas, CLAUDE.md, conventions/hook
injections — measured at ~47-66k across recent sessions) already consumes a
fifth to a third of the budget before any work happens.

Env overrides:
  CONTEXT_WATCH_WINDOW  budget in tokens; when set, used verbatim (skips the
                        model lookup and the cap)
  CONTEXT_WATCH_BANDS   comma-separated warn thresholds in percent (default:
                        the bands in context-budget.json)
"""
import json
import os
import sys
import tempfile

TAIL_BYTES = 512 * 1024

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "context-budget.json"
)
with open(CONFIG_PATH) as _f:
    _CONFIG = json.load(_f)
BUDGET_CAP = int(_CONFIG["cap_tokens"])
BANDS = sorted(int(b) for b in _CONFIG["bands"])
FALLBACK_WINDOW = 200_000
# Canonical model-id prefixes with a native 1M window, from the Claude Code
# model table (2.1.219). 200k-native and unknown ids both fall back to 200k,
# so only the 1M side needs listing.
NATIVE_1M_PREFIXES = (
    "claude-sonnet-5",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-fable-5",
    "claude-mythos-5",
)


def bands():
    """Warn thresholds in percent: CONTEXT_WATCH_BANDS, else the config's."""
    override = os.environ.get("CONTEXT_WATCH_BANDS")
    if override:
        return sorted(int(b) for b in override.split(","))
    return BANDS


def effective_window(model):
    """Best-effort context window for the session's model id."""
    if not model:
        return FALLBACK_WINDOW
    model = model.lower()
    if "[1m]" in model or model.startswith(NATIVE_1M_PREFIXES):
        return 1_000_000
    return FALLBACK_WINDOW


def last_usage(transcript_path):
    """Return (usage dict, model id) of the last main-loop assistant message."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None, None
    for line in reversed(tail.splitlines()):
        if '"usage"' not in line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        message = entry.get("message", {})
        usage = message.get("usage")
        if usage and "input_tokens" in usage:
            return usage, message.get("model")
    return None, None


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    transcript = payload.get("transcript_path")
    session_id = payload.get("session_id", "unknown")
    if not transcript:
        return

    usage, model = last_usage(transcript)
    if not usage:
        return
    context = (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )
    override = os.environ.get("CONTEXT_WATCH_WINDOW")
    if override:
        budget = int(override)
    else:
        budget = min(effective_window(model), BUDGET_CAP)
    pct = 100 * context // budget

    warn_bands = bands()
    crossed = [b for b in warn_bands if pct >= b]
    if not crossed:
        return
    band = crossed[-1]

    state_path = os.path.join(
        tempfile.gettempdir(), f"context-watch-{session_id}"
    )
    try:
        with open(state_path) as f:
            already_warned = int(f.read().strip() or 0)
    except (OSError, ValueError):
        already_warned = 0
    if band <= already_warned:
        return
    with open(state_path, "w") as f:
        f.write(str(band))

    if band >= warn_bands[-1]:
        advice = (
            "Wrap up now: finish the current step only, then write a handover "
            "and respawn into a fresh session. Do not start new work here."
        )
    elif len(warn_bands) >= 3 and band == warn_bands[0]:
        advice = (
            "Shift into delegation mode: from here, send exploration and "
            "sustained implementation to subagents and keep the main loop to "
            "orchestration and targeted reads. No need to wrap up — just stop "
            "growing this context with bulk work."
        )
    else:
        advice = (
            "Stop taking on new inline work: delegate remaining implementation "
            "or research to subagents. Before respawning, estimate the remaining "
            "cost from what the same kind of step cost earlier in this session; "
            "if it fits the budget left, keep going and finish the current unit "
            "of work. Respawn only when it clearly does not fit, at a natural "
            "boundary, and say what the estimate was."
        )
    message = (
        f"Context at {pct}% of the {budget:,}-token budget ({context:,} tokens). "
        f"{advice} (conventions: Delegation)"
    )
    print(
        json.dumps(
            {
                "systemMessage": f"context-watch: {pct}% of context budget used",
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": message,
                },
            }
        )
    )


if __name__ == "__main__":
    main()
