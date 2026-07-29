#!/usr/bin/env python3
"""PreToolUse hook: deny bulk reads in a deep main-loop context.

The context-watch hook (PostToolUse) is advisory; transcript analysis showed
it changes respawn behavior but not delegation — deep sessions still do all
their exploration inline. This hook enforces the Delegation convention: once
the live context crosses the first context-watch band, bulk read/search calls
in the MAIN LOOP are denied with instructions to dispatch a researcher
subagent instead. A denied tool call redirects the model where injected
advice does not.

What is gated (only when armed):
  - Read without offset/limit, or with limit > FREE_READ_LINES
  - Grep with output_mode "content" and no head_limit
  - Bash commands that start with a read/search binary (cat, head, tail,
    rg, grep, find, awk, sed)

What is never gated:
  - Subagent (sidechain) tool calls — subagents are the delegates
  - Targeted reads (offset+limit), compact greps, Glob
  - Any turn that already dispatched an Agent (the model is delegating;
    verifying results inline is fine)
  - The first FREE_ROUNDTRIPS bulk-read round-trips of a turn (a round-trip
    is one assistant message, however many parallel calls it batches —
    batching is encouraged, so it is never penalized)

Above the last band the allowance drops to 1 round-trip: at that depth the
advisory has already said to wrap up.

All ambiguity fails open (allow): a wrongly denied read costs a confused
turn, a wrongly allowed read costs a few thousand tokens.

Env overrides:
  DELEGATION_GATE            "off" disables the gate entirely
  DELEGATION_GATE_ARM_PCT    context percent at which the gate arms (default 70;
                             deliberately above context-watch's 50% delegation
                             nudge — advice first, teeth later; lower to 50 if
                             the nudge alone still produces no dispatches)
  DELEGATION_GATE_ROUNDTRIPS free bulk round-trips per turn when armed (default 3)
  CONTEXT_WATCH_WINDOW       shared with context-watch (default 250000, matching
                             the min(model window, 250k) budget context-watch
                             computes for every model currently in use; fold in
                             its effective_window() helper if the fleet ever
                             includes a 200k-native model)
  CONTEXT_WATCH_BANDS        shared with context-watch (default 50,70,85; only
                             the last band is read here, for the harsh tier)
"""
import json
import os
import re
import sys

TAIL_BYTES = 2 * 1024 * 1024
FREE_READ_LINES = 250
BASH_READ_RE = re.compile(r"^\s*(cat|head|tail|rg|grep|find|awk|sed)\b")


def is_bulk_read(tool_name, tool_input):
    """True if this call is the kind of bulk read the gate applies to."""
    tool_input = tool_input or {}
    if tool_name == "Read":
        limit = tool_input.get("limit")
        return limit is None or limit > FREE_READ_LINES
    if tool_name == "Grep":
        return (
            tool_input.get("output_mode") == "content"
            and tool_input.get("head_limit") is None
        )
    if tool_name == "Bash":
        return bool(BASH_READ_RE.match(tool_input.get("command", "")))
    return False


def read_tail(transcript_path):
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            return f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def parse_entries(lines):
    for line in reversed(lines):
        if '"type"' not in line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") in ("user", "assistant"):
            yield entry


def is_turn_boundary(entry):
    """True for a genuine user prompt (not a tool_result carrier)."""
    if entry.get("type") != "user" or entry.get("isSidechain"):
        return False
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return not any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
    return False


def tool_uses(entry):
    content = entry.get("message", {}).get("content")
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]


def main():
    if os.environ.get("DELEGATION_GATE", "").lower() == "off":
        return
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    tool_name = payload.get("tool_name", "")
    if not is_bulk_read(tool_name, payload.get("tool_input")):
        return
    transcript = payload.get("transcript_path")
    if not transcript:
        return

    lines = read_tail(transcript)
    entries = list(parse_entries(lines))
    if not entries:
        return

    # If the newest assistant entry is a sidechain, this call is (almost
    # certainly) a subagent's — never gate the delegates.
    newest_assistant = next(
        (e for e in entries if e.get("type") == "assistant"), None
    )
    if newest_assistant is None or newest_assistant.get("isSidechain"):
        return

    usage = None
    context = 0
    bulk_roundtrips = 0
    skipped_own_message = False
    for entry in entries:
        if is_turn_boundary(entry):
            break
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        if usage is None:
            u = entry.get("message", {}).get("usage")
            if u and "input_tokens" in u:
                usage = u
                context = (
                    u.get("input_tokens", 0)
                    + u.get("cache_read_input_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0)
                )
        uses = tool_uses(entry)
        if any(t.get("name") in ("Agent", "Task") for t in uses):
            return  # already delegating this turn
        bulky = [t for t in uses if is_bulk_read(t.get("name"), t.get("input"))]
        if bulky:
            # The newest assistant message is the round-trip that issued the
            # call being gated — exclude it once so a parallel batch counts
            # as a single round-trip and is judged consistently.
            if not skipped_own_message and any(
                t.get("name") == tool_name for t in bulky
            ):
                skipped_own_message = True
                continue
            bulk_roundtrips += 1
        skipped_own_message = True

    if usage is None:
        return

    window = int(os.environ.get("CONTEXT_WATCH_WINDOW", "250000"))
    bands = sorted(
        int(b) for b in os.environ.get("CONTEXT_WATCH_BANDS", "50,70,85").split(",")
    )
    arm_pct = int(os.environ.get("DELEGATION_GATE_ARM_PCT", "70"))
    pct = 100 * context // window
    if pct < arm_pct:
        return
    free = int(os.environ.get("DELEGATION_GATE_ROUNDTRIPS", "3"))
    if pct >= bands[-1]:
        free = 1
    if bulk_roundtrips < free:
        return

    reason = (
        f"delegation-gate: context is at {pct}% of the {window:,}-token budget "
        f"({context:,} tokens) and this turn already made {bulk_roundtrips} bulk "
        "read/search round-trips inline. Do not retry this call as-is. Either "
        "(a) dispatch a researcher/Explore subagent (Agent tool, explicit "
        "model:) briefed to return conclusions, not file dumps; (b) make the "
        f"read targeted — Read with offset+limit ≤{FREE_READ_LINES} lines, or "
        "Grep with head_limit — which stays allowed; or (c) if this session is "
        "wrapping up, write the handover and respawn instead. "
        "(conventions: Delegation)"
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


if __name__ == "__main__":
    main()
