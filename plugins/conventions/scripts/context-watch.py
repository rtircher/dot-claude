#!/usr/bin/env python3
"""PostToolUse hook: warn when the session context crosses budget bands.

Reads the transcript's most recent assistant usage block, computes the live
context size (input + cache-read + cache-creation tokens), and when it crosses
a new band emits a nudge to delegate or respawn (see conventions.md,
"Delegation"). Each band warns once per session.

CONTEXT_WATCH_WINDOW is a cost budget, not the model's physical window: on
1M-window models (fable) the whole context is still re-read every turn, so the
200k default deliberately warns at the same absolute spend on every model.

Env overrides:
  CONTEXT_WATCH_WINDOW  context budget in tokens (default 200000)
  CONTEXT_WATCH_BANDS   comma-separated warn thresholds in percent (default 50,70,85)
"""
import json
import os
import sys
import tempfile

TAIL_BYTES = 512 * 1024


def last_usage(transcript_path):
    """Return the usage dict of the last main-loop assistant message, or None."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        if '"usage"' not in line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        usage = entry.get("message", {}).get("usage")
        if usage and "input_tokens" in usage:
            return usage
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    transcript = payload.get("transcript_path")
    session_id = payload.get("session_id", "unknown")
    if not transcript:
        return

    usage = last_usage(transcript)
    if not usage:
        return
    context = (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )
    window = int(os.environ.get("CONTEXT_WATCH_WINDOW", "200000"))
    bands = sorted(
        int(b) for b in os.environ.get("CONTEXT_WATCH_BANDS", "50,70,85").split(",")
    )
    pct = 100 * context // window

    crossed = [b for b in bands if pct >= b]
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

    if band >= bands[-1]:
        advice = (
            "Wrap up now: finish the current step only, then write a handover "
            "and respawn into a fresh session. Do not start new work here."
        )
    else:
        advice = (
            "Stop taking on new inline work: delegate remaining implementation "
            "or research to subagents, and if substantial work remains, write a "
            "handover and respawn into a fresh session."
        )
    message = (
        f"Context at {pct}% of the {window:,}-token budget ({context:,} tokens). "
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
