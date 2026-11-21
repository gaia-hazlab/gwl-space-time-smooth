#!/usr/bin/env python3
"""How stale the parked work has become -- the cost of parking, measured instead of assumed.

A science-gate block parks ONE issue and lets the rest of the batch continue. That decision is
right, and it has a price nothing was watching: the parked issue keeps its pre-registered plan
and its panel verdicts, but the tree those were written against moves on. Its siblings land,
the files its plan names get rewritten, and at some point "resume the parked plan" stops being
cheaper than planning it again -- while the issue still sits there labelled `needs-human-decision`
looking exactly as resumable as it did on the day it was parked.

So every park writes a stamp: the issue, the commit the plan was written against, and the files
the plan said it would touch. Later runs measure the distance from there:

  * commits on the branch since the park -- how much the project moved at all;
  * commits touching THE PLAN'S OWN FILES -- how much it moved underneath this plan
    specifically, which is the number that decides whether the plan still describes reality;
  * days parked.

The verdict is deliberately blunt -- fresh / aging / stale -- and it recommends, it does not
act. Nothing here closes, reopens, deletes or re-queues anything: a staleness heuristic that
could act on an issue a human parked would be exactly the wrong thing to automate.

Usage:
    python gaia_parked.py --record --issue 186 --title "..." --panel panel.json --plan plan.json
    python gaia_parked.py --status [--out FILE] [--max-days 21] [--max-touching 3]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STAMPS = REPO_ROOT / ".gaia-runs" / "parked.jsonl"

# The bounds. Both are judgement calls stated once, out loud, rather than left implicit in a
# reader's sense of "a while ago" -- and both are arguments, so a project with a different
# cadence can set its own.
MAX_DAYS = 21          # beyond three weeks, the brief the plan was written from is itself stale
MAX_TOUCHING = 3       # commits rewriting the plan's own files; past a few, it is a new plan


def git(args: list[str], cwd: Path = REPO_ROOT) -> str | None:
    """Fail soft, always. This module reports; it may not be the reason a run stops."""
    try:
        out = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                             timeout=30)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def plan_paths(plan: dict) -> list[str]:
    """The files a plan said it would produce or change.

    `artifacts` is free text written by a planner, so it holds real paths next to prose like
    "a figure showing the residuals". Only path-shaped entries are kept: anything else would
    make `git rev-list -- <pathspec>` either error or silently match nothing, and a staleness
    number computed from a pathspec that matches nothing reads as "nothing changed".
    """
    out = []
    for a in plan.get("artifacts") or []:
        a = str(a).strip().strip("`").split(" ")[0]
        if not a or a.startswith("-"):
            continue
        if "/" in a or "." in a.lstrip("."):
            out.append(a)
    return sorted(set(out))


def read(path: Path = STAMPS) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def stamp(issue: int, title: str = "", milestone: str = "", panel: dict | None = None,
          plan: dict | None = None, sha: str = "", ts: str = "", log: str = "") -> dict:
    panel = panel or {}
    return dict(event="parked", issue=issue, title=title[:200], milestone=milestone[:200],
                ts=ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                sha=sha or (git(["rev-parse", "HEAD"]) or ""),
                paths=plan_paths(plan or {}),
                decision=panel.get("decision", "?"),
                blocking=[(c.get("claim") or "")[:200]
                          for c in (panel.get("blocking_concerns") or [])],
                log=log)


def latest(rows: list[dict]) -> dict[int, dict]:
    """One entry per issue, the newest -- an issue parked twice is one parked issue, and the
    second park is the one whose plan and commit a resume would start from."""
    out: dict[int, dict] = {}
    for r in rows:
        n = r.get("issue")
        if n is None:
            continue
        if r.get("event") == "unparked":
            out.pop(n, None)
            continue
        if n not in out or str(r.get("ts", "")) >= str(out[n].get("ts", "")):
            out[n] = r
    return out


def age_days(ts: str, now: datetime | None = None) -> float | None:
    try:
        t = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return round(((now or datetime.now(timezone.utc)) - t).total_seconds() / 86400.0, 1)


def staleness(days: float | None, commits: int | None, touching: int | None,
              max_days: int = MAX_DAYS, max_touching: int = MAX_TOUCHING) -> dict:
    """fresh / aging / stale, with the reason spelled out.

    `touching` dominates on purpose. A hundred commits elsewhere in the repository do not make
    a parked plan wrong; three commits rewriting the two files it names probably do. Unknowns
    never manufacture a verdict: a stamp whose commit is no longer in the tree reports
    `unknown` rather than `fresh`, because "we cannot tell" and "it is fine" are different
    answers and only one of them is safe to act on.
    """
    reasons = []
    if days is None and commits is None:
        return dict(verdict="unknown", reasons=["no usable park stamp"])
    stale = aging = False
    if touching is not None and touching > max_touching:
        stale = True
        reasons.append(f"{touching} commits have rewritten the files this plan names "
                       f"(bound: {max_touching})")
    elif touching:
        aging = True
        reasons.append(f"{touching} commit(s) have touched the files this plan names")
    if days is not None and days > max_days:
        stale = True
        reasons.append(f"parked {days:.0f} days (bound: {max_days})")
    elif days is not None and days > max_days / 2:
        aging = True
        reasons.append(f"parked {days:.0f} days")
    if commits is not None and not reasons:
        reasons.append(f"{commits} commit(s) landed since, none in this plan's files")
    if touching is None and commits is None:
        return dict(verdict="unknown", reasons=["the parked commit is not in this tree"])
    return dict(verdict="stale" if stale else "aging" if aging else "fresh", reasons=reasons)


def measure(row: dict, cwd: Path = REPO_ROOT, now: datetime | None = None,
            max_days: int = MAX_DAYS, max_touching: int = MAX_TOUCHING) -> dict:
    sha, paths = row.get("sha") or "", row.get("paths") or []
    known = bool(sha) and git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd) is not None
    commits = touching = None
    changed: list[str] = []
    if known:
        c = git(["rev-list", "--count", f"{sha}..HEAD"], cwd)
        commits = int(c) if c and c.isdigit() else None
        if paths:
            t = git(["rev-list", "--count", f"{sha}..HEAD", "--", *paths], cwd)
            touching = int(t) if t and t.isdigit() else None
            names = git(["log", "--name-only", "--pretty=format:", f"{sha}..HEAD", "--", *paths],
                        cwd)
            changed = sorted({n for n in (names or "").split("\n") if n.strip()})
    days = age_days(row.get("ts", ""), now)
    out = dict(row)
    out.update(days=days, commits=commits, touching=touching, changed=changed,
               **staleness(days, commits, touching, max_days, max_touching))
    return out


def gh_state(issue: int) -> str | None:
    """Best effort. An issue that has since been closed is not parked work any more, but a
    missing or offline `gh` must not turn the whole report off -- it just means the report
    says it could not check."""
    try:
        out = subprocess.run(["gh", "issue", "view", str(issue), "--json", "state"],
                             capture_output=True, text=True, timeout=25)
        if out.returncode != 0:
            return None
        return str(json.loads(out.stdout).get("state", "")).upper() or None
    except Exception:
        return None


def render(measured: list[dict], checked_gh: bool = False, closed: int = 0) -> str:
    if not measured:
        return ("# Parked work\n\nNothing parked, or nothing recorded. Every science-gate park "
                "writes a stamp here.\n")
    icon = {"stale": "🔴", "aging": "🟠", "fresh": "🟢", "unknown": "⚪"}
    order = {"stale": 0, "unknown": 1, "aging": 2, "fresh": 3}
    measured = sorted(measured, key=lambda m: (order.get(m["verdict"], 9), -(m["days"] or 0)))
    n_stale = sum(1 for m in measured if m["verdict"] == "stale")
    out = ["# Parked work, and how far the project has moved without it", "",
           "A parked issue keeps its pre-registered plan and its panel verdicts, and the tree "
           "they were written against keeps moving. This measures that distance — commits "
           "since the park, commits rewriting **the files the plan itself names**, and days "
           "waiting. Nothing here acts: it recommends, and a person decides.", "",
           f"**{len(measured)} parked** · {n_stale} stale."
           + (f" {closed} since closed and dropped from this list." if closed else "")
           + ("" if checked_gh else " *(Issue state not checked — `gh` unavailable — so an "
              "issue closed by hand may still be listed.)*"), "",
           "| | issue | parked | commits since | touching this plan's files | verdict |",
           "|---|---|---|---|---|---|"]
    for m in measured:
        d = f"{m['days']:.0f}d" if m["days"] is not None else "?"
        c = m["commits"] if m["commits"] is not None else "?"
        t = m["touching"] if m["touching"] is not None else ("—" if not m.get("paths") else "?")
        out.append(f"| {icon.get(m['verdict'], '')} | #{m['issue']} | {d} | {c} | {t} | "
                   f"{m['verdict']} |")
    out.append("")
    for m in measured:
        if m["verdict"] in ("fresh",):
            continue
        out.append(f"### {icon.get(m['verdict'], '')} #{m['issue']} — {m.get('title', '')}")
        out.append(f"*{'; '.join(m['reasons'])}.*")
        if m.get("changed"):
            out.append("Rewritten since it was parked: "
                       + ", ".join(f"`{c}`" for c in m["changed"][:8])
                       + (f" (+{len(m['changed']) - 8} more)" if len(m["changed"]) > 8 else ""))
        if m["verdict"] == "stale":
            out.append("**Re-plan rather than resume.** The panel's verdicts are still worth "
                       "reading — they are on the issue — but the plan they judged was written "
                       "against a tree that no longer exists.")
        out.append(f"`gh issue view {m['issue']} --comments`"
                   + (f" · parked at `{m['sha'][:9]}`" if m.get("sha") else ""))
        out.append("")
    return "\n".join(out)


def load(path: str | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--record", action="store_true")
    p.add_argument("--unpark", action="store_true",
                   help="record that an issue is no longer parked; it drops out of --status")
    p.add_argument("--status", action="store_true")
    p.add_argument("--issue", type=int)
    p.add_argument("--title", default="")
    p.add_argument("--milestone", default="")
    p.add_argument("--panel", metavar="PANEL_JSON")
    p.add_argument("--plan", metavar="PLAN_JSON")
    p.add_argument("--sha", default="")
    p.add_argument("--ts", default="")
    p.add_argument("--log", default="")
    p.add_argument("--stamps", metavar="FILE")
    p.add_argument("--repo-dir", metavar="DIR")
    p.add_argument("--max-days", type=int, default=MAX_DAYS)
    p.add_argument("--max-touching", type=int, default=MAX_TOUCHING)
    p.add_argument("--no-gh", action="store_true", help="skip the issue-state check")
    p.add_argument("--out", metavar="FILE")
    a = p.parse_args()
    path = Path(a.stamps) if a.stamps else STAMPS
    cwd = Path(a.repo_dir) if a.repo_dir else REPO_ROOT

    if a.record or a.unpark:
        if a.issue is None:
            print("--record/--unpark need --issue N", file=sys.stderr)
            return 2
        row = (dict(event="unparked", issue=a.issue,
                    ts=a.ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
               if a.unpark else
               stamp(a.issue, a.title, a.milestone, load(a.panel), load(a.plan), a.sha, a.ts,
                     a.log))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:                 # never a gate: see the module docstring
            print(f"could not record the park of #{a.issue}: {e}", file=sys.stderr)
            return 0
        print(f"parked #{a.issue} recorded at {row.get('sha', '')[:9]} "
              f"({len(row.get('paths') or [])} plan path(s))", file=sys.stderr)
        return 0

    if a.status:
        rows = list(latest(read(path)).values())
        closed, checked = 0, False
        if not a.no_gh:
            keep = []
            for r in rows:
                st = gh_state(r["issue"])
                checked = checked or st is not None
                if st == "CLOSED":
                    closed += 1
                    continue
                keep.append(r)
            rows = keep
        measured = [measure(r, cwd, None, a.max_days, a.max_touching) for r in rows]
        text = render(measured, checked, closed)
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
