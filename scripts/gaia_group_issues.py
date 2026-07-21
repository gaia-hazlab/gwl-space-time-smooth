#!/usr/bin/env python3
"""Group open issues into PR-sized batches for scripts/gaia_run_queue.sh.

Grouping key, in order:
  1. milestone title, if the issue has one -- this repo's milestones are
     the user's own curated epics (e.g. "Water budget: vadose-zone physics
     & calibration"), so they're trusted over any label heuristic.
  2. otherwise, the first matching label from TOPIC_LABEL_PRIORITY.
  3. otherwise, the issue is its own solo group.

Within a group, P0-labeled issues split into their own (earlier) batch --
blocking-correctness work must not wait behind exploratory P2 work just
because they share an epic. Groups are chunked to MAX_BATCH issues so a
single PR stays reviewable. Batches are ordered by their worst (highest-
priority) member, P0 first.

Issues labeled "epic" are trackers, never work items, and are excluded.

Cross-issue dependencies (BLOCKED_BY, below) come from the probabilistic
nowcast/forecast dependency graph in
docs/probabilistic-nowcast-forecast-roadmap.md. An issue with an open
blocker is held out of this run's batches entirely -- it never gets
chunked alongside ready work, regardless of milestone/topic grouping --
so the automated queue can't dispatch e.g. #188 (cycling DA) before #187
(the canonical contract it's built on) merely because grouping put them
in the same milestone batch. Held-back issues are logged to stderr, not
silently dropped.

Emits one JSON object per line (JSONL) to stdout:
  {"key": "...", "branch": "gaia/...", "issues": [{"number": N, "title": "..."}]}
"""
import json
import re
import subprocess
import sys

MAX_BATCH = 4

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}

TOPIC_LABEL_PRIORITY = [
    "dv-v", "water-budget", "geotech", "landlab", "stage-3", "stage-2",
    "stage-1", "hydrogeology", "soil-reanalysis", "atmospheric",
    "uncertainty", "validation", "peer-review", "documentation", "bug",
    "enhancement",
]

# Execution sequence for milestoned batches: all P0 batches run first (globally,
# across every milestone/topic), then the queue proceeds one milestone at a time
# in THIS order. It follows the operating-loop spine in ROADMAP.md: cross-cutting
# infrastructure and the advance/correct foundations first (they unblock the rest),
# then the represent->propagate versioned ladder, then the Act hazards that consume
# it all. Reorder this single list to change the milestone sequence. Titles must
# match the GitHub milestone titles EXACTLY. Batches whose milestone is absent here
# (or which have no milestone -- topic/solo batches) sort after all listed milestones.
MILESTONE_ORDER = [
    "Software: CI, tests, reproducibility, scale",
    "Water budget: vadose-zone physics & calibration",
    "Applied math: DA estimator correctness",
    "v0.2 — Hydrogeologic realism",
    "v0.3 — Vs30 densification (SVM → 90 m, obs-anchored)",
    "v0.4 — Domain extension: western Cascades (gauged-basin coverage)",
    "v0.5 — Eastern Cascades: Stehekin (rain shadow, snow-dominated)",
    "v0.6 — Memory & disturbance (hysteresis + coseismic/wildfire/agricultural)",
    "v0.7 — Probabilistic nowcast and ensemble forecast",
    "Hazard: LandLab landslide handoff",
    "Hazard: Sanger-Maurer liquefaction framework",
    "Hazard: flood / inundation handoff",
]


# Precomputed once so sorting is a dict lookup, not a linear scan per batch.
_MILESTONE_RANK = {title: i for i, title in enumerate(MILESTONE_ORDER)}


def milestone_rank(milestone):
    """Position in MILESTONE_ORDER; unlisted/None sorts after all listed milestones."""
    return _MILESTONE_RANK.get(milestone, len(MILESTONE_ORDER))

# Direct blockers only (not transitively expanded) -- an issue is held back
# if ANY of its listed blockers is still open. Transitive blocking falls
# out naturally: #188 blocks on #187, and #192 blocks on #188, so #192
# stays held back for as long as #187 does too, without needing to list
# #187 again under #192.
BLOCKED_BY = {
    187: [186, 52, 89, 137, 171, 172],   # canonical contract needs corrected UQ, theta, water/timestep fixes
    189: [187],                          # operational obs records need the canonical contract
    188: [154, 187, 189],                # cycling DA needs scale, contract, and obs records
    192: [188],                          # B/Q/R diagnosis needs a running cycling DA to diagnose
    194: [192],                          # withheld-sensor value-added needs calibrated B/Q/R
    191: [188],                          # ensemble forecast needs the DA posterior it initializes from
    190: [187],                          # probabilistic mechanical memory needs the canonical contract
    193: [191],                          # joint hazard handoff needs stable member identity from #191
    195: [191, 193, 194],                # release-gate validation needs forecast, hazard, and DA value-added
    # Opus 2026-07-21 strategy review: new issues #199-#205 (see docs/reviews/opus-...).
    203: [187],                           # Earth2Studio wrapper needs the canonical (E2S-shaped) contract
    205: [194],                           # regime-switching tau is a diagnostic-gated follow-on of #194
    200: [187, 191],                      # flood source-term export needs the member contract + ensemble members
    201: [200],                           # routing pilot needs the source-term export contract
    202: [201],                           # gauge-hydrograph validation needs a routed hydrograph
}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def fetch_issues():
    raw = subprocess.check_output([
        "gh", "issue", "list", "--state", "open", "--limit", "500",
        "--json", "number,title,labels,milestone",
    ])
    return json.loads(raw)


def priority_of(labels):
    for lbl in labels:
        if lbl in PRIORITY_RANK:
            return lbl
    return None


def topic_of(labels):
    for candidate in TOPIC_LABEL_PRIORITY:
        if candidate in labels:
            return candidate
    return None


def main():
    issues = fetch_issues()
    open_numbers = {issue["number"] for issue in issues}
    groups = {}

    for issue in issues:
        labels = [l["name"] for l in issue["labels"]]
        if "epic" in labels:
            continue

        blockers = [b for b in BLOCKED_BY.get(issue["number"], []) if b in open_numbers]
        if blockers:
            print(
                f"holding back #{issue['number']} ({issue['title']}): "
                f"blocked by open {', '.join('#' + str(b) for b in blockers)}",
                file=sys.stderr,
            )
            continue

        milestone = issue["milestone"]["title"] if issue.get("milestone") else None
        topic = topic_of(labels)
        if milestone:
            key = f"milestone:{milestone}"
        elif topic:
            key = f"topic:{topic}"
        else:
            key = f"solo:{issue['number']}"

        groups.setdefault(key, []).append({
            "number": issue["number"],
            "title": issue["title"],
            "priority": priority_of(labels),
            "milestone": milestone,
        })

    batches = []
    for key, members in groups.items():
        p0 = [m for m in members if m["priority"] == "P0"]
        rest = [m for m in members if m["priority"] != "P0"]
        for tier_name, tier_members in (("p0", p0), ("rest", rest)):
            if not tier_members:
                continue
            for i in range(0, len(tier_members), MAX_BATCH):
                chunk = tier_members[i:i + MAX_BATCH]
                rank = min((PRIORITY_RANK.get(m["priority"], 3) for m in chunk), default=3)
                chunk_idx = i // MAX_BATCH
                batches.append({
                    "key": key,
                    "milestone": chunk[0]["milestone"],
                    "rank": rank,
                    "branch": f"gaia/{slug(key)}-{tier_name}-{chunk_idx}",
                    "issues": [{"number": m["number"], "title": m["title"]} for m in chunk],
                })

    # P0 batches first (globally), then one milestone at a time in MILESTONE_ORDER;
    # within a milestone, higher priority first, then a stable key/branch tiebreak.
    batches.sort(key=lambda b: (
        0 if b["rank"] == 0 else 1,
        milestone_rank(b["milestone"]),
        b["rank"],
        b["key"],
        b["branch"],
    ))
    for b in batches:
        print(json.dumps(b))


if __name__ == "__main__":
    main()
