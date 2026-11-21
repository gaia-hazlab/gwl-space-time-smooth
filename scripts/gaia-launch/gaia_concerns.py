#!/usr/bin/env python3
"""The standing record of scientific disagreements the pipeline did not settle.

Two rounds of review are enough. After that a disagreement is one of two things, and they
deserve opposite treatment:

  * It reaches past its own issue -- a breaking change for the rest of the project, or physics
    that is simply wrong. That blocks, parks the issue, and goes to a human now.
  * It does not. The work proceeds, because a panel of domain experts reviewing a milestone
    will always have more to say and stopping for all of it is how a gate becomes a pager.

The second case had nowhere to go. A deferred concern was posted on its issue, handed to the
implementer, and then gone -- so the panel's real science evaporated at the end of every run,
and the same objection was rediscovered from scratch on the next issue that touched the same
ground. That is the expensive failure: not the concerns that stop work, but the ones that
don't and are then forgotten.

So they accumulate here instead, and are reviewed HOLISTICALLY -- which is the point. Read one
at a time they are twelve separate objections; read together they are usually three. On issue
#186 the Clopper-Pearson interval being anticonservative under clustered wells, the n=316
power threshold being optimistic, and the block-bootstrap design effect were filed as three
critical concerns by two personas. They are one problem: the coverage validation is
underpowered and its interval is wrong. A per-issue gate can never see that. A ledger can.

Usage:
    python gaia_concerns.py --append panel.json --issue 186 --title "..." [--milestone "..."]
    python gaia_concerns.py --render [--issue 186] [--since 2026-08-01]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = REPO_ROOT / ".gaia-runs" / "science-concerns.jsonl"

# Disposition, which is NOT severity. It records what the pipeline did about the concern, so a
# later reader can tell "this stopped an issue" from "this was noted and the work went ahead".
BLOCKED = "blocked"        # critical + a scope that reaches past the issue; the issue parked
DEFERRED = "deferred"      # real, but in-milestone; handed to the implementer and proceeded
UNRESOLVED = "unresolved"  # raised in an earlier round and still standing at the last one

# Two concerns are related when they are about the same THING, not when they happen to use the
# same words. Prose overlap was tried first and does not work here: measured on the real #186
# panel, the best true pair (two personas independently on Clopper-Pearson) scored BELOW a
# false one, and boilerplate like "stopping condition" manufactured matches between concerns
# with nothing to do with each other. Reviewers writing about the same problem from different
# disciplines share almost no vocabulary -- what they share is the referent.
#
# So the signal is the technical referents: the file and line, the symbol, the named method.
# `interpolate_residuals.py:79`, `MIN_SITES_PER_MONTH`, `Clopper-Pearson`, `NST`.
REF = re.compile(r"""
    [A-Za-z_][A-Za-z0-9_]*\.py(?::\d+(?:-\d+)?)?   # interpolate_residuals.py:79
  | [A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+           # sigma_response, measurement_target
  | [A-Z][a-z]+-[A-Z][a-z]+                        # Clopper-Pearson, Gauss-Hermite
  | \b[A-Z]{2,}\b                                  # NST, OK, SK, GLM, DOMAINS
""", re.X)


def referents(claim: str) -> frozenset[str]:
    """The named things a concern is about. A file path keeps the file but drops the line:
    two reviewers objecting to the same function rarely cite the same line number."""
    out = set()
    for m in REF.findall(claim or ""):
        m = m.strip()
        out.add(m.split(":")[0] if ".py" in m else m)
    return frozenset(out)


def affinity(a: str, b: str, df: Counter, n: int = 0) -> float:
    """How strongly two concerns point at the same thing, weighted by rarity.

    Sharing `interpolate_residuals.py` when three concerns mention it is real evidence;
    sharing `OK` when half of them do is not. The weight is 1/(df-1): a referent that only
    these two concerns mention scores 1.0, one that ten mention scores 0.11. A score of 1.0
    therefore reads as "they share something nothing else mentions", at any ledger size.

    Textbook IDF -- log(1 + n/df) -- was the first attempt and is wrong here, because it
    scales with the corpus: the same two concerns about Clopper-Pearson failed to group in a
    three-entry ledger and grouped in a thirty-entry one. A record whose grouping changes
    because unrelated issues were added later is not one a person can trust.
    """
    shared = referents(a) & referents(b)
    return sum(1.0 / max(1, df[t] - 1) for t in shared if df.get(t, 0) > 1)


def read(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def rows_from_panel(panel: dict, issue: int, title: str = "", milestone: str = "",
                    run_ts: str = "", rounds: int = 1) -> list[dict]:
    """Everything still standing when the review stopped, with what the pipeline did about it.

    Minor concerns are excluded on purpose. The ledger is read by a person deciding what to
    work on next; padding it with everything anyone said is how a record stops being read.
    """
    rows: list[dict] = []

    def row(c: dict, disposition: str, persona: str):
        return dict(issue=issue, title=title[:200], milestone=milestone[:200],
                    run_ts=run_ts, rounds=rounds, disposition=disposition,
                    persona=persona or c.get("persona", "?"),
                    severity=c.get("severity", "?"), scope=c.get("scope", "?"),
                    claim=(c.get("claim") or "")[:400],
                    decisive_test=(c.get("decisive_test") or "")[:400])

    for c in panel.get("blocking_concerns") or []:
        rows.append(row(c, BLOCKED, c.get("persona", "?")))
    for c in panel.get("deferred_concerns") or []:
        rows.append(row(c, DEFERRED, c.get("persona", "?")))
    # A prior concern the last round left standing is the sharpest signal in the file: the
    # planner was told about it, tried, and the reviewer still says it stands.
    for v in panel.get("verdicts") or []:
        for p in v.get("prior_concerns") or []:
            if p.get("status") == "unresolved":
                rows.append(row(dict(claim=p.get("claim"), decisive_test=p.get("why"),
                                     severity="carried", scope="carried"),
                                UNRESOLVED, v.get("persona", "?")))
    return rows


def append(rows: list[dict], path: Path = LEDGER) -> int:
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def cluster(rows: list[dict], threshold: float = 1.0) -> tuple[list[list[dict]], dict]:
    """Single-link grouping on shared technical referents, largest group first.

    The value of this file is that it is read all at once, so the grouping is the product --
    it is what turns twelve objections into three problems. It is a reading aid and nothing
    downstream gates on it, so a wrong grouping costs a reader a moment, not a decision.

    Returns (groups, shared_referents_by_group_index) so the render can SAY what each group
    has in common. A group whose reason is visible can be dismissed in one glance when it is
    wrong; an unexplained one has to be re-derived every time the file is read.
    """
    df: Counter = Counter()
    for r in rows:
        df.update(referents(r["claim"]))
    n = len(rows)
    groups: list[list[dict]] = []
    for r in rows:
        for g in groups:
            if any(affinity(r["claim"], m["claim"], df, n) >= threshold for m in g):
                g.append(r)
                break
        else:
            groups.append([r])
    groups.sort(key=lambda g: (-len(g), g[0]["issue"]))
    common = {}
    for i, g in enumerate(groups):
        if len(g) > 1:
            sets = [referents(m["claim"]) for m in g]
            # What the group has in common: referents shared by at least two of its members.
            # Not the intersection of all -- single-link chains legitimately have none.
            seen: Counter = Counter()
            for s in sets:
                seen.update(s)
            # `df[t] < n` drops a referent every row in the ledger mentions -- that is the
            # subject of the file, not what this group has in common. It is a preference and
            # not a requirement: in a small ledger the group can BE the whole file, and then
            # the only shared referent is universal by arithmetic rather than by boilerplate.
            shared = sorted(t for t, c in seen.items() if c > 1)
            common[i] = [t for t in shared if df[t] < n] or shared
    return groups, common


def render(rows: list[dict]) -> str:
    if not rows:
        return ("# Standing science concerns\n\nNothing recorded. Either no panel has run yet, "
                "or every concern it raised was resolved within its two review rounds.\n")
    by_disp = defaultdict(list)
    for r in rows:
        by_disp[r["disposition"]].append(r)
    issues = sorted({r["issue"] for r in rows})
    out = ["# Standing science concerns",
           "",
           "Raised by the science panel, not settled within its two review rounds, and left "
           "open on purpose. Read this **all at once**: one at a time these are separate "
           "objections; together they are usually a handful of problems seen from different "
           "disciplines.",
           "",
           f"**{len(rows)}** concerns across **{len(issues)}** issues — "
           f"{len(by_disp[BLOCKED])} blocked an issue, {len(by_disp[DEFERRED])} were deferred "
           f"and the work proceeded, {len(by_disp[UNRESOLVED])} were carried unresolved out of "
           f"the last review round.",
           ""]

    groups, common = cluster(rows)
    multi = [(i, g) for i, g in enumerate(groups) if len(g) > 1]
    if multi:
        out += ["## Converging on the same thing", "",
                "*Grouped by the code, symbols and named methods the concerns point at — not by "
                "wording, since reviewers from different disciplines describe one problem in "
                "different words. These are the candidates for a single decision that settles "
                "several concerns at once.*", ""]
        for k, (i, g) in enumerate(multi, 1):
            where = ", ".join(f"#{n}" for n in sorted({m["issue"] for m in g}))
            who = ", ".join(sorted({m["persona"] for m in g}))
            about = ", ".join(f"`{t}`" for t in common.get(i, [])[:6])
            out.append(f"### {k}. {len(g)} concerns · {where} · *{who}*")
            if about:
                out.append(f"All about: {about}")
            out.append("")
            for m in g:
                out.append(f"- **[{m['disposition']}/{m['scope']}]** #{m['issue']} — {m['claim']}")
                if m["decisive_test"]:
                    out.append(f"  - *decisive test:* {m['decisive_test']}")
            out.append("")

    out += ["## By issue", ""]
    for n in issues:
        mine = [r for r in rows if r["issue"] == n]
        head = mine[0]
        ms = f" · *{head['milestone']}*" if head.get("milestone") else ""
        out.append(f"### #{n} — {head.get('title') or ''}{ms}")
        for r in mine:
            out.append(f"- **[{r['disposition']}/{r['scope']}]** {r['claim']} — *{r['persona']}*")
            if r["decisive_test"]:
                out.append(f"  - *decisive test:* {r['decisive_test']}")
        out.append("")
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--append", metavar="PANEL_JSON")
    p.add_argument("--issue", type=int)
    p.add_argument("--title", default="")
    p.add_argument("--milestone", default="")
    p.add_argument("--run-ts", default="")
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--render", action="store_true")
    p.add_argument("--out", metavar="FILE")
    p.add_argument("--ledger", metavar="FILE")
    a = p.parse_args()
    ledger = Path(a.ledger) if a.ledger else LEDGER

    if a.append:
        if a.issue is None:
            print("--append needs --issue N", file=sys.stderr)
            return 2
        try:
            panel = json.loads(Path(a.append).read_text(encoding="utf-8"))
        except Exception as e:
            # Never a gate. A ledger that cannot be written must not stop a batch that the
            # panel already passed -- the concerns are still on the issue either way.
            print(f"could not read {a.append}: {e}", file=sys.stderr)
            return 0
        n = append(rows_from_panel(panel, a.issue, a.title, a.milestone, a.run_ts, a.rounds),
                   ledger)
        print(f"recorded {n} standing concern(s) for #{a.issue}", file=sys.stderr)
        return 0

    if a.render:
        rows = read(ledger)
        if a.issue is not None:
            rows = [r for r in rows if r.get("issue") == a.issue]
        text = render(rows)
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
