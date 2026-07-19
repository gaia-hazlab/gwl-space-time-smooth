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

Emits one JSON object per line (JSONL) to stdout:
  {"key": "...", "branch": "gaia/...", "issues": [{"number": N, "title": "..."}]}
"""
import json
import re
import subprocess

MAX_BATCH = 4

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}

TOPIC_LABEL_PRIORITY = [
    "dv-v", "water-budget", "geotech", "landlab", "stage-3", "stage-2",
    "stage-1", "hydrogeology", "soil-reanalysis", "atmospheric",
    "uncertainty", "validation", "peer-review", "documentation", "bug",
    "enhancement",
]


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
    groups = {}

    for issue in issues:
        labels = [l["name"] for l in issue["labels"]]
        if "epic" in labels:
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

    batches.sort(key=lambda b: (b["rank"], b["key"], b["branch"]))
    for b in batches:
        print(json.dumps(b))


if __name__ == "__main__":
    main()
