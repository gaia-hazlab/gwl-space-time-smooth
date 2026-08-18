#!/usr/bin/env python3
"""
gaia_trace.py — turn a Claude Code stream-json transcript into an agent call
graph, a readable transcript, and a standalone HTML dashboard.

Accepts either
  * stdout of `claude -p --output-format stream-json --verbose`, or
  * a session file from ~/.claude/projects/<encoded-cwd>/<session-id>.jsonl

Usage
  python gaia_trace.py run.jsonl --inspect
  python gaia_trace.py run.jsonl --html run.html --md run.md --mermaid run.mmd
  python gaia_trace.py run.jsonl --records records.jsonl --issue 42 \
      --repo owner/name --outcome pass

Schema notes (Claude Code stream-json):
  system/init   -> session_id, model, cwd, tools[], mcp_servers[], permissionMode
  assistant     -> message.content[] blocks: text | thinking | tool_use
  user          -> message.content[] blocks: tool_result (tool_use_id, is_error)
  result        -> total_cost_usd, duration_ms, num_turns, usage, result
  parent_tool_use_id on assistant/user messages attributes them to a subagent;
  the spawning event is a tool_use block named "Task".
Field names are read defensively — run --inspect first on a real transcript.
"""

import argparse
import html
import json
import os
import re
import sys
from collections import Counter, OrderedDict

TASK_TOOLS = {"Task", "Agent", "dispatch_agent"}


# ----------------------------------------------------------------- parsing


def load(path):
    """Read JSONL, skipping blank and unparseable lines."""
    events, bad = [], 0
    stream = sys.stdin if path == "-" else open(path, "r", encoding="utf-8")
    try:
        for i, line in enumerate(stream):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if isinstance(obj, dict):
                obj["_ord"] = i
                events.append(obj)
    finally:
        if stream is not sys.stdin:
            stream.close()
    return events, bad


def blocks(ev):
    """Content blocks of an assistant/user event, whatever the nesting."""
    msg = ev.get("message") or {}
    content = msg.get("content", ev.get("content"))
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def text_of(block):
    if "text" in block:
        return block["text"] or ""
    if "thinking" in block:
        return block["thinking"] or ""
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(p.get("text", "") for p in c if isinstance(p, dict))
    return ""


def parse(events):
    """Build the agent tree plus a flat, ordered step list."""
    session = {
        "session_id": None, "model": None, "cwd": None, "permission_mode": None,
        "tools": [], "mcp_servers": [], "cost_usd": None, "duration_ms": None,
        "num_turns": None, "result": None, "is_error": None,
        "input_tokens": 0, "output_tokens": 0,
    }

    agents = OrderedDict()
    agents["root"] = {
        "id": "root", "parent": None, "name": "main session",
        "subagent_type": None, "prompt": None, "steps": [], "spawned": [],
        "depth": 0, "first": 0, "last": 0,
    }
    pending_tools = {}   # tool_use_id -> (agent_id, step_index)

    for ev in events:
        etype = ev.get("type")
        ordinal = ev["_ord"]
        ts = ev.get("timestamp")

        if etype == "system" and ev.get("subtype") == "init":
            for src, dst in (("session_id", "session_id"), ("model", "model"),
                             ("cwd", "cwd"), ("permissionMode", "permission_mode")):
                if ev.get(src) is not None:
                    session[dst] = ev[src]
            session["tools"] = ev.get("tools") or session["tools"]
            session["mcp_servers"] = ev.get("mcp_servers") or session["mcp_servers"]
            continue

        if etype == "result":
            session["cost_usd"] = ev.get("total_cost_usd", session["cost_usd"])
            session["duration_ms"] = ev.get("duration_ms", session["duration_ms"])
            session["num_turns"] = ev.get("num_turns", session["num_turns"])
            session["result"] = ev.get("result", session["result"])
            session["is_error"] = ev.get("is_error", session["is_error"])
            continue

        if etype not in ("assistant", "user"):
            continue  # stream_event, compact_boundary, and anything unknown

        parent = ev.get("parent_tool_use_id") or (ev.get("message") or {}).get(
            "parent_tool_use_id")
        agent_id = parent if parent in agents else ("root" if not parent else parent)
        if agent_id not in agents:
            # a subagent whose spawning Task block has not been seen yet
            agents[agent_id] = {
                "id": agent_id, "parent": "root", "name": "subagent",
                "subagent_type": None, "prompt": None, "steps": [],
                "spawned": [], "depth": 1, "first": ordinal, "last": ordinal,
            }
            agents["root"]["spawned"].append(agent_id)
        agent = agents[agent_id]
        agent["last"] = ordinal

        usage = (ev.get("message") or {}).get("usage") or {}
        session["input_tokens"] += usage.get("input_tokens", 0) or 0
        session["output_tokens"] += usage.get("output_tokens", 0) or 0

        for b in blocks(ev):
            btype = b.get("type")

            if btype in ("text", "thinking"):
                body = text_of(b).strip()
                if body:
                    agent["steps"].append({
                        "kind": btype, "ord": ordinal, "ts": ts, "text": body})

            elif btype == "tool_use":
                name = b.get("name", "?")
                tid = b.get("id")
                inp = b.get("input") or {}
                step = {"kind": "tool_use", "ord": ordinal, "ts": ts,
                        "tool": name, "tool_use_id": tid, "input": inp,
                        "result": None, "is_error": None, "spawns": None}
                agent["steps"].append(step)
                if tid:
                    pending_tools[tid] = (agent_id, len(agent["steps"]) - 1)

                if name in TASK_TOOLS and tid:
                    label = (inp.get("subagent_type") or inp.get("agent_type")
                             or inp.get("description") or "subagent")
                    placeholder = agents.get(tid)
                    if placeholder is not None:
                        # A placeholder was created above (its own events arrived
                        # before this, its spawning Task block, due to a
                        # reordered/corrupted transcript) -- update it in place so
                        # its already-collected steps aren't lost, and move it out
                        # of the placeholder parent's spawned list into its real
                        # one (it must appear exactly once in the tree).
                        old_parent = agents.get(placeholder["parent"])
                        if old_parent and placeholder["id"] in old_parent["spawned"]:
                            old_parent["spawned"].remove(placeholder["id"])
                        placeholder.update(
                            name=str(label), subagent_type=inp.get("subagent_type"),
                            prompt=inp.get("prompt") or inp.get("description"),
                            parent=agent_id, depth=agent["depth"] + 1)
                    else:
                        agents[tid] = {
                            "id": tid, "parent": agent_id, "name": str(label),
                            "subagent_type": inp.get("subagent_type"),
                            "prompt": inp.get("prompt") or inp.get("description"),
                            "steps": [], "spawned": [], "depth": agent["depth"] + 1,
                            "first": ordinal, "last": ordinal,
                        }
                    agent["spawned"].append(tid)
                    step["spawns"] = tid

            elif btype == "tool_result":
                tid = b.get("tool_use_id")
                loc = pending_tools.get(tid)
                if loc:
                    owner, idx = loc
                    s = agents[owner]["steps"][idx]
                    s["result"] = text_of(b).strip()
                    s["is_error"] = bool(b.get("is_error"))

    return session, agents


# --------------------------------------------------------- shared counts


def walk_order(agents):
    """Agent ids in spawn-tree order (root first, then each subtree)."""
    order = []

    def walk(aid):
        order.append(aid)
        for c in agents[aid]["spawned"]:
            walk(c)
    walk("root")
    return order


def agent_tool_stats(a):
    """(tools Counter, total calls, error count) for one agent's steps."""
    tools = Counter(s["tool"] for s in a["steps"] if s["kind"] == "tool_use")
    errs = sum(1 for s in a["steps"] if s["kind"] == "tool_use" and s["is_error"])
    return tools, sum(tools.values()), errs


def agent_rows(agents):
    """(name, calls, errors, tools) per agent in spawn order.

    The root is reported as "main" here (rather than "main session", used
    elsewhere) so this lines up with gaia_ticker.py's live table, which has
    no way to know the root's display name ahead of time.
    """
    rows = []
    for aid in walk_order(agents):
        a = agents[aid]
        name = "main" if aid == "root" else a["name"]
        tools, calls, errs = agent_tool_stats(a)
        rows.append((name, calls, errs, tools))
    return rows


def format_counts_table(rows):
    """Render (name, calls, errors, tools) rows as a fixed-width text table
    with a trailing total row. Shared by gaia_trace.py --counts and the
    closing summary in gaia_ticker.py, so both report identical layouts."""
    name_w = max([len("agent")] + [len(r[0]) for r in rows]) if rows else len("agent")
    header = "{:<{w}}  {:>6}  {:>6}  {}".format(
        "agent", "calls", "errors", "tools", w=name_w)
    rule = "-" * len(header)
    lines = [header, rule]
    total_calls = total_errors = 0
    total_tools = Counter()
    for name, calls, errs, tools in rows:
        tool_str = ", ".join(f"{t} x{n}" for t, n in tools.most_common())
        lines.append("{:<{w}}  {:>6}  {:>6}  {}".format(
            name, calls, errs, tool_str, w=name_w))
        total_calls += calls
        total_errors += errs
        total_tools.update(tools)
    lines.append(rule)
    tool_str = ", ".join(f"{t} x{n}" for t, n in total_tools.most_common())
    lines.append("{:<{w}}  {:>6}  {:>6}  {}".format(
        "total", total_calls, total_errors, tool_str, w=name_w))
    return "\n".join(lines)


# ------------------------------------------------------------ inspection


def inspect(events):
    types, tools, subagents, keys = Counter(), Counter(), Counter(), Counter()
    for ev in events:
        types[f'{ev.get("type")}/{ev.get("subtype", "-")}'] += 1
        keys.update(k for k in ev if not k.startswith("_"))
        for b in blocks(ev):
            if b.get("type") == "tool_use":
                tools[b.get("name", "?")] += 1
                if b.get("name") in TASK_TOOLS:
                    inp = b.get("input") or {}
                    subagents[str(inp.get("subagent_type")
                                  or inp.get("description", "?"))[:60]] += 1
    print(f"events: {len(events)}\n")
    print("event type/subtype:")
    for k, v in types.most_common():
        print(f"  {v:6d}  {k}")
    print("\ntop-level keys seen:")
    for k, v in keys.most_common():
        print(f"  {v:6d}  {k}")
    print("\ntools called:")
    for k, v in tools.most_common():
        print(f"  {v:6d}  {k}")
    if subagents:
        print("\nsubagents spawned:")
        for k, v in subagents.most_common():
            print(f"  {v:6d}  {k}")
    else:
        print("\nsubagents spawned: none detected "
              f"(looked for tool names {sorted(TASK_TOOLS)})")


# -------------------------------------------------------------- renderers


def mermaid(session, agents):
    lines = ["graph TD"]
    for aid, a in agents.items():
        node = "root" if aid == "root" else "a_" + aid.replace("-", "_")[-12:]
        tools = Counter(s["tool"] for s in a["steps"] if s["kind"] == "tool_use")
        detail = ", ".join(f"{t}x{n}" for t, n in tools.most_common(4)) or "no tools"
        lines.append(f'  {node}["{a["name"]}<br/><small>{detail}</small>"]')
        if a["parent"]:
            p = "root" if a["parent"] == "root" else "a_" + a["parent"].replace("-", "_")[-12:]
            lines.append(f"  {p} --> {node}")
    return "\n".join(lines)


def markdown(session, agents):
    out = ["# Agent run transcript", ""]
    out.append(f"- session: `{session['session_id']}`")
    out.append(f"- model: `{session['model']}`  cwd: `{redact_paths(str(session['cwd']))}`")
    if session["cost_usd"] is not None:
        out.append(f"- cost: ${session['cost_usd']:.4f}  "
                   f"turns: {session['num_turns']}  "
                   f"duration: {(session['duration_ms'] or 0)/1000:.1f}s")
    out.append("")

    def emit(aid, indent=0):
        a = agents[aid]
        pad = "  " * indent
        out.append(f"{pad}## {a['name']}" if indent == 0 else f"{pad}### {a['name']}")
        if a["prompt"]:
            out.append(f"{pad}> {a['prompt'][:400]}")
        out.append("")
        for s in a["steps"]:
            if s["kind"] == "thinking":
                out.append(f"{pad}*[reasoning]* {redact(s['text'][:1500])}")
            elif s["kind"] == "text":
                out.append(f"{pad}{redact(s['text'][:2000])}")
            else:
                arg = json.dumps(redact_value(s["input"]),
                                  ensure_ascii=False)[:200]
                flag = " **ERROR**" if s["is_error"] else ""
                out.append(f"{pad}- `{s['tool']}`{flag} `{arg}`")
                if s["result"]:
                    out.append(f"{pad}  ↳ {redact(s['result'][:400])}")
            out.append("")
        for child in a["spawned"]:
            emit(child, indent + 1)

    emit("root")
    if session["result"]:
        out += ["## Final result", "", redact(session["result"])]
    return "\n".join(out)


PALETTE = ["#5FB0C4", "#D9A441", "#B27CC4", "#7FB069", "#D97A7A", "#8892C7"]

# Best-effort scrub of common secret shapes from anything embedded in output
# that may end up published (dashboard.html goes to GitHub Pages via
# gaia_run_queue.sh). Not a guarantee -- the real fix is never putting a
# secret in a command, a file an agent writes, or its own reasoning/response
# -- but it catches the common accidental-token cases: a curl/git-remote
# command, an agent hardcoding a key while editing a config file, or an agent
# echoing a value back in its own text. Applied to EVERY string in a tool's
# input (not just Bash's "command") and to agent text, since a key can show
# up in a Write's content, an Edit's old/new string, or reasoning, not only
# a shell command.
_KEY_LABEL = r'(?i)\b(api[_-]?key|access[_-]?token|secret|password|passwd|auth(?:orization)?)'
_SECRET_PATTERNS = [
    re.compile(_KEY_LABEL + r'(["\']?\s*[:=]\s*["\']?)(bearer\s+)?\S+'),
    re.compile(r'(?i)\bbearer\s+\S+'),
    re.compile(r'sk-[A-Za-z0-9_-]{10,}'),           # Anthropic/OpenAI-style
    re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}'),      # GitHub tokens
    re.compile(r'AKIA[0-9A-Z]{16}'),                # AWS access key id
    re.compile(r'xox[baprs]-[A-Za-z0-9-]{10,}'),    # Slack tokens
    re.compile(r'AIza[0-9A-Za-z_-]{35}'),           # Google API key
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----'),
    re.compile(r'(https?://)[^:/\s]+:[^@/\s]+@'),  # userinfo embedded in a URL
]


# Home directories are not secrets, but dashboard.html IS published to GitHub
# Pages, and every absolute path in a transcript discloses the operator's
# username and the machine's directory layout to anyone reading the site. A
# single run can embed hundreds of them. Rewrite absolute paths to repo-relative
# ones so the published page says `src/models/observability.py` rather than
# `/home/<someone>/gwl-space-time-smooth/src/models/observability.py`.
_HOME_PATTERNS = [
    re.compile(r'/(?:home|Users)/[^/\s"\'<>:;,)\]]+/([A-Za-z0-9._-]+)'),  # /home/<user>/<repo>
    re.compile(r'/(?:home|Users)/[^/\s"\'<>:;,)\]]+'),                    # bare /home/<user>
]


def redact_paths(text):
    """Strip operator home directories from anything published."""
    if not isinstance(text, str):
        return text
    out = _HOME_PATTERNS[0].sub(r'~/\1', text)
    return _HOME_PATTERNS[1].sub('~', out)


def redact(text):
    if not isinstance(text, str):
        return text
    out = text
    out = _SECRET_PATTERNS[0].sub(r'\1\2[REDACTED]', out)
    for pat in _SECRET_PATTERNS[1:6]:
        out = pat.sub('[REDACTED]', out)
    out = _SECRET_PATTERNS[6].sub('[REDACTED]', out)
    out = _SECRET_PATTERNS[7].sub('[REDACTED]', out)
    out = _SECRET_PATTERNS[8].sub(r'\1[REDACTED]@', out)
    return redact_paths(out)


def redact_value(value):
    """Recursively scrub every string in a JSON-like value (a tool_use's
    input, whatever its shape) -- a secret can land in any field of any
    tool, not just Bash's "command"."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    return value


def dashboard(session, agents, source_name):
    order = walk_order(agents)

    lo = min(a["first"] for a in agents.values())
    hi = max(a["last"] for a in agents.values())
    span = max(hi - lo, 1)

    def pct(o):
        return (o - lo) / span * 100

    rows, cards = [], []
    for i, aid in enumerate(order):
        a = agents[aid]
        color = PALETTE[i % len(PALETTE)]
        tools, calls, errs = agent_tool_stats(a)
        ticks = []
        for s in a["steps"]:
            if s["kind"] != "tool_use":
                continue
            cls = "tick err" if s["is_error"] else (
                "tick spawn" if s["spawns"] else "tick")
            arg = json.dumps(redact_value(s["input"]),
                              ensure_ascii=False)[:180]
            ticks.append(
                f'<span class="{cls}" style="left:{pct(s["ord"]):.3f}%" '
                f'title="{html.escape(s["tool"] + "  " + arg, quote=True)}"></span>')
        bar = (f'<span class="span" style="left:{pct(a["first"]):.3f}%;'
               f'width:{max(pct(a["last"]) - pct(a["first"]), 0.4):.3f}%;'
               f'background:{color}"></span>')
        rows.append(
            f'<div class="chan" style="--c:{color}">'
            f'<div class="chan-label" style="padding-left:{a["depth"] * 18}px">'
            f'<span class="dot"></span>{html.escape(a["name"])} '
            f'<span class="count">({calls})</span></div>'
            f'<div class="chan-track">{bar}{"".join(ticks)}</div></div>')

        thinking = sum(1 for s in a["steps"] if s["kind"] == "thinking")
        chips = "".join(f'<li><b>{v}</b>{html.escape(t)}</li>'
                        for t, v in tools.most_common())
        log = []
        for s in a["steps"]:
            if s["kind"] == "tool_use":
                arg = json.dumps(redact_value(s["input"]),
                                  ensure_ascii=False)[:220]
                log.append(f'<div class="ln t{" err" if s["is_error"] else ""}">'
                           f'<code>{html.escape(s["tool"])}</code>'
                           f'<span>{html.escape(arg)}</span></div>')
            else:
                tag = "reasoning" if s["kind"] == "thinking" else "says"
                log.append(f'<div class="ln {s["kind"]}"><em>{tag}</em>'
                           f'<span>{html.escape(redact(s["text"])[:600])}</span></div>')
        cards.append(
            f'<details class="agent" style="--c:{color}"{" open" if aid == "root" else ""}>'
            f'<summary><span class="dot"></span>'
            f'<b>{html.escape(a["name"])}</b>'
            f'<span class="meta">{sum(tools.values())} tool calls · '
            f'{thinking} reasoning blocks · {errs} errors</span></summary>'
            f'<ul class="chips">{chips}</ul>'
            f'<div class="log">{"".join(log)}</div></details>')

    def stat(label, value):
        return (f'<div class="stat"><span class="k">{label}</span>'
                f'<span class="v">{value}</span></div>')

    cost = f"${session['cost_usd']:.4f}" if session["cost_usd"] is not None else "—"
    dur = (f"{session['duration_ms']/1000:.1f}s"
           if session["duration_ms"] is not None else "—")
    stats = "".join([
        stat("agents", len(agents)),
        stat("tool calls", sum(1 for a in agents.values()
                               for s in a["steps"] if s["kind"] == "tool_use")),
        stat("turns", session["num_turns"] if session["num_turns"] is not None else "—"),
        stat("cost", cost),
        stat("wall clock", dur),
        stat("tokens in / out",
             f"{session['input_tokens']:,} / {session['output_tokens']:,}"),
    ])

    final = (f'<section class="final"><h2>Final result</h2><pre>'
             f'{html.escape(redact(session["result"]))}</pre></section>'
             if session.get("result") else "")

    return TEMPLATE.format(
        source=html.escape(source_name),
        session=html.escape(str(session["session_id"])),
        model=html.escape(str(session["model"])),
        cwd=html.escape(redact_paths(str(session["cwd"]))),
        stats=stats, rows="".join(rows), cards="".join(cards), final=final)


TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent run — {source}</title>
<style>
  :root {{
    --ink:#0C141C; --panel:#131F2A; --line:#22313F;
    --fg:#DCE6EE; --dim:#7E93A5; --hair:#1B2A36;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--ink); color:var(--fg);
    font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:40px 24px 80px; }}
  h1 {{ font-family:"Iowan Old Style",Palatino,Georgia,serif;
    font-size:34px; font-weight:600; letter-spacing:-.015em; margin:0 0 6px; }}
  h2 {{ font-family:"Iowan Old Style",Palatino,Georgia,serif;
    font-size:19px; font-weight:600; margin:0 0 14px; }}
  .sub {{ color:var(--dim); font-family:ui-monospace,Menlo,Consolas,monospace;
    font-size:12.5px; margin-bottom:28px; }}
  .sub span {{ margin-right:18px; }}
  .stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
    gap:1px; background:var(--hair); border:1px solid var(--hair);
    margin-bottom:34px; }}
  .stat {{ background:var(--panel); padding:14px 16px; }}
  .stat .k {{ display:block; color:var(--dim); font-size:11px;
    text-transform:uppercase; letter-spacing:.09em; }}
  .stat .v {{ display:block; font-family:ui-monospace,Menlo,monospace;
    font-size:19px; margin-top:4px; }}
  section {{ margin-bottom:38px; }}
  /* record section */
  .chan {{ display:grid; grid-template-columns:230px 1fr; align-items:center;
    gap:14px; padding:5px 0; }}
  .chan-label {{ font-family:ui-monospace,Menlo,monospace; font-size:12px;
    color:var(--fg); white-space:nowrap; overflow:hidden;
    text-overflow:ellipsis; }}
  .chan-label .count {{ color:var(--dim); }}
  .dot {{ display:inline-block; width:7px; height:7px; border-radius:50%;
    background:var(--c); margin-right:7px; vertical-align:middle; }}
  .chan-track {{ position:relative; height:22px;
    border-bottom:1px solid var(--hair); }}
  .span {{ position:absolute; top:10px; height:2px; opacity:.5; }}
  .tick {{ position:absolute; top:4px; width:2px; height:14px;
    background:var(--c); cursor:help; }}
  .tick.spawn {{ height:20px; top:1px; width:3px; }}
  .tick.err {{ background:#E4574C; height:20px; top:1px; }}
  .axis {{ display:flex; justify-content:space-between; color:var(--dim);
    font-family:ui-monospace,Menlo,monospace; font-size:11px;
    margin:6px 0 0 244px; }}
  /* agent cards */
  .agent {{ border:1px solid var(--hair); border-left:3px solid var(--c);
    background:var(--panel); margin-bottom:10px; }}
  .agent summary {{ cursor:pointer; padding:12px 16px; list-style:none;
    display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .agent summary::-webkit-details-marker {{ display:none; }}
  .agent .meta {{ color:var(--dim); font-size:12px; margin-left:auto;
    font-family:ui-monospace,Menlo,monospace; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:6px; list-style:none;
    margin:0; padding:0 16px 12px; }}
  .chips li {{ font-family:ui-monospace,Menlo,monospace; font-size:11px;
    color:var(--dim); border:1px solid var(--line); padding:2px 7px; }}
  .chips b {{ color:var(--c); margin-right:5px; }}
  .log {{ border-top:1px solid var(--hair); max-height:420px; overflow:auto; }}
  .ln {{ display:flex; gap:10px; padding:7px 16px;
    border-bottom:1px solid var(--hair); font-size:13px; }}
  .ln code {{ font-family:ui-monospace,Menlo,monospace; font-size:12px;
    color:var(--c); flex:0 0 auto; }}
  .ln em {{ font-style:normal; color:var(--dim); font-size:11px;
    text-transform:uppercase; letter-spacing:.08em; flex:0 0 78px; }}
  .ln span {{ color:var(--dim); overflow-wrap:anywhere; }}
  .ln.text span {{ color:var(--fg); }}
  .ln.err code {{ color:#E4574C; }}
  .final pre {{ background:var(--panel); border:1px solid var(--hair);
    padding:16px; overflow:auto; white-space:pre-wrap; font-size:13px; }}
  @media (max-width:700px) {{ .chan {{ grid-template-columns:150px 1fr; }}
    .axis {{ margin-left:164px; }} }}
</style>
<div class="wrap">
  <h1>Agent run</h1>
  <div class="sub"><span>{source}</span><span>{model}</span>
    <span>{session}</span><span>{cwd}</span></div>
  <div class="stats">{stats}</div>

  <section>
    <h2>Record section</h2>
    <div class="chans">{rows}</div>
    <div class="axis"><span>run start</span><span>event sequence</span>
      <span>run end</span></div>
  </section>

  <section>
    <h2>Agents</h2>
    {cards}
  </section>

  {final}
</div>
"""


# -------------------------------------------------------------- records


def record(session, agents, args):
    """One trajectory plus its outcome labels, for a training corpus."""
    def flat(aid):
        a = agents[aid]
        return {
            "agent": a["name"], "subagent_type": a["subagent_type"],
            "prompt": a["prompt"],
            "steps": [{k: v for k, v in s.items() if k != "ord"} for s in a["steps"]],
            "children": [flat(c) for c in a["spawned"]],
        }

    meta = {}
    if args.meta and os.path.exists(args.meta):
        try:
            with open(args.meta, encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"note: could not read {args.meta}: {e}", file=sys.stderr)

    tools = Counter(s["tool"] for a in agents.values()
                    for s in a["steps"] if s["kind"] == "tool_use")
    subagents = [a["name"] for aid, a in agents.items() if aid != "root"]

    rec = {
        # identity
        "run_id": meta.get("run_id"),
        "session_id": session["session_id"],
        "model": session["model"],
        "claude_version": meta.get("claude_version"),
        # task
        "repo": meta.get("repo", args.repo),
        "issue": meta.get("issue", args.issue),
        "issue_title": meta.get("issue_title"),
        "git_rev": meta.get("git_rev"),
        "prompt": None,
        # outcome labels — the reward signal
        "outcome": meta.get("outcome", args.outcome),
        "test_cmd": meta.get("test_cmd"),
        "test_rc": meta.get("test_rc"),
        "claude_rc": meta.get("claude_rc"),
        "diff_lines": meta.get("diff_lines"),
        "files_touched": meta.get("files_touched"),
        # cost and shape
        "cost_usd": session["cost_usd"],
        "num_turns": session["num_turns"],
        "duration_ms": session["duration_ms"],
        "wall_s": meta.get("wall_s"),
        "input_tokens": session["input_tokens"],
        "output_tokens": session["output_tokens"],
        "n_agents": len(agents),
        "subagents": subagents,
        "tool_histogram": dict(tools),
        "n_tool_calls": sum(tools.values()),
        "n_tool_errors": sum(1 for a in agents.values() for s in a["steps"]
                             if s["kind"] == "tool_use" and s["is_error"]),
        "n_reasoning_blocks": sum(1 for a in agents.values()
                                  for s in a["steps"] if s["kind"] == "thinking"),
        # payload
        "final_result": session["result"],
        "artifacts_dir": meta.get("dir"),
        "trajectory": flat("root"),
    }
    d = meta.get("dir")
    if d:
        p = os.path.join(d, "prompt.txt")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                rec["prompt"] = f.read().strip()
    return rec


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("jsonl", help="stream-json transcript, or - for stdin")
    p.add_argument("--inspect", action="store_true",
                   help="report event types, tools, and subagents, then exit")
    p.add_argument("--counts", action="store_true",
                   help="print the per-agent call/error/tool summary table, then exit")
    p.add_argument("--html", metavar="FILE")
    p.add_argument("--md", metavar="FILE")
    p.add_argument("--mermaid", metavar="FILE")
    p.add_argument("--records", metavar="FILE",
                   help="append one trajectory record (JSONL) for training use")
    p.add_argument("--meta", metavar="FILE",
                   help="meta.json from gaia-run.sh; merged into the record")
    p.add_argument("--repo"), p.add_argument("--issue")
    p.add_argument("--outcome", help="e.g. pass, fail, needs-review")
    args = p.parse_args()

    events, bad = load(args.jsonl)
    if bad:
        print(f"note: skipped {bad} unparseable line(s)", file=sys.stderr)
    if not events:
        sys.exit("no events found")

    if args.inspect:
        inspect(events)
        return

    session, agents = parse(events)

    if args.counts:
        print(format_counts_table(agent_rows(agents)))
        return

    if args.mermaid:
        open(args.mermaid, "w", encoding="utf-8").write(mermaid(session, agents))
    if args.md:
        open(args.md, "w", encoding="utf-8").write(markdown(session, agents))
    if args.html:
        open(args.html, "w", encoding="utf-8").write(
            dashboard(session, agents, os.path.basename(args.jsonl)))
    if args.records:
        with open(args.records, "a", encoding="utf-8") as f:
            f.write(json.dumps(record(session, agents, args),
                               ensure_ascii=False) + "\n")

    n_tools = sum(1 for a in agents.values()
                  for s in a["steps"] if s["kind"] == "tool_use")
    print(f"{len(agents)} agent(s), {n_tools} tool call(s), "
          f"{session['num_turns']} turn(s)", file=sys.stderr)
    for f in (args.html, args.md, args.mermaid, args.records):
        if f:
            print(f"wrote {f}", file=sys.stderr)


if __name__ == "__main__":
    main()
