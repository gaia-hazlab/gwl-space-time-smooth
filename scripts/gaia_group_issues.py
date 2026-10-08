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
  {"key": "...", "branch": "gaia/...", "issues": [{"number": N, "title": "...", "labels": [...]}]}
"""
import json
import os
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
    # Audited table, 2026-10-08 physics and backlog audit (docs/reviews/2026-10-08-physics-backlog-audit/,
    # approved by the PI). Leaf issues only -- never an epic, which only a human closes.
    # 232 water ledger, 233 valley sink, 234 snow state, 235 recorders+holdouts, 236 cal/val harness,
    # 237 gauge flux operator, 247 kernel sanity, 260 liquefaction decision, 263 lapse rate,
    # 265 hydrologic-core design record, 268 v0.4 static rebuild, 270 value-of-information gate.
    187: [52],                                # schema draft; release gates are in the issue body
    188: [187, 189, 155, 156, 232, 233],
    189: [187, 9],
    192: [188],
    194: [192],
    191: [188],
    190: [187, 121, 198],
    193: [187],
    195: [191, 194],
    203: [187, 188, 191],
    205: [194],
    172: [232, 265],
    131: [172],
    173: [172],
    174: [172, 265],
    175: [232, 233],
    137: [172, 173, 174, 175, 131, 100, 89, 235, 236],
    89: [70],
    100: [70, 234],
    130: [172, 174],
    133: [130, 174],
    176: [172, 131, 198],
    198: [172, 187, 247],
    45: [198],
    50: [198],
    30: [198],
    162: [188, 169],
    123: [162, 169],
    121: [124],
    122: [134],
    132: [134],
    226: [187, 189, 100, 172],
    223: [268],
    224: [223, 128],
    225: [172],
    227: [223, 232, 234, 263],
    129: [128],
    141: [260, 270],
    142: [137, 9],
    82: [81],
    83: [81],
    84: [81],
    86: [81, 84],
    200: [187],
    201: [232, 237],
    202: [201],
    99: [100],
    47: [21, 9],
    7: [186],
    6: [235],
}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


# Issues carrying any of these labels are human-held: never dispatched, even when selected
# explicitly with GAIA_ONLY_ISSUES. Releasing the hold means removing the label.
HOLD_LABELS = {"needs-human-decision"}

_BLOCKED_LINE = re.compile(r"^\s*\**Blocked by\**:?\**\s*(.*)$", re.IGNORECASE | re.MULTILINE)


def body_blockers(body):
    """Issue numbers named on 'Blocked by:' lines of the CURRENT scope of an issue body.

    Text after the first '<details>' is the archived original body and is ignored, so a
    superseded dependency there cannot hold an issue. Combined with BLOCKED_BY (union).
    """
    if not body:
        return []
    current = body.split("<details>", 1)[0]
    found = []
    for line in _BLOCKED_LINE.findall(current):
        found += [int(n) for n in re.findall(r"#(\d+)", line)]
    return sorted(set(found))


def fetch_issues():
    raw = subprocess.check_output([
        "gh", "issue", "list", "--state", "open", "--limit", "500",
        "--json", "number,title,labels,milestone,body",
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


def only_issues():
    """Restrict this run to chosen issues: GAIA_ONLY_ISSUES="186" or "153,152".

    For SUPERVISED runs. The queue works whichever batch sorts first, which is not
    necessarily the batch an operator wants to sit and watch -- the first batch is
    currently CI/reproducibility work, which routes to no project persona at all. This
    filters the INPUT rather than the output, so grouping, P0 splitting, chunking,
    blocker hold-back and ordering all behave exactly as in a real run: the batch that
    comes out is the batch that would have come out anyway, with the others withheld.

    Unset (the normal case) returns None and changes nothing.
    """
    raw = os.environ.get("GAIA_ONLY_ISSUES", "").strip()
    if not raw:
        return None
    picked = {int(tok.lstrip("#")) for tok in re.split(r"[,\s]+", raw) if tok.strip()}
    if not picked:
        return None
    return picked


def main():
    issues = fetch_issues()
    # Blockers are judged against EVERY open issue, never the selected subset. Computing
    # this after the GAIA_ONLY_ISSUES filter would make an unselected blocker look closed
    # and silently disable the hold-back guard -- the exact class of quiet degradation
    # this repo keeps having to design against.
    open_numbers = {issue["number"] for issue in issues}

    only = only_issues()
    if only is not None:
        missing = sorted(only - open_numbers)
        if missing:
            print("GAIA_ONLY_ISSUES: not open (ignored): "
                  + ", ".join("#" + str(n) for n in missing), file=sys.stderr)
        issues = [i for i in issues if i["number"] in only]
        if not issues:
            print("GAIA_ONLY_ISSUES matched no open issue -- emitting no batches.",
                  file=sys.stderr)
        else:
            print("GAIA_ONLY_ISSUES: restricting this run to "
                  + ", ".join("#" + str(i["number"]) for i in issues), file=sys.stderr)

    groups = {}

    for issue in issues:
        labels = [l["name"] for l in issue["labels"]]
        if "epic" in labels:
            continue
        held = sorted(HOLD_LABELS.intersection(labels))
        if held:
            print(f"holding back #{issue['number']} ({issue['title']}): labelled {', '.join(held)}",
                  file=sys.stderr)
            continue

        declared = set(BLOCKED_BY.get(issue["number"], [])) | set(body_blockers(issue.get("body")))
        blockers = sorted(b for b in declared if b in open_numbers and b != issue["number"])
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
            # Carried through to the batch JSON so the queue's science panel can route on
            # them. The grouper already has them (it groups by topic label); dropping them
            # here would have collapsed every panel to the default pair.
            "labels": labels,
            "priority": priority_of(labels),
            "milestone": milestone,
        })

    batches = []
    for key, members in groups.items():
        # Oldest issue first within a group: `gh issue list` returns newest first, which
        # used to put follow-on issues ahead of the foundations they build on.
        members.sort(key=lambda m: m["number"])
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
                    "issues": [{"number": m["number"], "title": m["title"],
                                "labels": m.get("labels", [])} for m in chunk],
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
