#!/usr/bin/env python3
"""
gaia_corpus.py — manage the archive of agent runs produced by gaia-run.sh.

  python gaia_corpus.py index                 rebuild records.jsonl from run dirs
  python gaia_corpus.py stats                 outcome rates, cost, tool usage
  python gaia_corpus.py browse                write index.html over all runs
  python gaia_corpus.py export out.jsonl      eval-ready dataset
  python gaia_corpus.py export out.jsonl --format sft --outcome pass

Archive layout (created by gaia-run.sh):
  $GAIA_RUNS/
    records.jsonl                    one line per run, append-only
    index.html                       browsable table (gaia_corpus.py browse)
    <repo>/issue-<n>/<timestamp>/
      raw.jsonl  prompt.txt  meta.json  change.diff  tests.log
      dashboard.html  transcript.md  graph.mmd

records.jsonl is the working index and can be rebuilt at any time from the
run directories, which are the archive of record. Nothing here mutates a
raw.jsonl.
"""

import argparse
import glob
import html
import json
import os
import statistics
import subprocess
import sys
from collections import Counter, defaultdict

ROOT = os.environ.get("GAIA_RUNS", os.path.expanduser("~/gaia-runs"))


def load_records(root):
    path = os.path.join(root, "records.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


# ------------------------------------------------------------------- index


def cmd_index(args):
    """Rebuild records.jsonl by re-parsing every archived run."""
    here = os.path.dirname(os.path.abspath(__file__))
    trace = os.path.join(here, "gaia_trace.py")
    runs = sorted(glob.glob(os.path.join(args.root, "*", "issue-*", "*", "raw.jsonl")))
    if not runs:
        sys.exit(f"no runs found under {args.root}")

    out = os.path.join(args.root, "records.jsonl")
    if os.path.exists(out):
        backup = out + ".bak"
        os.replace(out, backup)
        print(f"previous index moved to {backup}")

    ok = fail = 0
    for raw in runs:
        d = os.path.dirname(raw)
        meta = os.path.join(d, "meta.json")
        cmd = [sys.executable, trace, raw, "--records", out]
        if os.path.exists(meta):
            cmd += ["--meta", meta]
        if args.rebuild_views:
            cmd += ["--html", os.path.join(d, "dashboard.html"),
                    "--md", os.path.join(d, "transcript.md"),
                    "--mermaid", os.path.join(d, "graph.mmd")]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            ok += 1
        else:
            fail += 1
            print(f"  failed: {d}\n    {r.stderr.strip()[:200]}", file=sys.stderr)
    print(f"indexed {ok} run(s), {fail} failure(s) -> {out}")


# ------------------------------------------------------------------- stats


def cmd_stats(args):
    recs = load_records(args.root)
    if not recs:
        sys.exit(f"no records in {args.root}; run 'index' first")

    outcomes = Counter(r.get("outcome") or "unknown" for r in recs)
    print(f"runs: {len(recs)}\n")
    print("outcome:")
    for k, v in outcomes.most_common():
        print(f"  {v:5d}  {v/len(recs)*100:5.1f}%  {k}")

    def nums(key):
        return [r[key] for r in recs
                if isinstance(r.get(key), (int, float))]

    print("\nper run:")
    for key, label, fmt in [
        ("cost_usd", "cost (USD)", "{:.4f}"),
        ("num_turns", "turns", "{:.1f}"),
        ("n_tool_calls", "tool calls", "{:.1f}"),
        ("n_tool_errors", "tool errors", "{:.1f}"),
        ("n_agents", "agents", "{:.1f}"),
        ("diff_lines", "diff lines", "{:.0f}"),
        ("wall_s", "wall clock (s)", "{:.0f}"),
    ]:
        v = nums(key)
        if not v:
            continue
        med = statistics.median(v)
        print(f"  {label:16s} median {fmt.format(med):>10s}   "
              f"total {fmt.format(sum(v)):>12s}")

    tools = Counter()
    for r in recs:
        tools.update(r.get("tool_histogram") or {})
    print("\ntool calls:")
    for k, v in tools.most_common(15):
        print(f"  {v:6d}  {k}")

    subs = Counter()
    for r in recs:
        subs.update(r.get("subagents") or [])
    if subs:
        print("\nsubagents:")
        for k, v in subs.most_common(15):
            print(f"  {v:6d}  {k}")

    # Does the agent's behaviour separate passing runs from failing ones?
    by = defaultdict(list)
    for r in recs:
        if r.get("outcome") in ("pass", "fail"):
            by[r["outcome"]].append(r)
    if by.get("pass") and by.get("fail"):
        print("\npass vs fail (median):")
        for key in ("num_turns", "n_tool_calls", "n_tool_errors",
                    "n_agents", "cost_usd", "diff_lines"):
            p = [r[key] for r in by["pass"] if isinstance(r.get(key), (int, float))]
            f = [r[key] for r in by["fail"] if isinstance(r.get(key), (int, float))]
            if p and f:
                print(f"  {key:16s} pass {statistics.median(p):9.3f}   "
                      f"fail {statistics.median(f):9.3f}")

    reps = Counter(r.get("repo") or "?" for r in recs)
    print("\nrepos:")
    for k, v in reps.most_common():
        print(f"  {v:5d}  {k}")


# ------------------------------------------------------------------ browse

BROWSE = """<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent run corpus</title>
<style>
 :root {{ --ink:#0C141C; --panel:#131F2A; --fg:#DCE6EE; --dim:#7E93A5;
   --hair:#1B2A36; --pass:#7FB069; --fail:#E4574C; --none:#7E93A5; }}
 *{{box-sizing:border-box}}
 body{{margin:0;background:var(--ink);color:var(--fg);
   font:14px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}}
 .wrap{{max-width:1280px;margin:0 auto;padding:40px 24px 80px}}
 h1{{font-family:"Iowan Old Style",Palatino,Georgia,serif;font-size:32px;
   font-weight:600;letter-spacing:-.015em;margin:0 0 4px}}
 .sub{{color:var(--dim);font-family:ui-monospace,Menlo,monospace;
   font-size:12.5px;margin-bottom:26px}}
 .stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
   gap:1px;background:var(--hair);border:1px solid var(--hair);margin-bottom:30px}}
 .stat{{background:var(--panel);padding:13px 15px}}
 .stat .k{{display:block;color:var(--dim);font-size:11px;
   text-transform:uppercase;letter-spacing:.09em}}
 .stat .v{{display:block;font-family:ui-monospace,Menlo,monospace;
   font-size:18px;margin-top:3px}}
 input{{width:100%;padding:9px 12px;margin-bottom:14px;background:var(--panel);
   border:1px solid var(--hair);color:var(--fg);font-size:13px;
   font-family:ui-monospace,Menlo,monospace}}
 input:focus{{outline:2px solid #5FB0C4;outline-offset:-2px}}
 table{{width:100%;border-collapse:collapse;font-size:13px}}
 th{{text-align:left;color:var(--dim);font-size:11px;text-transform:uppercase;
   letter-spacing:.08em;font-weight:500;padding:8px 10px;
   border-bottom:1px solid var(--hair);cursor:pointer;user-select:none}}
 th:hover{{color:var(--fg)}}
 td{{padding:9px 10px;border-bottom:1px solid var(--hair);
   font-family:ui-monospace,Menlo,monospace;font-size:12px}}
 tr:hover td{{background:var(--panel)}}
 a{{color:#5FB0C4;text-decoration:none}} a:hover{{text-decoration:underline}}
 .pill{{display:inline-block;padding:1px 8px;font-size:11px;
   border:1px solid currentColor}}
 .pass{{color:var(--pass)}} .fail{{color:var(--fail)}}
 .unverified,.unknown{{color:var(--none)}}
 .num{{text-align:right}} .dim{{color:var(--dim)}}
</style>
<div class="wrap">
 <h1>Agent run corpus</h1>
 <div class="sub">{root} · {n} runs</div>
 <div class="stats">{stats}</div>
 <input id="q" placeholder="filter by repo, issue, outcome, subagent…">
 <table id="t"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>
</div>
<script>
const q=document.getElementById('q'),tb=document.querySelector('#t tbody');
q.addEventListener('input',()=>{{const v=q.value.toLowerCase();
  [...tb.rows].forEach(r=>r.style.display=r.textContent.toLowerCase().includes(v)?'':'none');}});
document.querySelectorAll('#t th').forEach((th,i)=>th.addEventListener('click',()=>{{
  const rows=[...tb.rows],asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
  rows.sort((a,b)=>{{const x=a.cells[i].dataset.v??a.cells[i].textContent,
    y=b.cells[i].dataset.v??b.cells[i].textContent,
    nx=parseFloat(x),ny=parseFloat(y);
    return (!isNaN(nx)&&!isNaN(ny))?(asc?nx-ny:ny-nx)
      :(asc?String(x).localeCompare(y):String(y).localeCompare(x));}});
  rows.forEach(r=>tb.appendChild(r));}}));
</script>
"""

COLS = [("run", "run_id"), ("repo", "repo"), ("issue", "issue"),
        ("outcome", "outcome"), ("turns", "num_turns"),
        ("agents", "n_agents"), ("tools", "n_tool_calls"),
        ("errors", "n_tool_errors"), ("diff", "diff_lines"),
        ("cost", "cost_usd"), ("subagents", "subagents")]


def cmd_browse(args):
    recs = load_records(args.root)
    if not recs:
        sys.exit(f"no records in {args.root}; run 'index' first")
    recs.sort(key=lambda r: r.get("run_id") or "", reverse=True)

    head = "".join(f'<th>{html.escape(lbl)}</th>' for lbl, _ in COLS)
    out_path = args.out or os.path.join(args.root, "index.html")

    rows = []
    for r in recs:
        cells = []
        for lbl, key in COLS:
            v = r.get(key)
            if key == "run_id":
                d = r.get("artifacts_dir")
                dash = None
                if d:
                    dash = os.path.join(d, "dashboard.html")
                    try:  # relative keeps the archive portable
                        dash = os.path.relpath(dash, os.path.dirname(
                            os.path.abspath(out_path)))
                    except ValueError:
                        pass
                txt = html.escape(str(v or "?"))
                cells.append(f'<td data-v="{txt}">'
                             + (f'<a href="{html.escape(dash)}">{txt}</a>'
                                if dash else txt) + "</td>")
            elif key == "outcome":
                o = str(v or "unknown")
                cells.append(f'<td data-v="{html.escape(o)}">'
                             f'<span class="pill {html.escape(o)}">'
                             f'{html.escape(o)}</span></td>')
            elif key == "subagents":
                s = ", ".join(v or []) or "—"
                cells.append(f'<td class="dim">{html.escape(s[:60])}</td>')
            elif key == "cost_usd":
                cells.append(f'<td class="num" data-v="{v if v is not None else 0}">'
                             + (f"${v:.4f}" if isinstance(v, (int, float)) else "—")
                             + "</td>")
            elif isinstance(v, (int, float)):
                cells.append(f'<td class="num" data-v="{v}">{v}</td>')
            else:
                cells.append(f'<td>{html.escape(str(v) if v is not None else "—")}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")

    oc = Counter(r.get("outcome") or "unknown" for r in recs)
    costs = [r["cost_usd"] for r in recs if isinstance(r.get("cost_usd"), (int, float))]
    turns = [r["num_turns"] for r in recs if isinstance(r.get("num_turns"), (int, float))]
    pass_rate = oc["pass"] / max(oc["pass"] + oc["fail"], 1) * 100

    def stat(k, v):
        return f'<div class="stat"><span class="k">{k}</span><span class="v">{v}</span></div>'

    stats = "".join([
        stat("runs", len(recs)),
        stat("pass rate", f"{pass_rate:.0f}%"),
        stat("passed", oc["pass"]), stat("failed", oc["fail"]),
        stat("total cost", f"${sum(costs):.2f}" if costs else "—"),
        stat("median turns", f"{statistics.median(turns):.0f}" if turns else "—"),
        stat("repos", len({r.get("repo") for r in recs})),
    ])

    out = out_path
    open(out, "w", encoding="utf-8").write(BROWSE.format(
        root=html.escape(args.root), n=len(recs),
        stats=stats, head=head, rows="".join(rows)))
    print(f"wrote {out}")


# ------------------------------------------------------------------ export


def flatten(node, out, depth=0):
    """Depth-first list of every step across the agent tree."""
    for s in node.get("steps", []):
        out.append(dict(s, agent=node.get("agent"), depth=depth))
    for c in node.get("children", []):
        flatten(c, out, depth + 1)
    return out


def cmd_export(args):
    recs = load_records(args.root)
    if not recs:
        sys.exit(f"no records in {args.root}; run 'index' first")

    if args.outcome:
        keep = set(args.outcome.split(","))
        recs = [r for r in recs if (r.get("outcome") or "unknown") in keep]
    if args.repo:
        recs = [r for r in recs if r.get("repo") == args.repo]
    if not recs:
        sys.exit("filters removed every record")

    n = 0
    with open(args.out, "w", encoding="utf-8") as f:
        for r in recs:
            if args.format == "trajectory":
                rec = r
            elif args.format == "sft":
                steps = flatten(r.get("trajectory") or {}, [])
                msgs = [{"role": "user", "content": r.get("prompt") or ""}]
                for s in steps:
                    if s["kind"] in ("text", "thinking"):
                        msgs.append({"role": "assistant", "kind": s["kind"],
                                     "agent": s.get("agent"),
                                     "content": s.get("text", "")})
                    else:
                        msgs.append({"role": "assistant", "kind": "tool_use",
                                     "agent": s.get("agent"),
                                     "tool": s.get("tool"),
                                     "input": s.get("input"),
                                     "result": s.get("result"),
                                     "is_error": s.get("is_error")})
                rec = {"run_id": r.get("run_id"), "repo": r.get("repo"),
                       "issue": r.get("issue"), "outcome": r.get("outcome"),
                       "messages": msgs}
            else:  # outcome — one compact row per run, no trajectory payload
                rec = {k: v for k, v in r.items() if k != "trajectory"}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"wrote {n} record(s) to {args.out} (format={args.format})")
    print("Reminder: Anthropic's terms permit training non-competing models on "
          "outputs. Confirm scope before using this beyond analysis.")


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=ROOT, help=f"archive root (default {ROOT})")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("index", help="rebuild records.jsonl from run directories")
    i.add_argument("--rebuild-views", action="store_true",
                   help="also regenerate dashboard.html / transcript.md per run")
    i.set_defaults(func=cmd_index)

    s = sub.add_parser("stats", help="summarise the corpus")
    s.set_defaults(func=cmd_stats)

    b = sub.add_parser("browse", help="write a browsable index.html")
    b.add_argument("--out")
    b.set_defaults(func=cmd_browse)

    e = sub.add_parser("export", help="write an eval-ready dataset")
    e.add_argument("out")
    e.add_argument("--format", choices=["trajectory", "sft", "outcome"],
                   default="trajectory")
    e.add_argument("--outcome", help="comma-separated filter, e.g. pass,fail")
    e.add_argument("--repo")
    e.set_defaults(func=cmd_export)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:  # output piped to head/less
        try:
            sys.stdout.close()
        finally:
            os._exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
