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
  - Bash pipelines whose output is unbounded by construction: a read/search
    binary (cat, rg, grep, find, awk, sed) or a bulk SCM view (git diff/show/
    log, jj log/diff/show, gh pr view/diff) with no limiter (`| head`,
    `| tail`, `| wc`, grep -c/-l), no compact flag (--stat, --name-only,
    --oneline, -n N, --json ...), and no downstream consumer. Leading
    `cd X &&`, `VAR=... ;`, `echo ...;` and loop keywords are seen through,
    so `cd repo && git diff a b -- f` is judged on the diff.

What is never gated:
  - Subagent (sidechain) tool calls — subagents are the delegates
  - Targeted reads (offset+limit), compact greps, Glob
  - Bash that writes (redirect, heredoc, sed -i, find -delete/-exec), that is
    bounded (head/tail/wc/sed -n small range, --stat, -n N), or that feeds a
    non-filter program (`cat f | python3 x.py`)
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
  DELEGATION_GATE_ARM_PCT    context percent at which the gate arms (default 50,
                             the first context-watch band; it started at 70 but a
                             transcript audit showed the 50% nudge alone produced
                             no dispatches, so advice and teeth now arrive together)
  DELEGATION_GATE_ROUNDTRIPS free bulk round-trips per turn when armed (default 3)
  CONTEXT_WATCH_WINDOW       shared with context-watch: when set, used verbatim;
                             otherwise the budget is min(model window, 250k) via
                             context-watch's effective_window() (200k fallback
                             if the helper can't load — stricter, never laxer)
  CONTEXT_WATCH_BANDS        shared with context-watch (default 50,70,85; only
                             the last band is read here, for the harsh tier)
"""
import importlib.util
import json
import os
import re
import shlex
import sys

TAIL_BYTES = 2 * 1024 * 1024
FREE_READ_LINES = 250
# Binaries whose default output is the whole input.
READ_BINS = {"cat", "tac", "rg", "grep", "egrep", "fgrep", "find", "awk", "sed",
             "bat", "less", "more", "strings"}
# SCM views whose default output is unbounded (a whole-file diff, a full log).
READ_SUBCMDS = {("git", "diff"), ("git", "show"), ("git", "log"),
                ("jj", "log"), ("jj", "diff"), ("jj", "show"), ("jj", "op", "log"),
                ("gh", "pr", "view"), ("gh", "pr", "diff")}
READ_SUBCMDS_BY_BIN = {}
for _k in READ_SUBCMDS:
    READ_SUBCMDS_BY_BIN.setdefault(_k[0], []).append(_k)
# A pipeline containing one of these is bounded regardless of what feeds it.
LIMITERS = {"head", "tail", "wc", "md5sum", "sha1sum", "sha256sum", "cksum"}
# Text filters: a pipeline ending in one of these still emits the (filtered)
# stream. Anything else at the tail is a consumer and the pipeline is exempt.
FILTERS = READ_BINS | {"sort", "uniq", "cut", "tr", "jq", "yq", "xargs", "tee",
                       "column", "paste", "nl", "rev", "fold", "fmt", "expand",
                       "unexpand"}
# Flags that make an SCM view or a grep compact on their own.
COMPACT_FLAGS_RE = re.compile(
    r"(?:^|\s)(?:--stat|--shortstat|--numstat|--dirstat|--name-only|--name-status"
    r"|--oneline|--no-patch|--summary|--check|--quiet|--exit-code|--json|--jq"
    r"|--count|--files-with-matches|--files-without-match|--max-count(?:=|\s)\d+"
    r"|--limit(?:=|\s)\d+|-[A-Za-z]*[cLlqs][A-Za-z]*|-m\s*\d+|-n\s*\d+|-\d+)(?=\s|$)"
)
WRITE_REDIRECT_RE = re.compile(r"(?<![<>\d])>{1,2}(?!&)")
SED_RANGE_RE = re.compile(r"(\d+),(\d+)\s*p\b")
SHELL_PREFIX_RE = re.compile(
    r"^(?:(?:[A-Za-z_][A-Za-z0-9_]*=\S*|do|then|else|elif|if|while|until|!"
    r"|time|command|builtin|nice|sudo|env)\s+)+"
)


def split_unquoted(text, seps):
    """Split on any of `seps` outside single/double quotes; drop heredoc bodies."""
    out, buf, quote, i = [], [], None, 0
    lines = text.split("\n")
    kept = []
    skip_until = None
    for line in lines:
        if skip_until is not None:
            if line.strip() == skip_until:
                skip_until = None
            continue
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        if m:
            skip_until = m.group(1)
        kept.append(line)
    text = "\n".join(kept)
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"' and i + 1 < len(text):
                i += 1
                buf.append(text[i])
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        matched = next((s for s in seps if text.startswith(s, i)), None)
        if matched:
            out.append("".join(buf))
            buf = []
            i += len(matched)
            continue
        buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [seg.strip() for seg in out if seg.strip()]


def command_words(segment):
    """The command name and its arguments, minus env assignments and shell keywords."""
    seg = SHELL_PREFIX_RE.sub("", segment.strip())
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return seg.split()


def pipeline_is_bulk(pipeline):
    stages = split_unquoted(pipeline, ["|"])
    if not stages:
        return False
    if WRITE_REDIRECT_RE.search(pipeline):
        return False  # writes somewhere; whatever reaches context is small
    heads = []
    for stage in stages:
        words = command_words(stage)
        if not words:
            return False
        heads.append(words)
    first = heads[0]
    name = os.path.basename(first[0])
    args = " ".join(first[1:])
    if name in READ_SUBCMDS_BY_BIN:
        sub = tuple(first[: 1 + max(len(k) - 1 for k in READ_SUBCMDS_BY_BIN[name])])
        if not any(sub[: len(k)] == k for k in READ_SUBCMDS_BY_BIN[name]):
            return False
    elif name not in READ_BINS:
        return False
    if (name, first[1] if len(first) > 1 else "") == ("jj", "log") and not re.search(
        r"(?:^|\s)(?:-r|--revisions)(?:=|\s)", args
    ):
        return False
    if name == "sed":
        if re.search(r"(?:^|\s)(?:-i|--in-place)", args):
            return False
        m = SED_RANGE_RE.search(args)
        if m and int(m.group(2)) - int(m.group(1)) <= FREE_READ_LINES:
            return False
        if re.search(r"(?:^|\s)-n\s+'?\d+p'?", args):
            return False
    if name == "find" and re.search(r"\s-(?:delete|exec|execdir|ok|okdir)\b", args):
        return False
    if COMPACT_FLAGS_RE.search(args):
        return False
    for words in heads[1:]:
        tail_name = os.path.basename(words[0])
        if tail_name in LIMITERS:
            return False
        if tail_name in ("grep", "rg", "egrep") and COMPACT_FLAGS_RE.search(
            " ".join(words[1:])
        ):
            return False
    last = os.path.basename(heads[-1][0])
    if len(heads) > 1 and last not in FILTERS:
        return False  # a consumer program, not a dump into context
    return True


def bash_is_bulk_read(command):
    """True if any pipeline in `command` dumps unbounded output into context."""
    try:
        for segment in split_unquoted(command, ["&&", "||", ";", "\n"]):
            if pipeline_is_bulk(segment):
                return True
        return False
    except Exception:
        return False  # ambiguity fails open


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
        return bash_is_bulk_read(tool_input.get("command", ""))
    return False


def compute_budget(model):
    """min(model window, 250k) via context-watch's helper; env override wins."""
    override = os.environ.get("CONTEXT_WATCH_WINDOW")
    if override:
        return int(override)
    try:
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "context-watch.py"
        )
        spec = importlib.util.spec_from_file_location("context_watch", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return min(mod.effective_window(model), mod.BUDGET_CAP)
    except Exception:
        return 200_000


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
    model = None
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
                model = entry.get("message", {}).get("model")
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

    window = compute_budget(model)
    bands = sorted(
        int(b) for b in os.environ.get("CONTEXT_WATCH_BANDS", "50,70,85").split(",")
    )
    arm_pct = int(os.environ.get("DELEGATION_GATE_ARM_PCT", "50"))
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
        f"read targeted — Read with offset+limit ≤{FREE_READ_LINES} lines, Grep "
        "with head_limit, or in Bash a compact form (`--stat`/`--name-only`, "
        "`-n N`, `| head -50`, `sed -n 'a,bp'` over a small range) — which stays "
        "allowed; or (c) if this session is wrapping up, write the handover and "
        "respawn instead. "
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
