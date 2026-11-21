#!/usr/bin/env python3
"""What is waiting on a person, in one place — the queue behind the human gate.

The pipeline decides everything it can and parks what it cannot. Parking is correct and it
is also where the design quietly ends: the issue gets a label, a plan, a panel, and then it
waits on a human who has to *notice*. Until now noticing meant reading the tail of a console
log on whichever box the queue ran on. A gate whose escalation path is "someone remembers to
look" is not an escalation path.

So the state that needs a person is assembled here, from GitHub — which is the source of
truth for this project and the one place both the box and CI can see — and published three
ways, all of them the SAME queue rendered differently:

  * a page on the docs site, for looking;
  * one rolling digest issue, for the sitting (never one notification per plan — that is the
    pager this whole design exists to avoid);
  * a decision packet posted on the issue itself the moment it is parked, so the person who
    is assigned can rule without reconstructing anything.

Every parked issue carries a machine-readable stamp in its park comment (`<!-- gaia-park:{…} -->`,
written by gaia_run_queue.sh) naming the commit its plan was judged against and the files the
plan said it would touch. That is what lets CI measure staleness with no access to the box's
`.gaia-runs/`: the repository is checked out, the commit is in it, and the rest is `git`.

Usage:
    python gaia_human_queue.py --from-github --repo owner/name --html docs/gaia-human-queue.html
    python gaia_human_queue.py --from-json queue.json --markdown      # offline, for CI and tests
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO_ROOT = HERE.parents[1]

LABEL = "needs-human-decision"
DIGEST_LABEL = "gaia-digest"
DIGEST_TITLE = "Open decisions: what the gaia pipeline is waiting on a person for"

# The park stamp the queue writes into its park comment. An HTML comment rather than a fenced
# block: it is machinery, it should not be something a reader has to skip over, and GitHub
# hands it back verbatim in the comment body.
STAMP = re.compile(r"<!--\s*gaia-park:(\{.*?\})\s*-->", re.S)

# How long a decision may sit before the digest says so. Not a pager and not an SLA -- the
# whole point of batching is that a person chooses when to sit down. It is the number that
# turns "waiting" into "waiting too long", which is a different sentence.
OVERDUE_DAYS = 7

# `gh issue list` pages through the API itself up to this many issues. Reaching it means the
# queue may be incomplete, and fetch() says so instead of dropping the remainder silently.
FETCH_LIMIT = 1000
COMMENT_PAGE = 100       # comments per issue that the list call is relied on to return in full


def gh_json(args: list[str]) -> object | None:
    """`gh` or nothing. Every caller degrades to a smaller report rather than to an error:
    this module tells a person what is waiting; it may not itself become a thing that fails."""
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            print(out.stderr.strip()[:400], file=sys.stderr)
            return None
        return json.loads(out.stdout or "null")
    except Exception as e:
        print(f"gh failed: {e}", file=sys.stderr)
        return None


def parse_stamp(body: str) -> dict:
    """The last stamp in a comment body wins — a re-park supersedes the park before it."""
    found = STAMP.findall(body or "")
    for raw in reversed(found):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            continue
    return {}


def stamp_from_comments(comments: list[dict]) -> dict:
    for c in reversed(comments or []):
        st = parse_stamp(c.get("body", ""))
        if st:
            return st
    return {}


def fetch(repo: str, label: str = LABEL, limit: int = FETCH_LIMIT) -> list[dict]:
    """Open issues waiting on a person, each with its park stamp if it has one."""
    issues = gh_json(["issue", "list", "--repo", repo, "--label", label, "--state", "open",
                      "--limit", str(limit), "--json",
                      "number,title,url,updatedAt,createdAt,assignees,milestone,labels,comments"])
    if issues and len(issues) >= limit:
        # The list may be cut short. Say so where a person sees it (an Actions annotation on
        # the run summary), rather than ship a digest that quietly drops decisions.
        print(f"::warning::{len(issues)} open '{label}' issues reached the fetch limit of {limit}; "
              "the queue may be incomplete. Raise FETCH_LIMIT in gaia_human_queue.py.", file=sys.stderr)
    rows = []
    for it in issues or []:
        # Comments come with the list call, so a large queue is one request rather than one per
        # issue. The list may cap comments per issue (COMMENT_PAGE); an issue at the cap is
        # re-read on its own so that its newest stamp is not missed.
        comments = it.get("comments") or []
        if len(comments) >= COMMENT_PAGE:
            comments = (gh_json(["issue", "view", str(it["number"]), "--repo", repo,
                                 "--json", "comments"]) or {}).get("comments") or comments
        st = stamp_from_comments(comments)
        rows.append(dict(issue=it["number"], title=it.get("title", ""), url=it.get("url", ""),
                         updated=it.get("updatedAt", ""), created=it.get("createdAt", ""),
                         assignees=[a.get("login") for a in it.get("assignees") or []],
                         milestone=((it.get("milestone") or {}) or {}).get("title", ""),
                         labels=[l.get("name") for l in it.get("labels") or []],
                         stamp=st))
    return rows


def waiting_days(row: dict, now: datetime | None = None) -> float | None:
    """Since it was PARKED, not since the issue was opened. An issue may have existed for
    months before a panel ever looked at it; what is waiting on a person is the decision."""
    now = now or datetime.now(timezone.utc)
    for ts in ((row.get("stamp") or {}).get("ts"), row.get("updated"), row.get("created")):
        if not ts:
            continue
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                t = datetime.strptime(ts, fmt)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                return round((now - t).total_seconds() / 86400.0, 1)
            except ValueError:
                continue
    return None


def enrich(rows: list[dict], repo_dir: Path | None = None,
           now: datetime | None = None) -> list[dict]:
    """Add days-waiting, and staleness where the stamp lets us measure it.

    Staleness is the same measurement `gaia_parked.py` makes locally, computed here from the
    stamp instead of from the box's ledger — so CI, which has the repository but never had
    `.gaia-runs/`, reports the same number the run did.
    """
    try:
        from gaia_parked import measure
    except Exception:
        measure = None
    out = []
    for r in rows:
        r = dict(r)
        r["days"] = waiting_days(r, now)
        r["overdue"] = bool(r["days"] is not None and r["days"] > OVERDUE_DAYS)
        st = r.get("stamp") or {}
        r["blocking"] = st.get("blocking") or []
        r["decision"] = st.get("decision", "")
        r["cause"] = st.get("cause", "")
        if measure and repo_dir and st.get("sha"):
            m = measure(dict(issue=r["issue"], sha=st["sha"], paths=st.get("paths") or [],
                             ts=st.get("ts", "")), cwd=Path(repo_dir), now=now)
            r.update(staleness=m["verdict"], commits=m["commits"], touching=m["touching"],
                     changed=m["changed"], reasons=m["reasons"])
        else:
            r.update(staleness="unknown", commits=None, touching=None, changed=[],
                     reasons=["no park stamp on the issue"] if not st else
                             ["the repository was not available to measure against"])
        out.append(r)
    order = {"stale": 0, "unknown": 1, "aging": 2, "fresh": 3}
    out.sort(key=lambda r: (not r["overdue"], order.get(r["staleness"], 9), -(r["days"] or 0)))
    return out


# ── the three renderings of the one queue ────────────────────────────────────

def packet(row: dict, repo: str = "") -> str:
    """What is posted on the issue the moment it is parked.

    An escalation is a request for a DECISION, not a request for an investigation. If the
    person has to reconstruct the situation before they can rule on it, the interruption cost
    is the reconstruction. So this says what was asked, what stopped it, and what test would
    settle each blocking concern -- and then gets out of the way, because the plan and every
    verdict are already comments on this same issue.
    """
    st = row.get("stamp") or {}
    lines = [f"## ⚖️ This one needs you",
             "",
             f"The science panel {'blocked' if st.get('decision') == 'block' else 'stopped'} "
             f"the pre-registered plan for this issue"
             + (f" (`{st['cause']}`)" if st.get("cause") else "")
             + ". The rest of the batch carried on; this issue is parked, with its plan and "
               "every verdict already posted above.",
             "",
             "**What is being asked of you:** rule on the blocking concerns below — the plan "
             "is wrong, the concern is wrong, or the scope was overstated. Any of the three "
             "unblocks it. Nothing else in the run is waiting on this.", ""]
    if row.get("blocking"):
        lines.append("### What stopped it")
        for c in row["blocking"]:
            if isinstance(c, dict):
                lines.append(f"- **[{c.get('scope', '?')}]** {c.get('claim', '')} "
                             f"— *{c.get('persona', '?')}*")
                if c.get("decisive_test"):
                    lines.append(f"  - *decisive test:* {c['decisive_test']}")
            else:
                lines.append(f"- {c}")
        lines.append("")
    elif st:
        lines += ["### What stopped it", "",
                  "_No blocking concerns were recorded — the plan itself never validated "
                  "(timeout, or it never met the output contract). This one is a pipeline "
                  "failure, not a science one; the log is on the box._", ""]
    else:
        # No stamp at all is a different statement from a stamp with nothing in it, and
        # collapsing them would tell a reader this issue failed in a way it may not have.
        lines += ["### What stopped it", "",
                  "_This issue carries the label but no park stamp — it was parked before the "
                  "stamp existed, or labelled by hand. What stopped it is in the panel "
                  "comments on this issue, not here._", ""]
    if st.get("sha"):
        lines += [f"Parked against `{st['sha'][:9]}`"
                  + (f" · plan touches {', '.join('`' + p + '`' for p in (st.get('paths') or [])[:6])}"
                     if st.get("paths") else "")
                  + ".", ""]
    lines += ["*Posted by the gaia human gate. Remove the `needs-human-decision` label when "
              "you have ruled — that is what takes it off the queue.*"]
    return "\n".join(lines)


def markdown(rows: list[dict], repo: str = "", now: datetime | None = None) -> str:
    """The digest issue: one sitting, not one interruption per plan."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    if not rows:
        return ("## Nothing is waiting on you\n\nNo open issue carries "
                f"`{LABEL}`. The pipeline has decided everything it is allowed to decide.\n\n"
                f"*Rebuilt {stamp}.*\n")
    overdue = [r for r in rows if r["overdue"]]
    stale = [r for r in rows if r["staleness"] == "stale"]
    out = [f"## {len(rows)} decision{'' if len(rows) == 1 else 's'} waiting on a person", "",
           f"Everything here is a plan the science panel would not pass on a scope that "
           f"reaches past its own issue — a breaking change for the rest of the project, or "
           f"physics that is wrong as stated. That is the only class of question this "
           f"pipeline is supposed to bring to you.", ""]
    if overdue:
        out += [f"**{len(overdue)} {'has' if len(overdue) == 1 else 'have'} waited more than "
                f"{OVERDUE_DAYS} days.** "
                + ", ".join(f"#{r['issue']}" for r in overdue), ""]
    if stale:
        out += [f"**{len(stale)} {'is' if len(stale) == 1 else 'are'} now stale** — the tree "
                f"has moved far enough under the parked plan that re-planning is likely "
                f"cheaper than resuming: "
                + ", ".join(f"#{r['issue']}" for r in stale), ""]
    out += ["| issue | waiting | plan vs. tree | what stopped it |", "|---|---|---|---|"]
    for r in rows:
        d = f"{r['days']:.0f}d" if r["days"] is not None else "?"
        if r["blocking"]:
            c = r["blocking"][0]
            first = c.get("claim", "") if isinstance(c, dict) else str(c)
        elif r.get("stamp"):
            first = "_no blocking concern recorded — a pipeline failure, not a science one_"
        else:
            first = "_no park stamp — read the panel comments on the issue_"
        out.append(f"| #{r['issue']} | {d}{' ⚠️' if r['overdue'] else ''} | {r['staleness']} "
                   f"| {first[:140]} |")
    out += ["", "Each issue carries its pre-registered plan, every persona's verdict and a "
                "decisive test per concern, posted before any code was written. Rule on the "
                "issue; **remove the label** to take it off this queue.", "",
            f"*Rebuilt {stamp}. This issue is updated in place — it will not notify you again "
            f"unless something changes.*"]
    return "\n".join(out)


def html(rows: list[dict], repo: str = "", now: datetime | None = None) -> str:
    """The page on the docs site. Same queue, for looking at rather than acting in."""
    e = html_mod.escape
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    pill = {"stale": "s-stale", "aging": "s-aging", "fresh": "s-fresh", "unknown": "s-unknown"}
    cards = []
    for r in rows:
        d = f"{r['days']:.0f} days" if r["days"] is not None else "unknown"
        concerns = []
        for c in r["blocking"][:6]:
            if isinstance(c, dict):
                concerns.append(
                    f"<li><b>[{e(str(c.get('scope', '?')))}]</b> {e(str(c.get('claim', '')))}"
                    + (f"<div class='dt'>decisive test: {e(str(c['decisive_test']))}</div>"
                       if c.get("decisive_test") else "")
                    + f" <span class='who'>{e(str(c.get('persona', '?')))}</span></li>")
            else:
                concerns.append(f"<li>{e(str(c))}</li>")
        if not concerns:
            concerns = [("<li><i>No blocking concern recorded — the plan itself never "
                         "validated. This one is a pipeline failure, not a science one.</i></li>")
                        if r.get("stamp") else
                        ("<li><i>No park stamp on this issue — parked before the stamp existed, "
                         "or labelled by hand. What stopped it is in the panel comments on the "
                         "issue.</i></li>")]
        cards.append(f"""
    <article class="card">
      <header>
        <a class="num" href="{e(r['url'])}">#{r['issue']}</a>
        <h3>{e(r['title'])}</h3>
        <div class="tags">
          <span class="pill {'s-over' if r['overdue'] else 's-wait'}">waiting {e(d)}</span>
          <span class="pill {pill.get(r['staleness'], 's-unknown')}">plan vs. tree: {e(r['staleness'])}</span>
          {f'<span class="pill s-ms">{e(r["milestone"])}</span>' if r.get("milestone") else ''}
        </div>
      </header>
      <ul class="concerns">{''.join(concerns)}</ul>
      <p class="why">{e('; '.join(r.get('reasons') or []))}</p>
    </article>""")
    empty = """
    <div class="empty"><h3>Nothing is waiting on you.</h3>
      <p>No open issue carries <code>needs-human-decision</code>. The pipeline has decided
         everything it is allowed to decide.</p></div>"""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>What needs a person</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&family=JetBrains+Mono:wght@400;600&display=swap">
<style>
:root{{
  --ink:#1a1a2e; --muted:#5a5a6e; --line:#e4e4ec; --bg:#f7f7fb; --card:#ffffff; --sunk:#eeeef4;
  --proceed:#009E73; --defer:#0072B2; --block:#D55E00; --human:#CC79A7;
  --proceed-wash:#e2f3ed; --defer-wash:#dfecf6; --block-wash:#fbe8dc; --human-wash:#f7e8f0;
  --serif:"Source Serif 4",Georgia,serif;
  --sans:"Inter",system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{
  --ink:#e8e8f0; --muted:#a0a0b4; --line:#2a2a3a; --bg:#141420; --card:#1c1c2a; --sunk:#181824;
  --proceed:#4cc4a0; --defer:#5aa9db; --block:#f0854a; --human:#dc9cc0;
  --proceed-wash:#152a25; --defer-wash:#13232f; --block-wash:#2d1d13; --human-wash:#2a1c25;}}}}
:root[data-theme="dark"]{{
  --ink:#e8e8f0; --muted:#a0a0b4; --line:#2a2a3a; --bg:#141420; --card:#1c1c2a; --sunk:#181824;
  --proceed:#4cc4a0; --defer:#5aa9db; --block:#f0854a; --human:#dc9cc0;
  --proceed-wash:#152a25; --defer-wash:#13232f; --block-wash:#2d1d13; --human-wash:#2a1c25;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:16.5px;line-height:1.6;-webkit-font-smoothing:antialiased}}
main{{max-width:min(1040px,100%);margin:0 auto;padding:clamp(1.5rem,4vw,3.5rem) clamp(1rem,4vw,2rem) 5rem;
  display:grid;gap:2rem}}
h1,h2,h3{{font-family:var(--serif);margin:0;text-wrap:balance;letter-spacing:-.012em}}
h1{{font-size:clamp(2rem,5vw,2.9rem);line-height:1.07;font-weight:700}}
h3{{font-size:1.08rem;font-weight:600}}
p{{margin:0}}
.eyebrow{{font-family:var(--mono);font-size:.7rem;font-weight:600;letter-spacing:.14em;
  text-transform:uppercase;color:var(--human);margin:0}}
.lede{{color:var(--muted);max-width:64ch}}
.meta{{font-family:var(--mono);font-size:.74rem;color:var(--muted);
  border-top:1px solid var(--line);padding-top:.8rem;display:flex;gap:1.4rem;flex-wrap:wrap}}
.queue{{display:grid;gap:1rem}}
.card{{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--human);
  border-radius:8px;padding:1.1rem 1.2rem;display:grid;gap:.7rem}}
.card header{{display:grid;gap:.45rem}}
.num{{font-family:var(--mono);font-size:.78rem;font-weight:600;color:var(--human);
  text-decoration:none}}
.num:hover{{text-decoration:underline}}
.tags{{display:flex;gap:.4rem;flex-wrap:wrap}}
.pill{{font-family:var(--mono);font-size:.66rem;font-weight:600;letter-spacing:.05em;
  padding:.2rem .5rem;border-radius:999px;background:var(--w,var(--sunk));
  color:var(--c,var(--muted));border:1px solid color-mix(in srgb,var(--c,var(--line)) 30%,transparent)}}
.s-wait{{--w:var(--defer-wash);--c:var(--defer)}}
.s-over{{--w:var(--block-wash);--c:var(--block)}}
.s-stale{{--w:var(--block-wash);--c:var(--block)}}
.s-aging{{--w:var(--human-wash);--c:var(--human)}}
.s-fresh{{--w:var(--proceed-wash);--c:var(--proceed)}}
.s-unknown{{--w:var(--sunk);--c:var(--muted)}}
.s-ms{{--w:var(--sunk);--c:var(--muted)}}
.concerns{{margin:0;padding-left:1.1rem;display:grid;gap:.5rem}}
.concerns li{{font-size:.94rem}}
.dt{{font-family:var(--mono);font-size:.76rem;color:var(--muted);margin-top:.2rem}}
.who{{font-size:.78rem;color:var(--muted)}}
.why{{font-size:.8rem;color:var(--muted);font-style:italic}}
.empty{{background:var(--proceed-wash);border:1px solid var(--line);border-left:3px solid var(--proceed);
  border-radius:8px;padding:1.4rem;display:grid;gap:.5rem}}
.note{{background:var(--sunk);border-left:3px solid var(--defer);border-radius:6px;
  padding:1rem 1.1rem;display:grid;gap:.5rem;font-size:.92rem}}
code{{font-family:var(--mono);font-size:.86em;background:var(--sunk);padding:.08em .34em;
  border-radius:4px;border:1px solid var(--line)}}
a{{color:var(--defer)}}
</style></head><body><main>
<header>
  <p class="eyebrow">The gaia human gate</p>
  <h1>What needs a person</h1>
  <p class="lede">Everything below is a plan the science panel would not pass on a scope that
    reaches past its own issue — a breaking change for the rest of the project, or physics
    that is wrong as stated. That is the <b>only</b> class of question this pipeline is
    supposed to bring to a human. Everything it could decide, it decided.</p>
  <div class="meta"><span>{len(rows)} waiting</span>
    <span>{sum(1 for r in rows if r['overdue'])} over {OVERDUE_DAYS} days</span>
    <span>{sum(1 for r in rows if r['staleness'] == 'stale')} stale</span>
    <span>rebuilt {e(stamp)}</span></div>
</header>
<div class="queue">{''.join(cards) if cards else empty}</div>
<div class="note">
  <p><b>Ruling takes it off this list.</b> Each issue carries its pre-registered plan, every
     persona's verdict and a decisive test per concern — posted before any code was written,
     at the one moment the objection could still have changed the answer. Rule on the issue
     and remove the <code>needs-human-decision</code> label.</p>
  <p><b>"Plan vs. tree" is not how old the issue is.</b> It is how far the repository has moved
     under the parked plan — commits rewriting the very files the plan named. <code>stale</code>
     means re-planning is probably now cheaper than resuming; the panel's verdicts are still
     worth reading either way.</p>
</div>
</main></body></html>
"""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from-github", action="store_true")
    p.add_argument("--from-json", metavar="FILE", help="rows as JSON; offline, for tests")
    p.add_argument("--repo", default="")
    p.add_argument("--repo-dir", metavar="DIR", default=str(REPO_ROOT))
    p.add_argument("--label", default=LABEL)
    p.add_argument("--html", metavar="FILE")
    p.add_argument("--markdown", action="store_true")
    p.add_argument("--json", metavar="FILE")
    p.add_argument("--packet", type=int, metavar="ISSUE",
                   help="print the decision packet for one parked issue and exit")
    a = p.parse_args()

    if a.from_json:
        rows = json.loads(Path(a.from_json).read_text(encoding="utf-8"))
    elif a.from_github:
        if not a.repo:
            print("--from-github needs --repo owner/name", file=sys.stderr)
            return 2
        rows = fetch(a.repo, a.label)
    else:
        p.print_help()
        return 2

    rows = enrich(rows, Path(a.repo_dir) if a.repo_dir else None)

    if a.packet is not None:
        match = [r for r in rows if r["issue"] == a.packet]
        if not match:
            print(f"#{a.packet} is not on the queue", file=sys.stderr)
            return 1
        print(packet(match[0], a.repo))
        return 0
    if a.html:
        Path(a.html).parent.mkdir(parents=True, exist_ok=True)
        Path(a.html).write_text(html(rows, a.repo), encoding="utf-8")
        print(f"wrote {a.html} ({len(rows)} waiting)", file=sys.stderr)
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if a.markdown or not (a.html or a.json):
        print(markdown(rows, a.repo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
