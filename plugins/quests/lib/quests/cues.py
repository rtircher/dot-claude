"""Detect side-quest cues in a user prompt."""
from __future__ import annotations

import re

_PARK = re.compile(
    r"\b(?:park (?:it|this|that)"
    r"|(?:for|until) later"
    r"|(?:do|handle|address|look at|deal with)(?: it| this| that)? later"
    r"|side ?note"
    r"|follow[- ]?up (?:task|item|ticket)"
    r"|add (?:a )?follow[- ]?up"
    r"|flag (?:it|this|that))\b",
    re.IGNORECASE,
)
_BTW = re.compile(r"\b(?:btw|by the way)\b", re.IGNORECASE)


def match(prompt: str) -> str | None:
    if not isinstance(prompt, str):
        return None
    if _PARK.search(prompt):
        return "park"
    if _BTW.search(prompt):
        return "btw"
    return None
