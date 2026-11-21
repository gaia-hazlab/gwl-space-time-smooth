#!/usr/bin/env python3
"""Regenerate the soil-state review ladder tracker from GitHub.

Reads ``docs/reviews/2026-11-07-fable-soil-state-review/issues/ladder.json`` (ladder key ->
issue number, written when the issues were created) and the static ladder table in this file,
queries GitHub through ``gh api`` for state, labels, assignee, closing PR and the "Blocked by:"
line of each issue's current scope, and rewrites the state columns of ``TRACKER.md``. Outcome and
evidence columns are hand-maintained in ``outcomes.json`` next to the tracker: this script never
invents an outcome. ``--check`` exits non-zero if a ladder issue is missing or its blockers differ
from the ladder table. Writes nothing to GitHub.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
RECORD = HERE / "docs/reviews/2026-11-07-fable-soil-state-review"
LADDER_JSON = RECORD / "issues/ladder.json"
OUTCOMES_JSON = RECORD / "outcomes.json"
TRACKER = RECORD / "TRACKER.md"
TWIN = "gaia-hazlab/gwl-space-time-smooth"
REPOS = {"H1": "gaia-hazlab/hydrostate", "H2": "gaia-hazlab/hydrostate", "M1": "gaia-hazlab/mechanicalstate"}

# key, type, batch, expected blockers (ladder keys or issue numbers in the twin), one-line title
LADDER = [
    ("R0", "epic", 0, [], "validation ladder epic"),
    ("L1", "experiment", 0, [], "closed-column ledger audit (legacy store model)"),
    ("L2", "experiment", 0, [], "forecast reinitialisation and issue-time leakage"),
    ("U1", "experiment", 0, [], "dependence sensitivity: coherent vs independent draws"),
    ("C1", "experiment", 0, [], "Landlab LandslideProbability causal test"),
    ("P1", "experiment", 0, [], "bounded land-surface performance study"),
    ("H1", "experiment", 0, [], "hydrostate: 1-D column reference with seepage/free drainage"),
    ("H2", "docs", 0, [], "hydrostate: architecture doc aligned with MF6 direction"),
    ("M1", "experiment", 0, [], "mechanicalstate: separated refinement sweeps, clean evidence"),
    ("X1", "experiment", 1, [275], "option A vs B column test vs Richards reference"),
    ("X2", "experiment", 1, [275], "UZF restart memory"),
    ("Q1", "decision", 2, ["X1"], "capillary replenishment and residual PET under option B"),
    ("Q2", "decision", 2, ["X2"], "cycling operation mode"),
    ("Q3", "decision", 2, ["L2"], "one snow model, one root bucket"),
    ("Q4", "decision", 2, ["X1"], "Hydrostate role"),
    ("X3", "experiment", 4, [289], "constrained reconciled analysis update"),
    ("B188", "feature", 4, [188, 285, 9, 235], "cycling nowcast pilot and multi-sensor (slices b, c)"),
    ("X4", "experiment", 5, [235], "multi-event issue-time-frozen evaluation manifest"),
    ("Q5", "decision", 6, [230], "products made with the sign-inverted Stage-3 DTW"),
    ("QF", "decision", 6, ["L1", "L2", "U1", "C1", "P1", "X1", "X2", "X3", "X4", "Q1", "Q2", "Q3", "Q4", "Q5"], "human review of the ladder"),
]
AMENDED = [232, 280, 282, 283, 286, 142, 270, 188, 289, 187, 234, 52, 191, 230, 195, 235, 189, 247, 198, 127, 129, 193, 260, 141, 267]
BLOCKED = re.compile(r"^\s*\**Blocked by\**:?\**\s*(.*)$", re.IGNORECASE | re.MULTILINE)


def gh(args: list[str]) -> dict | list:
    out = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def body_blockers(body: str | None) -> set[int]:
    if not body:
        return set()
    scope = body.split("<details>", 1)[0]
    nums: set[int] = set()
    for m in BLOCKED.finditer(scope):
        nums.update(int(n) for n in re.findall(r"#(\d+)", m.group(1)))
    return nums


def fetch(repo: str, number: int) -> dict:
    i = gh([f"repos/{repo}/issues/{number}"])
    prs = gh([f"repos/{repo}/issues/{number}/timeline", "--paginate", "-H", "Accept: application/vnd.github+json"])
    linked = sorted({e["source"]["issue"]["number"] for e in prs
                     if e.get("event") == "cross-referenced" and e.get("source", {}).get("issue", {}).get("pull_request")})
    return {"state": i["state"], "labels": sorted(l["name"] for l in i["labels"]),
            "milestone": (i.get("milestone") or {}).get("title"), "blockers": sorted(body_blockers(i.get("body"))),
            "linked_prs": linked, "updated": i["updated_at"][:10], "title": i["title"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 on missing issues or blocker mismatch")
    args = ap.parse_args()
    nums = json.loads(LADDER_JSON.read_text())
    outcomes = json.loads(OUTCOMES_JSON.read_text()) if OUTCOMES_JSON.exists() else {}
    problems: list[str] = []
    rows = []
    for key, kind, batch, expected, title in LADDER:
        repo = REPOS.get(key, TWIN)
        if key not in nums:
            problems.append(f"{key} has no issue number"); continue
        info = fetch(repo, nums[key])
        exp = sorted(nums[b] if isinstance(b, str) else b for b in expected) if repo == TWIN else []
        if repo == TWIN and info["blockers"] != exp:
            problems.append(f"{key} #{nums[key]} blockers {info['blockers']} != ladder {exp}")
        held = [l for l in info["labels"] if l in ("needs-human-decision", "needs-compute", "superseded")]
        state = "closed" if info["state"] == "closed" else ("held" if held else ("PR" if info["linked_prs"] else "open"))
        o = outcomes.get(key, {})
        rows.append((key, f"{repo.split('/')[1]}#{nums[key]}", kind, batch,
                     ", ".join(f"#{b}" for b in info["blockers"]) or "none", state,
                     o.get("outcome", ""), o.get("evidence", ""), o.get("date", info["updated"])))
    amended = []
    for n in AMENDED:
        info = fetch(TWIN, n)
        amended.append((f"#{n}", info["title"][:70], info["state"], ", ".join(f"#{b}" for b in info["blockers"]) or "none", info["updated"]))
    decisions = outcomes.get("_decisions", [])
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    lines = [f"# Tracker: soil-state validation ladder", "",
             f"Regenerated {stamp} by `scripts/review_tracker.py` from GitHub. Outcome and evidence columns come from `outcomes.json` (hand-maintained by the PR that completes a row); state, blockers and dates come from GitHub. Record: `README.md` in this folder; epic: {TWIN}#{nums['R0']}.", "",
             "## Ladder", "", "| key | issue | type | batch | blocked by | state | outcome | evidence | date |", "|---|---|---|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    lines += ["", "## Amended existing issues", "", "| issue | title | state | blocked by | updated |", "|---|---|---|---|---|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in amended]
    lines += ["", "## Decision log", "", "| question | prerequisite evidence | decision | date | decided by |", "|---|---|---|---|---|"]
    lines += ["| " + " | ".join(str(d.get(k, "")) for k in ("question", "evidence", "decision", "date", "by")) + " |" for d in decisions] or ["| (none yet) | | | | |"]
    if problems:
        lines += ["", "## Check problems", ""] + [f"- {p}" for p in problems]
    TRACKER.write_text("\n".join(lines) + "\n")
    print(f"wrote {TRACKER} ({len(rows)} ladder rows, {len(amended)} amended, {len(problems)} problems)")
    for p in problems:
        print("PROBLEM:", p, file=sys.stderr)
    return 1 if (args.check and problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
