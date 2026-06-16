#!/usr/bin/env python3
"""
Stop hook: block assistant turns that contain an em-dash (U+2014) or en-dash
(U+2013) in user-facing prose, forcing a rewrite with periods/colons/commas.

The conventions plugin's "Writing style" rule disallows these dashes; a soft
prompt rule is not enough against the training default, so this hook turns it
into a hard contract. Shipped in the plugin (not user-scope ~/.claude) so it
travels to cloud/web sessions too, where the rule otherwise has no enforcement.

Code blocks (fenced ``` and inline `code`) are stripped before scanning, so
quoted file contents and shell snippets that legitimately contain dashes don't
trigger false positives. When stop_hook_active is true (we've already forced
one redo), we silently allow the turn through to prevent an infinite loop.
"""

from __future__ import annotations

import json
import re
import sys


FENCE = re.compile(r"```.*?```", re.DOTALL)
INLINE = re.compile(r"`[^`]*`")
DASHES = ("—", "–")
# Deliberate override the assistant emits when a dash is genuinely warranted,
# carrying a 1/5..5/5 self-rating of how strongly it feels the dash is needed
# (left visible in the output so a weak justification is obvious to the reader).
# Example: {emdash-ok 5/5: quoting the user's message verbatim}
SENTINEL = re.compile(r"\{emdash-ok\s+[1-5]/5:[^}]*\}")


def strip_code(text: str) -> str:
    text = FENCE.sub("", text)
    text = INLINE.sub("", text)
    return text


def last_assistant_text(transcript_path: str) -> str:
    last = ""
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                inner = msg.get("message") or {}
                if inner.get("role") != "assistant":
                    continue
                content = inner.get("content") or []
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        last = block.get("text", "") or last
    except OSError:
        return ""
    return last


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if payload.get("stop_hook_active"):
        return 0

    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return 0

    text = last_assistant_text(transcript_path)
    if not text:
        return 0

    scan = strip_code(text)
    if not any(d in scan for d in DASHES):
        return 0

    # Deliberate, self-rated override for the rare legitimate case.
    if SENTINEL.search(text):
        return 0

    reason = (
        "Your last response contained an em-dash (U+2014) or en-dash (U+2013). "
        "Per the conventions plugin's no-em-dash writing rule, these are "
        "disallowed in user-facing prose. Rewrite the response without them: "
        "prefer a period and a new sentence, then a colon, comma, parentheses, "
        "or simpler sentence structure. Do NOT replace dashes one-for-one with "
        "hyphens, which usually reads worse. Restructure the sentence. "
        "If the dash is genuinely warranted (quoting text verbatim, or writing "
        "about dashes themselves), keep it and add a visible override marker "
        "rating how strongly it is warranted: {emdash-ok N/5: brief reason}, "
        "with N from 1 (weak) to 5 (essential). Use this sparingly."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
