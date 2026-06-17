#!/usr/bin/env python3
"""
PreToolUse hook: keep an em-dash (U+2014) or en-dash (U+2013) out of a
deliverable, text that appears as written by the user. Conversation with Claude
is deliberately not checked; that is why this is a PreToolUse hook on the writing
tools, not a Stop hook on every turn (which would reprompt ordinary replies).

Surfaces checked:
- Write / Edit / MultiEdit: the file content being written.
- git commit (and gt create / gt modify): the commit message.
- MCP send tools (Slack, email, etc.): the message body.

It denies the call before the text lands, so the model rewrites without the
dash. There is no inline override marker: a marker would pollute the file,
commit, or message. The escape for a genuinely needed dash in a file is the
ALLOWLIST below.

Fenced ``` / ~~~ blocks and inline `code` are stripped before scanning, so a
dash inside an embedded code block or shell snippet does not trigger.
"""

from __future__ import annotations

import json
import re
import sys


FENCE = re.compile(r"(```|~~~).*?\1", re.DOTALL)
FENCE_OPEN = re.compile(r"(```|~~~).*\Z", re.DOTALL)
INLINE = re.compile(r"`[^`]*`")
DASHES = ("—", "–")

# A file whose path contains any of these substrings skips the check. Add a path
# for a file that legitimately needs a dash (e.g. a doc quoting verbatim). This
# hook's own source is listed because it stores the dash characters themselves.
ALLOWLIST = ("conventions/scripts/block-emdash.py",)

# MCP tools whose name matches this are treated as message sends worth checking.
MCP_SEND = re.compile(r"send|post.?message|create.?message|reply|chat.*post|e?mail", re.I)
MCP_FIELDS = ("text", "body", "message", "content", "markdown", "html")

# git / gt commands that carry a commit message (tolerating sudo and env prefixes).
COMMIT_CMD = re.compile(
    r"^\s*(?:sudo\s+)?(?:[A-Z_][A-Za-z0-9_]*=\S+\s+)*"
    r"(?:git\s+commit|gt\s+(?:create|modify))\b"
)


def strip_code(text: str) -> str:
    text = FENCE.sub("", text)
    text = FENCE_OPEN.sub("", text)
    text = INLINE.sub("", text)
    return text


def has_dash(text: str) -> bool:
    if not text:
        return False
    return any(d in strip_code(text) for d in DASHES)


def _allowlisted(path: str) -> bool:
    return any(s in (path or "") for s in ALLOWLIST)


def text_to_check(tool_name: str, ti: dict) -> str:
    """The deliverable text for this tool call, or "" when there is nothing to check."""
    if tool_name == "Write":
        return "" if _allowlisted(ti.get("file_path", "")) else (ti.get("content") or "")
    if tool_name == "Edit":
        return "" if _allowlisted(ti.get("file_path", "")) else (ti.get("new_string") or "")
    if tool_name == "MultiEdit":
        if _allowlisted(ti.get("file_path", "")):
            return ""
        edits = ti.get("edits") or []
        return "\n".join(e.get("new_string", "") for e in edits if isinstance(e, dict))
    if tool_name == "Bash":
        cmd = ti.get("command") or ""
        # The if: matcher fires on substrings, so re-validate it is really a commit.
        return cmd if COMMIT_CMD.search(cmd) else ""
    if tool_name.startswith("mcp__") and MCP_SEND.search(tool_name):
        return "\n".join(str(ti.get(f, "")) for f in MCP_FIELDS if ti.get(f))
    return ""


SURFACE = {
    "Write": "This file",
    "Edit": "This file",
    "MultiEdit": "This file",
    "Bash": "This commit message",
}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name = payload.get("tool_name") or ""
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        return 0

    if not has_dash(text_to_check(tool_name, ti)):
        return 0

    surface = SURFACE.get(tool_name, "This message")
    reason = (
        f"{surface} contains an em-dash (U+2014) or en-dash (U+2013), which the "
        "conventions plugin's no-em-dash writing rule disallows in text written "
        "as the user. Redo this call without it: prefer a period and a new "
        "sentence, then a colon, comma, or parentheses. Do NOT swap the dash for "
        "a hyphen, which reads worse; restructure the sentence instead. For a "
        "genuinely needed dash in a file (e.g. quoting verbatim), add the file "
        "path to the ALLOWLIST in block-emdash.py."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
