#!/usr/bin/env python3
"""
gaia_runs_site_index.py — build a static index over every dashboard.html
committed by scripts/gaia_run_queue.sh, for GitHub Pages.

Usage
  python3 gaia_runs_site_index.py docs/gaia-runs out/index.html

Expected layout (written by gaia_run_queue.sh, one per resolved issue):
  docs/gaia-runs/issue-<n>/<timestamp>/dashboard.html

This only lists what it finds on disk at build time; there is no separate
database to fall out of sync with the committed files.
"""

import glob
import html
import os
import sys


def find_dashboards(root):
    """[(issue_number, timestamp, path_relative_to_root), ...], newest first."""
    pattern = os.path.join(root, "issue-*", "*", "dashboard.html")
    rows = []
    for path in glob.glob(pattern):
        rel = os.path.relpath(path, root)
        parts = rel.split(os.sep)
        if len(parts) != 3:
            continue  # not the issue-*/<timestamp>/dashboard.html layout we expect
        issue_dir, stamp, _ = parts
        issue = issue_dir[len("issue-"):] if issue_dir.startswith("issue-") else issue_dir
        rows.append((issue, stamp, rel))
    rows.sort(key=lambda r: r[1], reverse=True)  # timestamp sorts lexicographically
    return rows


TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>gaia run dashboards</title>
<style>
  :root {{ --ink:#0C141C; --panel:#131F2A; --fg:#DCE6EE; --dim:#7E93A5; --hair:#1B2A36; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--ink); color:var(--fg);
    font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:860px; margin:0 auto; padding:40px 24px 80px; }}
  h1 {{ font-family:"Iowan Old Style",Palatino,Georgia,serif;
    font-size:30px; font-weight:600; letter-spacing:-.015em; margin:0 0 6px; }}
  .sub {{ color:var(--dim); font-family:ui-monospace,Menlo,Consolas,monospace;
    font-size:12.5px; margin-bottom:28px; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  th {{ text-align:left; color:var(--dim); font-size:11px; text-transform:uppercase;
    letter-spacing:.08em; font-weight:500; padding:8px 10px; border-bottom:1px solid var(--hair); }}
  td {{ padding:9px 10px; border-bottom:1px solid var(--hair);
    font-family:ui-monospace,Menlo,monospace; font-size:13px; }}
  tr:hover td {{ background:var(--panel); }}
  a {{ color:#5FB0C4; text-decoration:none; }} a:hover {{ text-decoration:underline; }}
  .empty {{ color:var(--dim); padding:20px 0; }}
</style>
<div class="wrap">
  <h1>gaia run dashboards</h1>
  <div class="sub">one row per issue resolved by gaia_run_queue.sh &middot; {n} run(s)</div>
  {body}
</div>
"""

ROW = ('<tr><td><a href="{href}">#{issue}</a></td><td>{stamp}</td></tr>')


def render(rows):
    if not rows:
        body = '<p class="empty">No runs committed yet.</p>'
    else:
        trs = "".join(
            ROW.format(href=html.escape(rel), issue=html.escape(issue),
                       stamp=html.escape(stamp))
            for issue, stamp, rel in rows)
        body = (f'<table><thead><tr><th>issue</th><th>run</th></tr></thead>'
                f'<tbody>{trs}</tbody></table>')
    return TEMPLATE.format(n=len(rows), body=body)


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: gaia_runs_site_index.py <gaia-runs-dir> <out.html>")
    root, out = sys.argv[1], sys.argv[2]
    rows = find_dashboards(root) if os.path.isdir(root) else []
    open(out, "w", encoding="utf-8").write(render(rows))
    print(f"wrote {out} ({len(rows)} run(s))")


if __name__ == "__main__":
    main()
