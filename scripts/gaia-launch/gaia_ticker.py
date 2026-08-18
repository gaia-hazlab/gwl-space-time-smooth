#!/usr/bin/env python3
"""
gaia_ticker.py — stateful live ticker for a Claude Code stream-json transcript.

Sits between `claude -p --output-format stream-json --verbose` and `tee`:
passes stdin through to stdout unchanged, and writes a human-readable,
per-agent ticker to stderr as it goes.

Usage
  claude -p ... --output-format stream-json --verbose \
    | python3 gaia_ticker.py \
    | tee raw.jsonl >/dev/null

Subagent attribution: a `tool_use` block named Task spawns a subagent, and
its input.subagent_type carries the name. Every later assistant/user event
belonging to that subagent carries parent_tool_use_id equal to the spawning
call's id, so the name is recorded once, at spawn time, and looked up by id
from then on. Events with no parent_tool_use_id belong to the main agent.
"""

import json
import os
import sys
from collections import Counter, OrderedDict

# Needed when this module is imported (e.g. by tests) rather than run as a
# script, since only the latter puts this directory on sys.path automatically.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gaia_trace import TASK_TOOLS, format_counts_table  # noqa: E402

MAIN = "main"
COLORS = ["\033[36m", "\033[33m", "\033[35m", "\033[32m", "\033[31m", "\033[34m"]
RESET = "\033[0m"


def blocks_of(ev):
    """Content blocks of an assistant/user event, whatever the nesting."""
    msg = ev.get("message") or {}
    content = msg.get("content", ev.get("content"))
    return content if isinstance(content, list) else []


class Ticker:
    def __init__(self, color):
        self.color = color
        self.names = {}             # Task tool_use id -> agent name
        self.order = []             # first-seen order of agent names
        self.colors = {}            # agent name -> ANSI code
        self.calls = Counter()      # agent name -> tool call count
        self.errors = Counter()     # agent name -> tool error count
        self.tools = OrderedDict()  # agent name -> Counter(tool name -> count)

    def note(self, name):
        if name not in self.colors:
            self.order.append(name)
            self.colors[name] = COLORS[(len(self.order) - 1) % len(COLORS)]
            self.tools[name] = Counter()

    def tag(self, name):
        self.note(name)
        label = "[{} #{}]".format(name, self.calls[name])
        if self.color:
            return self.colors[name] + label + RESET
        return label

    def emit(self, name, text):
        print("  {} {}".format(self.tag(name), text), file=sys.stderr, flush=True)

    def agent_of(self, parent):
        if not parent:
            return MAIN
        return self.names.get(parent, "subagent")

    def process(self, ev):
        etype = ev.get("type")

        if etype == "system" and ev.get("subtype") == "init":
            print("session {}   model {}".format(
                ev.get("session_id"), ev.get("model")), file=sys.stderr, flush=True)
            return

        if etype == "result":
            print("-" * 60, file=sys.stderr, flush=True)
            print("done   {} turns   ${}   {}s".format(
                ev.get("num_turns"), ev.get("total_cost_usd"),
                (ev.get("duration_ms") or 0) / 1000), file=sys.stderr, flush=True)
            return

        if etype not in ("assistant", "user"):
            return  # stream_event, compact_boundary, and anything unknown

        parent = ev.get("parent_tool_use_id") or (ev.get("message") or {}).get(
            "parent_tool_use_id")
        name = self.agent_of(parent)

        if etype == "assistant":
            for b in blocks_of(ev):
                if not isinstance(b, dict):
                    continue
                btype = b.get("type")
                if btype == "tool_use":
                    tname = b.get("name", "?")
                    inp = b.get("input") or {}
                    self.note(name)
                    self.calls[name] += 1
                    self.tools[name][tname] += 1
                    arg = json.dumps(inp, ensure_ascii=False)[:90]
                    self.emit(name, "{}  {}".format(tname, arg))
                    tid = b.get("id")
                    if tname in TASK_TOOLS and tid:
                        label = (inp.get("subagent_type")
                                 or inp.get("description") or "subagent")
                        self.names[tid] = str(label)
                elif btype == "thinking":
                    body = (b.get("thinking") or "").replace("\n", " ").strip()[:110]
                    if body:
                        self.emit(name, "reasoning: {}".format(body))
                elif btype == "text":
                    body = (b.get("text") or "").replace("\n", " ").strip()[:110]
                    if body:
                        self.emit(name, body)

        elif etype == "user":
            for b in blocks_of(ev):
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                    self.note(name)
                    self.errors[name] += 1
                    self.emit(name, "↳ tool error")

    def summary_rows(self):
        return [(n, self.calls[n], self.errors[n], self.tools[n]) for n in self.order]

    def print_summary(self):
        print(file=sys.stderr)
        print(format_counts_table(self.summary_rows()), file=sys.stderr, flush=True)


def main():
    color = sys.stderr.isatty() and not os.environ.get("NO_COLOR")
    ticker = Ticker(color)

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    for raw in stdin:
        stdout.write(raw)
        stdout.flush()
        try:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            ev = json.loads(line)
            if not isinstance(ev, dict):
                continue
        except Exception:
            continue  # malformed or unrecognised line: skip, keep the run alive
        try:
            ticker.process(ev)
        except Exception:
            continue

    ticker.print_summary()


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:  # downstream stage (e.g. tee) closed early
        try:
            sys.stdout.close()
        finally:
            os._exit(0)
