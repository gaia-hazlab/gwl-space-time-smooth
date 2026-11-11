"""Checks for the 2026-11-10 roadmap review record. Run from the repository root:
    python docs/reviews/2026-11-10-roadmap-review/scripts/check_record.py
1. every #N cited in README.md, coverage.csv and issues/*.md is an open issue in the snapshot, or is
   listed in KNOWN_NON_OPEN (PRs, closed issues, other repos) ;
2. every `path:line` citation points at an existing file with at least that many lines;
3. every NEW-xx referenced has a file in issues/.
"""
import json, pathlib, re, sys

R = pathlib.Path(__file__).resolve().parents[1]
ROOT = R.parents[2]
open_n = {i["number"] for i in json.loads((R / "snapshot/open_issues.json").read_text())}
KNOWN_NON_OPEN = {229, 272, 273, 313, 314, 315, 316, 317, 318, 222,      # pull requests
                  39, 55, 64, 87, 88, 90, 98, 137}                          # closed or superseded, cited as history
_posted = R / "issues/posted.json"
if _posted.exists():  # issues created by this review on 2026-11-11, after the snapshot
    open_n |= set(json.loads(_posted.read_text()).values())
files = [R / "README.md", R / "coverage.csv", *sorted((R / "issues").glob("*.md"))]
bad = []
new_ids = {p.name.split("-")[1] for p in (R / "issues").glob("NEW-*.md")}
for f in files:
    t = f.read_text()
    for n in {int(x) for x in re.findall(r"(?<![\w/])#(\d{1,3})\b", t)}:
        if n not in open_n and n not in KNOWN_NON_OPEN:
            bad.append(f"{f.name}: #{n} not open in snapshot")
    for path, line in re.findall(r"`((?:src|docs|scripts|tests)/[\w./-]+|ROADMAP\.md):(\d+)", t):
        p = ROOT / path
        if not p.exists():
            bad.append(f"{f.name}: {path} missing")
        elif len(p.read_text().splitlines()) < int(line):
            bad.append(f"{f.name}: {path}:{line} beyond end of file")
    for nid in set(re.findall(r"NEW-([A-Z]\d)\b", t)):
        if nid not in new_ids:
            bad.append(f"{f.name}: NEW-{nid} has no draft file")
print("\n".join(bad) or f"ok: {len(files)} files checked against {len(open_n)} open issues")
sys.exit(1 if bad else 0)
