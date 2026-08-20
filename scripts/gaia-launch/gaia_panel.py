#!/usr/bin/env python3
"""Route an issue to the science personas who should judge its PLAN, and aggregate them.

The problem this exists to fix is structural, not motivational. The pipeline's only
mechanical definition of "done" is `pixi run test`. A theoretician's judgment feeds no gate,
so under gate pressure the orchestrator's shortest path to green is always the
scientific-coder, and the science personas end up decorative. Calling them more often
changes nothing; a gate has to DEPEND on them.

So the panel reviews the pre-registered plan, before any code exists -- the cheapest moment
at which a wrong approach can still be redirected -- and a `block` stops implementation.
That is our own ground rule 3 ("design-review first, audit a plan once before resources are
spent") made mechanical, and ground rule 1 (the maker is never the sole judge) enforced by
seating the auditor on every panel.

Every persona here is READ-ONLY by tool grant, so this stage physically cannot touch the
working tree. It cannot introduce the bug it is meant to prevent.

Usage:
    python gaia_panel.py --route --labels "hydrogeology,P0" --milestone "Water budget: ..."
    python gaia_panel.py --aggregate v1.json v2.json [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Two families sit on these panels and the distinction matters.
#
#   PROJECT personas (.claude/agents/twin-*.md) are specific to this twin. They were derived
#   from this repository's own review record -- docs/reviews/peer_review.md's three domain
#   reviewers, the sensor-uncertainty/covariance review, and the 2026-08 hydrologic-state and
#   prior audit -- and they carry that record's standing concerns as priors. A generic
#   "theoretician" does not know that an 18.5 m baseline RMSE cannot serve a sub-metre
#   liquefaction requirement, or that ΔD = -Δh_wt makes two prior entries an error. These do.
#
#   GAIA plugin personas (gaia-*) are the general research family. The auditor is kept for
#   its independence, and the debugger and lab-notebook for work that is genuinely about
#   software or documentation rather than about this twin's science.
#
# Dispatch names differ: project agents resolve as a BARE name, plugin agents as `gaia:<name>`.
# expected_subagent_type() below is the single place that knows this.
PROJECT_PREFIX = "twin-"

# The auditor sits on EVERY panel: ground rule 1, the maker is never the sole judge.
ALWAYS = ["gaia-auditor"]

# Label -> personas with genuine standing on that question. Keyed on the labels this repo
# actually uses (see gaia_group_issues.py's TOPIC_LABEL_PRIORITY), not invented ones.
BY_LABEL = {
    "hydrogeology":    ["twin-hydrogeologist", "twin-geostatistician"],
    "water-budget":    ["twin-hydrogeologist", "twin-atmospheric-scientist"],
    "soil-reanalysis": ["twin-hydrogeologist", "twin-geostatistician"],
    "dv-v":            ["twin-geostatistician", "twin-geotech-engineer"],
    "atmospheric":     ["twin-atmospheric-scientist"],
    "geotech":         ["twin-geotech-engineer", "twin-hydrogeologist"],
    "landlab":         ["twin-geotech-engineer", "twin-hydrogeologist"],
    "uncertainty":     ["twin-geostatistician", "twin-da-methodologist"],
    "validation":      ["twin-geostatistician"],
    "stage-1":         ["twin-hydrogeologist"],
    "stage-2":         ["twin-geostatistician"],
    "stage-3":         ["twin-da-methodologist", "twin-geostatistician"],
    "peer-review":     ["gaia-literature-scout"],
    "documentation":   ["gaia-lab-notebook"],
    "bug":             ["gaia-debugger"],
}
# Milestones are curated epics and carry more signal than any single label.
BY_MILESTONE_KEYWORD = {
    "applied math":   ["twin-da-methodologist", "twin-geostatistician"],
    "water budget":   ["twin-hydrogeologist", "twin-atmospheric-scientist"],
    "liquefaction":   ["twin-geotech-engineer", "twin-hydrogeologist"],
    "landslide":      ["twin-geotech-engineer", "twin-hydrogeologist"],
    "flood":          ["twin-atmospheric-scientist", "twin-hydrogeologist"],
    "hazard":         ["twin-geotech-engineer"],
    "hydrogeologic":  ["twin-hydrogeologist", "twin-geostatistician"],
    "vs30":           ["twin-geotech-engineer"],
    "software":       ["gaia-debugger"],
    "probabilistic":  ["twin-da-methodologist", "twin-geostatistician"],
    "memory":         ["twin-hydrogeologist"],
    "domain extension": ["twin-hydrogeologist"],
    "eastern cascades": ["twin-atmospheric-scientist", "twin-hydrogeologist"],
}


def expected_subagent_type(persona: str) -> str:
    """What must appear in the transcript for this persona to count as really dispatched.
    Project agents live in .claude/agents and resolve bare; plugin agents are namespaced."""
    return persona if persona.startswith(PROJECT_PREFIX) else f"gaia:{persona}"
# A plan claiming novelty or impact must face the prior-art and impact readers, whatever
# its labels say -- an unchallenged novelty claim is the classic way overreach ships.
NOVELTY_MARKERS = ("novel", "first", "new method", "unprecedented", "state of the art",
                   "outperform", "breakthrough", "no one has")

MAX_PANEL = 3          # auditor + at most 2 routed, to bound cost per issue


def route(labels: list[str], milestone: str | None, plan_text: str = "") -> list[str]:
    picked: list[str] = list(ALWAYS)
    low = {l.strip().lower() for l in labels if l.strip()}

    def add(names):
        for n in names:
            if n not in picked and len(picked) < MAX_PANEL:
                picked.append(n)

    if milestone:
        ml = milestone.lower()
        for kw, names in BY_MILESTONE_KEYWORD.items():
            if kw in ml:
                add(names)
                break
    for lab in ("hydrogeology", "water-budget", "soil-reanalysis", "dv-v", "geotech",
                "landlab", "atmospheric", "uncertainty", "validation",
                "stage-3", "stage-2", "stage-1", "peer-review", "documentation"):
        if lab in low:
            add(BY_LABEL[lab])
    if plan_text and any(m in plan_text.lower() for m in NOVELTY_MARKERS):
        add(["gaia-literature-scout", "gaia-research-impact"])
    # An issue with no routable label still gets more than one pair of eyes. Prefer a project
    # persona over a generic one: an unlabelled issue in THIS repo is still about this twin.
    if len(picked) == 1:
        add(["twin-hydrogeologist"])
    return picked


VALID_VERDICTS = ("approve", "revise", "block")
VALID_SEVERITY = ("critical", "major", "minor")


def normalise_verdict(raw: dict, persona: str) -> dict:
    """Fail CLOSED. An unparseable or malformed verdict is a block, never an approval --
    the same rule the auditor merge gate already runs on."""
    if not isinstance(raw, dict):
        return dict(persona=persona, verdict="block", concerns=[dict(
            severity="critical", claim="verdict was not a JSON object",
            decisive_test="re-run the persona and capture its fenced JSON")])
    v = str(raw.get("verdict", "")).strip().lower()
    if v not in VALID_VERDICTS:
        return dict(persona=persona, verdict="block", concerns=[dict(
            severity="critical", claim=f"unrecognised verdict {raw.get('verdict')!r}",
            decisive_test="re-run the persona; valid verdicts are approve/revise/block")])
    cons = []
    for c in raw.get("concerns") or []:
        if not isinstance(c, dict):
            continue
        sev = str(c.get("severity", "minor")).strip().lower()
        cons.append(dict(severity=sev if sev in VALID_SEVERITY else "minor",
                         claim=str(c.get("claim", ""))[:400],
                         decisive_test=str(c.get("decisive_test", ""))[:400]))
    return dict(persona=persona, verdict=v, concerns=cons)


def aggregate(verdicts: list[dict]) -> dict:
    """Panel decision. Any block, or any critical concern, stops implementation."""
    blocking = [v for v in verdicts if v["verdict"] == "block"]
    critical = [c for v in verdicts for c in v["concerns"] if c["severity"] == "critical"]
    revise = [v for v in verdicts if v["verdict"] == "revise"]
    if blocking or critical:
        decision = "block"
    elif revise:
        decision = "revise"
    else:
        decision = "approve"
    return dict(decision=decision,
                n_personas=len(verdicts),
                blocked_by=[v["persona"] for v in blocking],
                n_critical=len(critical),
                n_major=sum(1 for v in verdicts for c in v["concerns"] if c["severity"] == "major"),
                verdicts=verdicts)


def render(agg: dict) -> str:
    icon = {"approve": "✅", "revise": "✏️", "block": "⛔"}[agg["decision"]]
    out = [f"## {icon} Science panel — **{agg['decision']}**",
           "",
           f"*{agg['n_personas']} read-only personas reviewed the pre-registered plan before "
           f"any code was written. The auditor sits on every panel (ground rule 1: the maker "
           f"is never the sole judge). A `block` stops implementation.*", ""]
    for v in agg["verdicts"]:
        out.append(f"### {v['persona']} — {v['verdict']}")
        if not v["concerns"]:
            out.append("_no concerns_")
        for c in v["concerns"]:
            out.append(f"- **{c['severity']}** — {c['claim']}")
            if c["decisive_test"]:
                out.append(f"  - *decisive test:* {c['decisive_test']}")
        out.append("")
    return "\n".join(out)


def stream_events(path: str):
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def final_text(path: str) -> str:
    """The assistant's last text, out of a stream-json transcript."""
    text = ""
    for ev in stream_events(path):
        if ev.get("type") == "result" and isinstance(ev.get("result"), str):
            text = ev["result"]
        msg = ev.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                    text = b["text"]
    return text


def dispatched(path: str) -> set[str]:
    """subagent_types actually dispatched via the Task/Agent tool in this transcript."""
    out: set[str] = set()
    for ev in stream_events(path):
        msg = ev.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Task", "Agent"):
                st = (b.get("input") or {}).get("subagent_type")
                if st:
                    out.add(str(st))
    return out


def last_json_block(text: str):
    """The LAST fenced json block; agent prose may quote earlier examples."""
    blocks = re.findall(r"```json\s*\n(.*?)\n```", text, re.S)
    if not blocks:
        return None
    try:
        return json.loads(blocks[-1])
    except json.JSONDecodeError:
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--route", action="store_true")
    p.add_argument("--from-stream", metavar="RAW_JSONL",
                   help="extract a persona verdict from a stream-json transcript AND verify "
                        "the persona was really dispatched as a subagent")
    p.add_argument("--expect-for", metavar="PERSONA",
                   help="print the subagent_type that PERSONA must dispatch as, then exit")
    p.add_argument("--expect", metavar="SUBAGENT_TYPE",
                   help="the subagent_type that must appear in the transcript")
    p.add_argument("--out", metavar="FILE", help="where to write the extracted verdict JSON")
    p.add_argument("--labels", default="")
    p.add_argument("--milestone", default="")
    p.add_argument("--plan", metavar="FILE", help="plan JSON, for novelty-claim routing")
    p.add_argument("--aggregate", nargs="*", metavar="VERDICT_JSON")
    p.add_argument("--json", metavar="OUT")
    p.add_argument("--render", action="store_true")
    a = p.parse_args()

    if a.expect_for:
        print(expected_subagent_type(a.expect_for))
        return 0

    if a.from_stream:
        # Asking an agent to "use the gaia-auditor persona" is prose. Whether it DELEGATED --
        # and therefore whether the persona's system prompt, tool grant and model tier were
        # ever loaded -- is a fact in the transcript. Check the fact.
        #
        # A verdict from a session that never dispatched is the base model in costume: it
        # carries the persona's name and none of its charter. That is a silent quality
        # degradation, so it fails CLOSED, exactly like an unparseable verdict.
        expect = a.expect or ""
        got = dispatched(a.from_stream)
        verdict = last_json_block(final_text(a.from_stream))
        ok = (not expect) or any(expect in g or g.endswith(expect) for g in got)
        if not ok:
            verdict = dict(verdict="block", concerns=[dict(
                severity="critical",
                claim=f"persona {expect} was never dispatched as a subagent "
                      f"(transcript dispatched: {sorted(got) or 'nothing'}); "
                      f"this verdict is not that persona's judgment",
                decisive_test="re-run with the plugin installed and the persona name correct")])
        if a.out:
            Path(a.out).write_text(json.dumps(verdict if verdict is not None else {}, indent=2),
                                   encoding="utf-8")
        print("dispatched" if ok else "NOT-DISPATCHED", file=sys.stderr)
        return 0 if ok else 1

    if a.route:
        plan_text = Path(a.plan).read_text(encoding="utf-8") if a.plan and Path(a.plan).exists() else ""
        print(" ".join(route([l for l in a.labels.split(",") if l], a.milestone or None, plan_text)))
        return 0

    if a.aggregate is not None:
        verdicts = []
        for f in a.aggregate:
            persona = Path(f).stem
            try:
                raw = json.loads(Path(f).read_text(encoding="utf-8"))
            except Exception:
                raw = None
            verdicts.append(normalise_verdict(raw, persona))
        agg = aggregate(verdicts)
        if a.json:
            Path(a.json).write_text(json.dumps(agg, indent=2), encoding="utf-8")
        if a.render:
            print(render(agg))
        else:
            print(agg["decision"])
        return 0 if agg["decision"] != "block" else 1

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
