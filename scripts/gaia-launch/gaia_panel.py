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

What a block means is narrower than it first was. A panel of domain experts reviewing a
milestone will always find real science to say about it; if every finding stops the batch,
the gate stops being a gate and becomes a pager. So each concern now declares a SCOPE
alongside its severity (see VALID_SCOPE), and only a critical concern that reaches past this
issue -- a breaking change for the rest of the project, or physics that is simply wrong --
stops the work. The rest are deferred: recorded, published, and handed to the implementer.

Every persona here is READ-ONLY by tool grant, so this stage physically cannot touch the
working tree. It cannot introduce the bug it is meant to prevent.

Usage:
    python gaia_panel.py --route --labels "hydrogeology,P0" --milestone "Water budget: ..."
    python gaia_panel.py --aggregate v1.json v2.json [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
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

REPO_ROOT = Path(__file__).resolve().parents[2]
# The scope series (follow-up 3): one row per panel, appended at aggregate time. Lives beside
# the standing-concerns ledger because it answers the same kind of question -- what is this
# process actually doing, across runs -- rather than anything about a single issue.
SCOPE_LOG = REPO_ROOT / ".gaia-runs" / "panel-scope.jsonl"

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
    "modflow":         ["twin-hydrogeologist", "twin-da-methodologist"],
}
# Milestones are curated epics and carry more signal than any single label.
BY_MILESTONE_KEYWORD = {
    "applied math":   ["twin-da-methodologist", "twin-geostatistician"],
    "groundwater model": ["twin-hydrogeologist", "twin-geostatistician"],
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
    for lab in ("modflow", "hydrogeology", "water-budget", "soil-reanalysis", "dv-v", "geotech",
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

# SEVERITY says how wrong a concern is. SCOPE says how far its consequences reach. Collapsing
# the two is what made the first supervised run unusable: on #186 all three personas returned
# `revise`, nobody voted `block`, and the aggregator turned twelve `critical`s into a stopped
# batch and a paged human. Eleven of those twelve were real science that belonged INSIDE the
# milestone; one or two would genuinely have propagated into the rest of the project.
#
# The reviewers were already making that distinction implicitly. They just had nowhere to
# record it, so the gate could not act on it. This is the field.
#
#   breaking      -- the plan fixes an interface, artifact name, unit convention or assumption
#                    that OTHER issues will build on. Wrong here means rework elsewhere later.
#   wrong-physics -- the result would be physically or mathematically incorrect as stated,
#                    not merely under-validated or imprecise.
#   in-milestone  -- real, but its correction lives inside this issue's own deliverable, or
#                    in a follow-up that can be filed and scheduled.
#
# Only the first two, at `critical`, stop the work. That is the rule a human would apply
# reading these verdicts, made mechanical instead of hoped for.
VALID_SCOPE = ("breaking", "wrong-physics", "in-milestone")
DEFAULT_BLOCK_ON = ("breaking", "wrong-physics")

# A review round after the first is an ADJUDICATION, not a fresh review. Without this the
# panel cannot converge: each round is a new `claude -p` session that has never seen its own
# previous verdict, so it re-derives from the plan in front of it and is free to resolve
# nothing, drop what it said last time, and raise something else instead. Rounds then differ
# without ever getting closer, and the revision budget buys noise.
#
# So on round 2+ each persona is handed ITS OWN previous verdict and the diff of what the
# planner changed, and must rule on every prior concern before raising anything new.
#
#   resolved  -- the revision answers it.
#   unresolved-- it still stands. The claim below says what is STILL wrong, not a restatement.
#   withdrawn -- the reviewer no longer believes it. Allowed on purpose: a panel that can
#                never back down converges by attrition, which is not convergence.
#
# The counts these produce are what make "is this converging?" a number instead of an
# impression -- and a round where nothing moved is a stalemate, which is a human's problem,
# not something to spend another planning session on.
VALID_PRIOR_STATUS = ("resolved", "unresolved", "withdrawn")


def referent_tools():
    """`referents()` and `affinity()` from the ledger module, or (None, None).

    Three things here now group concerns by what they POINT AT rather than by wording -- the
    panel's own convergence, the standing ledger, and the adjudication grading below. They
    must use one rule and one threshold, so there is one implementation and every caller
    degrades to silence rather than to a second, subtly different notion of "the same thing".
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from gaia_concerns import affinity, referents
        return affinity, referents
    except Exception:
        return None, None


def same_thing(claim: str, others: list[str], df: Counter) -> bool:
    """Does `claim` point at the same referent as any of `others`, at the shared threshold?"""
    affinity, _ = referent_tools()
    if affinity is None:
        return False
    return any(affinity(claim, o, df) >= 1.0 for o in others)


def block_on(env: dict | None = None) -> tuple[str, ...]:
    """Which scopes a critical concern must carry to stop implementation.

    GAIA_PANEL_BLOCK_ON overrides it, but an empty or unrecognised value falls back to the
    default rather than to "nothing blocks": a typo in an env var must not silently open the
    gate. To widen the gate, name the scopes; there is deliberately no way to close it to none.
    """
    raw = (env if env is not None else os.environ).get("GAIA_PANEL_BLOCK_ON", "")
    picked = tuple(s for s in (t.strip().lower().replace("_", "-") for t in raw.split(","))
                   if s in VALID_SCOPE)
    return picked or DEFAULT_BLOCK_ON


def normalise_verdict(raw: dict, persona: str) -> dict:
    """Fail CLOSED. An unparseable or malformed verdict is a block, never an approval --
    the same rule the auditor merge gate already runs on."""
    if not isinstance(raw, dict):
        return dict(persona=persona, verdict="block", concerns=[dict(
            severity="critical", scope="breaking", scope_declared=False,
            claim="verdict was not a JSON object",
            decisive_test="re-run the persona and capture its fenced JSON")],
            prior_concerns=[])
    v = str(raw.get("verdict", "")).strip().lower()
    if v not in VALID_VERDICTS:
        return dict(persona=persona, verdict="block", concerns=[dict(
            severity="critical", scope="breaking", scope_declared=False,
            claim=f"unrecognised verdict {raw.get('verdict')!r}",
            decisive_test="re-run the persona; valid verdicts are approve/revise/block")],
            prior_concerns=[])
    cons = []
    for c in raw.get("concerns") or []:
        if not isinstance(c, dict):
            continue
        sev = str(c.get("severity", "minor")).strip().lower()
        # An undeclared or unrecognised scope falls back to `breaking`, i.e. it blocks. Same
        # fail-closed convention as everything else here, and it means a persona that ignores
        # the new field behaves exactly like the old gate rather than slipping past it.
        sc = str(c.get("scope", "")).strip().lower().replace("_", "-")
        declared = sc in VALID_SCOPE
        cons.append(dict(severity=sev if sev in VALID_SEVERITY else "minor",
                         scope=sc if declared else "breaking",
                         scope_declared=declared,
                         claim=str(c.get("claim", ""))[:400],
                         decisive_test=str(c.get("decisive_test", ""))[:400]))
    priors = []
    for c in raw.get("prior_concerns") or []:
        if not isinstance(c, dict):
            continue
        st = str(c.get("status", "")).strip().lower()
        # An unrecognised status is `unresolved`: malformed output does not get to claim that
        # a concern was answered. Same direction of failure as everything else in this file.
        priors.append(dict(status=st if st in VALID_PRIOR_STATUS else "unresolved",
                           claim=str(c.get("claim", ""))[:400],
                           why=str(c.get("why", ""))[:400]))
    return dict(persona=persona, verdict=v, concerns=cons, prior_concerns=priors,
                report=str(raw.get("report", ""))[:20000])


def scope_mix(verdicts: list[dict], scopes: tuple[str, ...] | None = None) -> dict:
    """The panel's own declared scope split -- the measurement, not a decision.

    Scope is self-declared, and it is the field that decides whether work stops. That is an
    incentive: a reviewer who learns that `in-milestone` never blocks can be heard louder by
    calling the next one `breaking`, and nothing in the gate would notice the drift because
    every individual panel would look reasonable. The design claim ("reviewers declare scope
    honestly") is therefore not something to assert -- it is something to log per panel and
    read as a series.

    `stops_share` is the number that matters: the fraction of a panel's concerns that carry
    the combination which actually halts implementation, critical AND a blocking scope. It is
    reported here and gated on nowhere; a metric that feeds a gate stops measuring and starts
    being optimised.
    """
    scopes = tuple(scopes) if scopes else block_on()
    z = lambda: {s: 0 for s in VALID_SCOPE}                                     # noqa: E731
    out = dict(n_concerns=0, undeclared=0, by_scope=z(), critical_by_scope=z(),
               by_severity={s: 0 for s in VALID_SEVERITY}, per_persona={},
               block_on=list(scopes), stops=0, stops_share=0.0)
    for v in verdicts:
        pp = out["per_persona"].setdefault(v["persona"],
                                           dict(n_concerns=0, by_scope=z(),
                                                critical_by_scope=z(), stops=0))
        for c in v["concerns"]:
            sc, sev = c.get("scope", "breaking"), c.get("severity", "minor")
            if sc not in VALID_SCOPE:
                sc = "breaking"
            out["n_concerns"] += 1
            out["by_scope"][sc] += 1
            out["by_severity"][sev if sev in VALID_SEVERITY else "minor"] += 1
            out["undeclared"] += 0 if c.get("scope_declared", True) else 1
            pp["n_concerns"] += 1
            pp["by_scope"][sc] += 1
            if sev == "critical":
                out["critical_by_scope"][sc] += 1
                pp["critical_by_scope"][sc] += 1
                if sc in scopes:
                    out["stops"] += 1
                    pp["stops"] += 1
    if out["n_concerns"]:
        out["stops_share"] = round(out["stops"] / out["n_concerns"], 3)
    return out


def scope_log_row(agg: dict, issue: int | None = None, run_ts: str = "",
                  rounds: int = 1) -> dict:
    """One panel's scope split, flattened for the series."""
    mix = agg.get("scope_mix") or scope_mix(agg.get("verdicts", []))
    return dict(run_ts=run_ts, issue=issue, round=rounds, decision=agg.get("decision", "?"),
                n_personas=agg.get("n_personas", 0), **mix)


def append_scope_log(row: dict, path: Path = SCOPE_LOG) -> int:
    """Never a gate: a measurement that cannot be written must not stop a batch."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return 1
    except Exception:
        return 0


def read_jsonl(path: Path) -> list[dict]:
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


def scope_report(rows: list[dict]) -> str:
    """The series, and an honest statement of what it can and cannot yet show.

    The question is drift: does the share of concerns carrying the scope that stops work rise
    as personas learn what stops work? That is a question about a TREND, and a trend is not
    readable from one or two panels. So the report states the sample size first and refuses to
    call a direction until there is one -- a dashboard that reports a slope from n=2 is how a
    project convinces itself of something it has not measured.
    """
    if not rows:
        return ("# Declared scope, panel by panel\n\nNo panels logged yet. Each panel "
                "appends one row when it aggregates.\n")
    def share(r):
        return r.get("stops_share", 0.0)
    out = ["# Declared scope, panel by panel", "",
           "Scope is **self-declared**, and it is the field that decides whether work stops. "
           "A reviewer who learns that `in-milestone` never blocks can be heard louder by "
           "calling the next concern `breaking`. Every individual panel would still look "
           "reasonable, so the drift is only visible as a series — which is what this is. "
           "Nothing here gates anything: a measurement that feeds a gate stops measuring.", "",
           "| panel | issue | round | decision | concerns | breaking | wrong-physics | "
           "in-milestone | undeclared | stops | share |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        by = r.get("by_scope") or {}
        out.append(f"| {i} | #{r.get('issue', '?')} | {r.get('round', '?')} | "
                   f"{r.get('decision', '?')} | {r.get('n_concerns', 0)} | "
                   f"{by.get('breaking', 0)} | {by.get('wrong-physics', 0)} | "
                   f"{by.get('in-milestone', 0)} | {r.get('undeclared', 0)} | "
                   f"{r.get('stops', 0)} | {share(r):.0%} |")
    out.append("")

    n = len(rows)
    if n < 6:
        out += [f"**{n} panel(s) — too few to read a trend.** This is a baseline. The question "
                f"is whether `stops` share rises over successive panels; answering it needs a "
                f"series, and saying anything directional from {n} is the same overreach the "
                f"panel exists to catch.", ""]
    else:
        h = n // 2
        a = sum(share(r) for r in rows[:h]) / h
        b = sum(share(r) for r in rows[h:]) / (n - h)
        d = b - a
        verdict = ("no detectable drift" if abs(d) < 0.05 else
                   "**rising** — the share of concerns scoped to stop work is going up"
                   if d > 0 else "falling")
        out += [f"**{n} panels.** First half {a:.0%} of concerns scoped to stop work, second "
                f"half {b:.0%} — {verdict}. This is a description of the series, not a test: "
                f"the panels differ in issue, milestone and reviewer, and none of that is "
                f"controlled for.", ""]

    per: dict[str, dict] = defaultdict(lambda: dict(panels=0, n=0, stops=0))
    for r in rows:
        for who, pp in (r.get("per_persona") or {}).items():
            per[who]["panels"] += 1
            per[who]["n"] += pp.get("n_concerns", 0)
            per[who]["stops"] += pp.get("stops", 0)
    if per:
        out += ["## By reviewer", "",
                "*Where inflation would show first. Read the panel count before the share: one "
                "panel is an anecdote about one issue, not a disposition.*", "",
                "| reviewer | panels | concerns | stops | share |", "|---|---|---|---|---|"]
        for who, d in sorted(per.items(), key=lambda kv: -kv[1]["stops"]):
            sh = d["stops"] / d["n"] if d["n"] else 0.0
            out.append(f"| {who} | {d['panels']} | {d['n']} | {d['stops']} | {sh:.0%} |")
        out.append("")
    return "\n".join(out)


def grade_priors(verdicts: list[dict], prev: dict | None,
                 scopes: tuple[str, ...] | None = None) -> dict:
    """Did this round move what was actually BLOCKING, or only what was cheap to give up?

    `moved = resolved + withdrawn` treats every ruling as progress, and that is gameable in
    the cheapest possible way: a persona with one blocking concern it will not drop can
    withdraw a minor one it never cared about, `moved` becomes 1, the stalemate rule goes
    quiet, and the queue buys another planning round that settles nothing. Nothing noticed,
    because nothing checked WHICH concern moved.

    So each prior ruling is matched back to the previous round's blocking concerns -- by
    referent, the same rule convergence and the ledger use -- and only a ruling on one of
    those counts as movement. Rulings that match nothing that blocked are reported as
    `hollow`: not an accusation (a reviewer may legitimately withdraw a deferred concern),
    but the difference between "we are converging" and "we are moving the deck chairs".

    Grading needs the previous round's aggregate. Without it -- round 1, or a missing file --
    this returns graded=False and the caller keeps the old count-everything rule, so the
    absence of the previous panel can never be what opens the gate.
    """
    scopes = tuple(scopes) if scopes else block_on()
    prev_block = list((prev or {}).get("blocking_concerns") or []) if isinstance(prev, dict) else []
    out = dict(graded=False, prev_blocking=len(prev_block), moved_blocking=0,
               still_blocking=0, hollow=[])
    affinity, referents = referent_tools()
    if not prev_block or affinity is None:
        return out
    out["graded"] = True

    by_persona: dict[str, list[str]] = defaultdict(list)
    for c in prev_block:
        by_persona[c.get("persona", "?")].append(c.get("claim", "") or "")

    for v in verdicts:
        mine = by_persona.get(v["persona"], [])
        # A persona that blocked nothing last round cannot unblock anything this round. Its
        # rulings are real work and are counted in prior_adjudicated; they are just not the
        # thing standing between this issue and implementation.
        if not mine:
            continue
        df: Counter = Counter()
        for claim in mine:
            df.update(referents(claim))
        for pc in v.get("prior_concerns", []):
            local = df + Counter(referents(pc.get("claim", "")))
            hit = same_thing(pc.get("claim", ""), mine, local)
            pc["on_blocking"] = bool(hit)          # travels into panel.json, and is rendered
            if pc["status"] in ("resolved", "withdrawn"):
                if hit:
                    out["moved_blocking"] += 1
                else:
                    out["hollow"].append(dict(persona=v["persona"], status=pc["status"],
                                              claim=pc.get("claim", "")[:200]))
            elif hit:
                out["still_blocking"] += 1
    return out


def aggregate(verdicts: list[dict], scopes: tuple[str, ...] | None = None,
              prev: dict | None = None) -> dict:
    """Panel decision.

    Stops implementation for exactly two reasons: a persona voted `block` outright (which
    includes every fail-closed synthetic verdict above), or a `critical` concern carries a
    scope that reaches past this issue. Everything else -- including a critical concern scoped
    `in-milestone` -- is DEFERRED: recorded, published on the issue, handed to the implementer
    as a must-address item, and available to file as a follow-up. Deferred is not discarded,
    and the panel prompt says so, because a reviewer who believes their finding will be
    dropped learns to inflate its scope until it is heard.
    """
    scopes = tuple(scopes) if scopes else block_on()
    blocking_v = [v for v in verdicts if v["verdict"] == "block"]
    blocking_c: list[dict] = []
    deferred_c: list[dict] = []
    for v in verdicts:
        for c in v["concerns"]:
            item = dict(persona=v["persona"], **c)
            if c["severity"] == "critical" and c["scope"] in scopes:
                blocking_c.append(item)
            elif c["severity"] in ("critical", "major"):
                deferred_c.append(item)
    if blocking_v or blocking_c:
        decision = "block"
    elif any(v["verdict"] == "revise" for v in verdicts) or deferred_c:
        decision = "revise"
    else:
        decision = "approve"
    # Did this round move? Only meaningful from round 2, where the personas were handed their
    # own previous verdicts to rule on. A round that resolves and withdraws NOTHING while
    # still blocking is a stalemate: the next revision would be the same conversation at the
    # same price. That is a human's call, and the queue stops spending on it.
    priors = [p for v in verdicts for p in v.get("prior_concerns", [])]
    adjudicated = {s: sum(1 for p in priors if p["status"] == s) for s in VALID_PRIOR_STATUS}
    moved = adjudicated["resolved"] + adjudicated["withdrawn"]
    # WHICH concerns moved, when the previous round is available to say. Counting any ruling
    # as movement lets one throwaway withdrawal buy a whole extra planning round while the
    # concern that actually stopped the work sits untouched. See grade_priors().
    grading = grade_priors(verdicts, prev, scopes)
    stalemate = (decision == "block" and grading["moved_blocking"] == 0) if grading["graded"] \
        else (bool(priors) and moved == 0 and decision == "block")
    return dict(decision=decision,
                n_personas=len(verdicts),
                block_on=list(scopes),
                prior_adjudicated=adjudicated,
                prior_grading=grading,
                scope_mix=scope_mix(verdicts, scopes),
                stalemate=stalemate,
                blocked_by=sorted({v["persona"] for v in blocking_v}
                                  | {c["persona"] for c in blocking_c}),
                n_critical=sum(1 for v in verdicts for c in v["concerns"]
                               if c["severity"] == "critical"),
                n_major=sum(1 for v in verdicts for c in v["concerns"] if c["severity"] == "major"),
                blocking_concerns=blocking_c,
                deferred_concerns=deferred_c,
                convergence=convergence(verdicts),
                verdict_spread=sorted({v["verdict"] for v in verdicts}),
                synthesis=None,
                verdicts=verdicts)


# ── The panel's summary ──────────────────────────────────────────────────────
# Individual verdicts are what the gate acts on. They are not what a scientist reads. Three
# reviewers filing forty-one separately-scoped concerns is a database, and the questions a
# person actually arrives with -- do they agree? where do they conflict? what has to happen
# next? -- are answerable only by reading all of it and holding it in your head.
#
# So the panel also SUMMARISES, in four sections: agreements, disagreements, critical issues,
# proposed resolution. The split of labour is deliberate and is the integrity property here:
#
#   MECHANICAL (computed below, cannot be fabricated): which reviewers converged on the same
#   referent, where the verdicts differ, and the authoritative list of critical issues -- taken
#   straight from the aggregate the gate itself used.
#
#   JUDGED (written by a chair): what the disagreements actually ARE, and what the panel
#   proposes doing about them. No mechanical rule reads scientific conflict out of prose.
#
# The chair is a REPORTER, not a judge. It is dispatched as the lab-notebook persona -- the
# documenter -- precisely because it has no scientific stake to add, and it never changes the
# decision: `decision`, `blocking_concerns` and `stalemate` are already fixed by aggregate()
# before the chair is ever called. A synthesis that fails to parse costs the prose sections
# and nothing else, which is why this stage does NOT fail closed. It cannot: it is a report
# about a decision that has already been made.
SYNTH_SECTIONS = ("agreements", "disagreements", "proposed_resolution")


def convergence(verdicts: list[dict]) -> list[dict]:
    """Where DIFFERENT reviewers landed on the same thing -- the mechanical half of agreement.

    Two personas independently naming the same file, symbol or method is the strongest signal a
    panel produces: corroboration across disciplines, which no single reviewer can manufacture.
    Keyed on referents rather than wording for the reason documented in gaia_concerns.py --
    reviewers from different fields describe one problem in entirely different words.

    The rarity weighting is what makes this mean anything. Sharing `interpolate_residuals.py`
    when six concerns mention it is not agreement, it is working in the same area: reported
    naively it produced nineteen "agreements" on a panel that had perhaps four. A shared
    referent counts only when it is one that essentially only those concerns mention, which is
    the same 1/(df-1) criterion the standing ledger uses -- one rule, one threshold, one place
    to change it.
    """
    affinity, referents = referent_tools()
    if affinity is None:
        return []
    items = [dict(persona=v["persona"], **c) for v in verdicts for c in v["concerns"]
             if c["severity"] != "minor"]
    df: Counter = Counter()
    for i in items:
        df.update(referents(i["claim"]))
    n = len(items)

    groups: list[list[dict]] = []
    for it in items:
        for g in groups:
            if any(affinity(it["claim"], m["claim"], df, n) >= 1.0 for m in g):
                g.append(it)
                break
        else:
            groups.append([it])

    out = []
    for g in groups:
        people = sorted({i["persona"] for i in g})
        if len(people) < 2:                 # one reviewer twice is not corroboration
            continue
        shared: Counter = Counter()
        for i in g:
            shared.update(referents(i["claim"]))
        # Name what they share. The `df[t] < n` filter drops boilerplate that EVERY concern on
        # the panel mentions -- which is the area they work in, not what they agree about. It
        # degenerates when the group IS the whole panel (two concerns, both about
        # Clopper-Pearson: df == n and the only real referent is filtered out), so it is a
        # preference, not a requirement. Falling back to "the same code" when we know the word
        # is strictly worse than saying it.
        common = [t for t, c in shared.most_common() if c > 1]
        out.append(dict(about=", ".join([t for t in common if df[t] < n] or common)[:120]
                        or "the same code",
                        personas=people,
                        claims=[dict(persona=i["persona"], claim=i["claim"]) for i in g]))
    return sorted(out, key=lambda g: (-len(g["personas"]), -len(g["claims"])))


def standing_prior(agg: dict, rows: list[dict], exclude_issue: int | None = None,
                   limit: int = 8) -> list[dict]:
    """Where THIS panel has landed on ground the project already has an open concern about.

    A panel is convened per issue and remembers nothing. The standing ledger is the only part
    of this pipeline that holds the project rather than the ticket -- and until now it was
    written at the end of a run and read by a human weeks later, so a panel could spend three
    personas rediscovering an objection that is already recorded, unsettled, two issues back.

    This is the cheap half of fixing that: an intersection by referent between the ledger and
    the concerns this panel just filed, handed to the chair as context and printed in the
    summary. It is a READING AID and it moves no gate -- the decision is already fixed by
    aggregate() before this is ever called, and a wrong match costs a reader one line.

    Deliberately not fed to the reviewers themselves: handing a persona the project's standing
    objections before it reviews would tell it what to say, and an independently rediscovered
    concern is evidence in a way a prompted one is not. The chair reports; the panel judges.
    """
    affinity, referents = referent_tools()
    if affinity is None:
        return []
    items = [dict(persona=v["persona"], claim=c["claim"])
             for v in agg.get("verdicts", []) for c in v.get("concerns", [])
             if c.get("severity") != "minor"]
    prior = [r for r in rows if r.get("issue") != exclude_issue and (r.get("claim") or "").strip()]
    if not items or not prior:
        return []
    df: Counter = Counter()
    for r in items + prior:
        df.update(referents(r["claim"]))
    out = []
    for r in prior:
        best, who = 0.0, None
        for it in items:
            a = affinity(r["claim"], it["claim"], df)
            if a > best:
                best, who = a, it
        if best < 1.0 or who is None:
            continue
        shared = sorted(referents(r["claim"]) & referents(who["claim"]))
        out.append(dict(issue=r.get("issue"), disposition=r.get("disposition", "?"),
                        scope=r.get("scope", "?"), persona=r.get("persona", "?"),
                        claim=r.get("claim", ""), decisive_test=r.get("decisive_test", ""),
                        about=", ".join(shared)[:120], score=round(best, 3),
                        echoed_by=who["persona"]))
    out.sort(key=lambda d: (-d["score"], d["issue"] or 0))
    return out[:limit]


def normalise_synthesis(raw: dict) -> dict:
    """Fail SOFT. The decision is already made; a malformed summary loses prose, never a gate."""
    out = {k: "" for k in SYNTH_SECTIONS}
    out["ok"] = False
    if not isinstance(raw, dict):
        return out
    for k in SYNTH_SECTIONS:
        val = raw.get(k)
        if isinstance(val, list):
            val = "\n".join(f"- {x}" for x in val if isinstance(x, str))
        out[k] = str(val or "")[:6000]
    out["ok"] = any(out[k].strip() for k in SYNTH_SECTIONS)
    return out


def render(agg: dict) -> str:
    icon = {"approve": "✅", "revise": "✏️", "block": "⛔"}[agg["decision"]]
    scopes = "`" + "` / `".join(agg.get("block_on") or DEFAULT_BLOCK_ON) + "`"
    n_block, n_defer = len(agg.get("blocking_concerns", [])), len(agg.get("deferred_concerns", []))
    out = [f"## {icon} Science panel — **{agg['decision']}**",
           "",
           f"*{agg['n_personas']} read-only personas reviewed the pre-registered plan before "
           f"any code was written. The auditor sits on every panel (ground rule 1: the maker "
           f"is never the sole judge).*",
           "",
           f"**{n_block} blocking** · **{n_defer} deferred** — implementation stops only for a "
           f"`critical` concern scoped {scopes}, or an outright `block` vote. A critical concern "
           f"scoped `in-milestone` is real science and is carried into the implementation "
           f"prompt as a must-address item; it does not stop the work.", ""]
    adj = agg.get("prior_adjudicated") or {}
    if sum(adj.values()):
        grade = agg.get("prior_grading") or {}
        line = (f"**Round 2+** — of the previous round's concerns: **{adj.get('resolved', 0)} "
                f"resolved**, {adj.get('unresolved', 0)} still standing, "
                f"{adj.get('withdrawn', 0)} withdrawn by the reviewer.")
        # Movement is only movement if it moved what was stopping the work. A ruling on a
        # concern that never blocked is real, but it is not convergence, and reporting the two
        # as one number is how a stalemate hides behind a withdrawal.
        if grade.get("graded"):
            line += (f" Of the **{grade['prev_blocking']} concern(s) that blocked** last round, "
                     f"**{grade['moved_blocking']} moved** and {grade['still_blocking']} still "
                     f"stand.")
        if agg.get("stalemate"):
            line += (" ⚠️ **Nothing that blocked moved — this is a stalemate, not a revision "
                     "cycle.**" if grade.get("graded") else
                     " ⚠️ **Nothing moved and it still blocks — this is a stalemate, not a "
                     "revision cycle.**")
        out += [line, ""]
        for h in (grade.get("hollow") or [])[:6]:
            out.append(f"- ⚠️ *{h['persona']}* ruled `{h['status']}` on a concern that was not "
                       f"among last round's blocking ones — {h['claim']}")
        if grade.get("hollow"):
            out.append("")
    # ── The four sections a reader actually arrives with questions about ──────────
    syn = agg.get("synthesis") or {}
    spread = agg.get("verdict_spread") or []
    out += ["---", "", "## Panel summary", ""]
    if len(spread) > 1:
        out += [f"The panel did not speak with one voice: verdicts were "
                f"{', '.join('`' + v + '`' for v in spread)}. The sections below are where that "
                f"matters.", ""]

    out += ["### 1. Agreements", ""]
    conv = agg.get("convergence") or []
    if conv:
        out.append("*Independently corroborated — different reviewers, same referent. This is "
                   "the strongest signal a panel produces.*")
        out.append("")
        for g in conv[:8]:
            out.append(f"- **`{g['about']}`** — {', '.join(g['personas'])}")
            for c in g["claims"]:
                out.append(f"  - *{c['persona']}:* {c['claim']}")
        out.append("")
    if syn.get("agreements"):
        out += [syn["agreements"], ""]
    elif not conv:
        out += ["_No two reviewers converged on the same referent. Each raised concerns in its "
                "own area; read the individual reports below._", ""]
    sp = agg.get("standing_prior") or []
    if sp:
        out += ["**The project has said this before.** *Standing concerns from earlier issues "
                "that point at the same code, symbols or methods — from the ledger of what two "
                "review rounds did not settle. Nobody on this panel was shown them; they were "
                "raised again independently, which is what makes the echo worth reading.*", ""]
        for e in sp:
            out.append(f"- **#{e['issue']}** `[{e['disposition']}/{e['scope']}]` — {e['claim']} "
                       f"— *{e['persona']}*"
                       + (f" · shares `{e['about']}`" if e["about"] else ""))
        out.append("")

    out += ["### 2. Disagreements", ""]
    out += [syn["disagreements"], ""] if syn.get("disagreements") else \
           ["_None recorded by the chair._" if syn.get("ok") else
            "_The chair did not report. Disagreement cannot be read out of the structured "
            "verdicts mechanically — see the individual reports below._", ""]

    out += ["### 3. Critical issues", ""]
    crit = agg["blocking_concerns"] + [c for c in agg.get("deferred_concerns", [])
                                       if c["severity"] == "critical"]
    if crit:
        out.append("*Taken verbatim from the verdicts the gate acted on, not restated by the "
                   "chair.*")
        out.append("")
        for c in crit:
            mark = "⛔ **BLOCKING**" if c in agg["blocking_concerns"] else "recorded"
            out.append(f"- {mark} · `{c['scope']}` — {c['claim']} — *{c['persona']}*")
            if c["decisive_test"]:
                out.append(f"  - *decisive test:* {c['decisive_test']}")
        out.append("")
    else:
        out += ["_No critical concerns._", ""]

    out += ["### 4. Proposed resolution", ""]
    if syn.get("proposed_resolution"):
        out += [syn["proposed_resolution"], ""]
    else:
        out += [("**A human must decide.** The panel found a problem that reaches past this "
                 "issue — a breaking change, or physics that is wrong as stated — so the issue "
                 "is parked with its plan and these verdicts, and the rest of the batch "
                 "continues." if agg["decision"] == "block" else
                 "Proceed with the plan. The concerns above are recorded and travel with the "
                 "implementation; none of them reaches past this issue."), ""]

    out += ["---", "", "## Individual reviewer reports", "",
            "*Each persona judged only its own discipline. These are their own words; the "
            "structured concerns above are extracted from them.*", ""]
    for v in agg["verdicts"]:
        out.append(f"### {v['persona']} — {v['verdict']}")
        if v.get("report"):
            out += ["", v["report"], ""]
        for p in v.get("prior_concerns", []):
            icon = {"resolved": "✅", "withdrawn": "↩️", "unresolved": "❌"}[p["status"]]
            # Only meaningful once the previous round is available to grade against, so an
            # ungraded panel says nothing rather than implying every ruling was weightless.
            mark = " · **on a blocking concern**" if p.get("on_blocking") else ""
            out.append(f"- {icon} *{p['status']}* (prior round){mark} — {p['claim']}")
            if p["why"]:
                out.append(f"  - {p['why']}")
        if not v["concerns"]:
            out.append("_no concerns_")
        for c in v["concerns"]:
            undeclared = "" if c.get("scope_declared", True) else " ⚠️ scope not declared"
            out.append(f"- **{c['severity']}** · `{c.get('scope','breaking')}`{undeclared} — {c['claim']}")
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


def persona_report(text: str) -> str:
    """The reviewer's own report: everything it wrote MINUS the machine-readable block.

    The structured concerns are what the gate acts on, but they are not what a scientist wants
    to read -- a claim capped at 400 characters with a decisive test attached is a database
    row, not an argument. The reasoning that produced it was there all along, in the reply, and
    was being discarded because only the fenced JSON was ever extracted.

    So the prose is kept and published beside the summary. A panel whose individual opinions
    are invisible cannot be audited by the people it advises: a reader who disagrees with the
    verdict has no way to see WHICH reviewer they disagree with, or why.
    """
    body = re.sub(r"```json\s*\n.*?\n```", "", text or "", flags=re.S).strip()
    # Trailing scaffolding an agent leaves around the contract, once the block itself is gone.
    body = re.sub(r"\n?(Here is|Below is|Finishing with)[^\n]{0,80}:\s*$", "", body).strip()
    return body


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
    p.add_argument("--synthesis", metavar="PANEL_JSON",
                   help="merge a chair's four-section summary into an existing panel.json; "
                        "reads the chair's stream-json transcript from --from-chair")
    p.add_argument("--from-chair", metavar="RAW_JSONL")
    p.add_argument("--brief", metavar="PANEL_JSON",
                   help="print the mechanical skeleton a chair must summarise, as markdown")
    p.add_argument("--issue", type=int,
                   help="the issue this panel is about; enables the standing-ledger "
                        "intersection and labels the scope-log row")
    p.add_argument("--ledger", metavar="FILE",
                   help="standing-concerns ledger to intersect with this panel "
                        "(default .gaia-runs/science-concerns.jsonl)")
    p.add_argument("--prev", metavar="PANEL_JSON",
                   help="the PREVIOUS round's panel.json; grades this round's rulings against "
                        "what actually blocked, so one throwaway withdrawal cannot look like "
                        "convergence")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--run-ts", default="")
    p.add_argument("--scope-log", metavar="FILE", nargs="?", const=str(SCOPE_LOG),
                   help="append this panel's declared-scope split to the series "
                        f"(default {SCOPE_LOG})")
    p.add_argument("--scope-report", metavar="FILE", nargs="?", const=str(SCOPE_LOG),
                   help="render the scope series as markdown and exit")
    p.add_argument("--block-on", metavar="SCOPES",
                   help="comma-separated scopes on which a critical concern blocks "
                        f"(default {','.join(DEFAULT_BLOCK_ON)}; also GAIA_PANEL_BLOCK_ON)")
    p.add_argument("--json", metavar="OUT")
    p.add_argument("--render", action="store_true")
    a = p.parse_args()

    if a.expect_for:
        print(expected_subagent_type(a.expect_for))
        return 0

    if a.scope_report:
        text = scope_report(read_jsonl(Path(a.scope_report)))
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
        else:
            print(text)
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
            # The verdict AND the reasoning behind it. Only when the persona really was
            # dispatched: prose from a session that never delegated is the base model's, and
            # publishing it under the persona's name is the exact confusion the check prevents.
            out = dict(verdict) if isinstance(verdict, dict) else {}
            if ok:
                out["report"] = persona_report(final_text(a.from_stream))
            Path(a.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print("dispatched" if ok else "NOT-DISPATCHED", file=sys.stderr)
        return 0 if ok else 1

    if a.brief:
        # What the chair is given: the facts it must not contradict, and the reviewers' own
        # words. Generated here rather than in the shell so the chair's input and the rendered
        # output are guaranteed to be describing the same panel.
        agg = json.loads(Path(a.brief).read_text(encoding="utf-8"))
        lines = [f"Panel decision (already final, you cannot change it): **{agg['decision']}**",
                 f"Verdicts: " + ", ".join(f"{v['persona']}={v['verdict']}"
                                           for v in agg["verdicts"]), ""]
        if agg.get("convergence"):
            lines.append("MECHANICALLY DETECTED CONVERGENCE — different reviewers, same referent:")
            for g in agg["convergence"][:8]:
                lines.append(f"- {g['about']}: {', '.join(g['personas'])}")
                for c in g["claims"]:
                    lines.append(f"    {c['persona']}: {c['claim']}")
            lines.append("")
        crit = agg["blocking_concerns"] + [c for c in agg.get("deferred_concerns", [])
                                           if c["severity"] == "critical"]
        if crit:
            lines.append("CRITICAL ISSUES (authoritative list; do not restate or re-rank):")
            for c in crit:
                lines.append(f"- [{c['scope']}] {c['claim']} ({c['persona']})")
            lines.append("")
        # THE STANDING LEDGER, which is the difference between a panel for this issue and a
        # reader who holds the project. The chair is the only stage that sees both: the
        # reviewers are deliberately not shown the ledger, so an echo here is independent
        # rediscovery rather than a persona repeating what it was handed.
        sp = agg.get("standing_prior") or []
        if sp:
            lines.append("THE PROJECT'S STANDING CONCERNS THAT THIS PANEL HAS LANDED ON AGAIN "
                         "(from earlier issues, unsettled after two rounds; NO reviewer on "
                         "this panel was shown them). Say plainly if this panel is "
                         "rediscovering an open project-level problem rather than finding a "
                         "new one -- that is the single most useful thing you can tell a "
                         "reader, and no individual verdict can say it:")
            for e in sp:
                lines.append(f"- #{e['issue']} [{e['disposition']}/{e['scope']}] {e['claim']} "
                             f"({e['persona']}) -- shares {e['about'] or 'the same code'} with "
                             f"{e['echoed_by']}'s concern today")
            lines.append("")
        grade = agg.get("prior_grading") or {}
        if grade.get("graded"):
            lines.append(f"ADJUDICATION (round 2+): of the {grade['prev_blocking']} concern(s) "
                         f"that BLOCKED last round, {grade['moved_blocking']} were resolved or "
                         f"withdrawn and {grade['still_blocking']} still stand.")
            for h in grade.get("hollow") or []:
                lines.append(f"- NOTE: {h['persona']} ruled {h['status']} on a concern that was "
                             f"not among the blocking ones: {h['claim']}")
            lines.append("")
        for v in agg["verdicts"]:
            lines += [f"===== REPORT: {v['persona']} (verdict: {v['verdict']}) =====",
                      v.get("report") or "(no prose report captured)", ""]
        print("\n".join(lines))
        return 0

    if a.synthesis:
        path = Path(a.synthesis)
        agg = json.loads(path.read_text(encoding="utf-8"))
        raw = last_json_block(final_text(a.from_chair)) if a.from_chair else None
        syn = normalise_synthesis(raw)
        agg["synthesis"] = syn
        path.write_text(json.dumps(agg, indent=2), encoding="utf-8")
        if a.render:
            print(render(agg))
        print("synthesis: " + ("merged" if syn["ok"] else
                               "chair produced nothing usable; mechanical summary stands"),
              file=sys.stderr)
        return 0                      # NEVER non-zero: this is a report, not a gate

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
        prev = None
        if a.prev and Path(a.prev).exists():
            try:
                prev = json.loads(Path(a.prev).read_text(encoding="utf-8"))
            except Exception:
                prev = None                 # ungraded, i.e. the old rule. Never fails open.
        agg = aggregate(verdicts,
                        block_on({"GAIA_PANEL_BLOCK_ON": a.block_on}) if a.block_on else None,
                        prev)
        # Everything below is reporting, and every line of it fails soft: the decision above
        # is already made and nothing here may change it.
        if a.issue is not None:
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                from gaia_concerns import LEDGER, read as read_ledger
                rows = read_ledger(Path(a.ledger) if a.ledger else LEDGER)
                agg["standing_prior"] = standing_prior(agg, rows, exclude_issue=a.issue)
            except Exception:
                agg["standing_prior"] = []
        if a.scope_log:
            append_scope_log(scope_log_row(agg, a.issue, a.run_ts, a.round),
                             Path(a.scope_log))
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
