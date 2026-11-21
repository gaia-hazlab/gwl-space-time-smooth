"""Blocked chains in the open roadmap, from the queue grouper's own hold report.

Inputs (written 2026-11-11 by `python scripts/gaia_group_issues.py > grouper_stdout.txt 2> grouper_stderr.txt`
and `gh issue list --state open --limit 400 --json number,title,milestone,labels,body,updatedAt`):
    snapshot/open_issues.json, snapshot/grouper_stderr.txt
Output: snapshot/critical_path.json and a table on stdout.
"""
import collections, functools, json, pathlib, re

R = pathlib.Path(__file__).resolve().parents[1]
iss = {i["number"]: i for i in json.loads((R / "snapshot/open_issues.json").read_text())}
held, blk = {}, {}
for line in (R / "snapshot/grouper_stderr.txt").read_text().splitlines():
    m = re.match(r"holding back #(\d+) .*: (?:labelled (\S+)|blocked by open (.*))$", line.strip())
    if m:
        n = int(m.group(1))
        if m.group(2):
            held[n] = m.group(2)
        else:
            blk[n] = [int(x) for x in re.findall(r"#(\d+)", m.group(3))]
# The grouper does not report the blockers of an issue it already holds by label, so chains would stop at
# every hold. Read those from the bodies with the grouper's own parser.
import importlib.util, sys
_spec = importlib.util.spec_from_file_location("grouper", R.parents[2] / "scripts/gaia_group_issues.py")
_g = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_g)
for n in held:
    b = sorted(x for x in _g.body_blockers(iss[n]["body"]) if x in iss and x != n)
    if b:
        blk[n] = b
epics = {n for n, i in iss.items() if "epic" in [x["name"] for x in i["labels"]]}
runnable = sorted(n for n in iss if n not in held and n not in blk and n not in epics)
direct_231 = sorted(n for n, b in blk.items() if 231 in b)


@functools.lru_cache(None)
def ancestors(n):
    out = set()
    for b in blk.get(n, []):
        out |= {b} | ancestors(b)
    return frozenset(out)


@functools.lru_cache(None)
def depth(n):
    return 0 if n not in blk else 1 + max(depth(b) for b in blk[n])


down = collections.Counter()
for n in iss:
    for a in ancestors(n):
        down[a] += 1
TARGETS = {306: "cycling nowcast, pilot", 191: "ensemble forecast from posterior", 195: "forecast calibration",
           193: "joint hazard ensemble", 250: "sigma'(z,t), Vs(z,t) product", 261: "seasonal-high DTW product",
           142: "sub-1.5 m DTW in liquefiable units", 141: "liquefaction MVP", 129: "Landlab corridor run",
           200: "flood source-term contract", 202: "routed discharge vs gauges", 286: "pilot held-out validation",
           288: "regional history match"}
rows = []
for t, what in TARGETS.items():
    anc = ancestors(t)
    rows.append({"issue": t, "product": what, "own_hold": held.get(t), "chain_depth": depth(t),
                 "open_ancestors": len(anc), "held_ancestors": sorted(a for a in anc if a in held),
                 "runnable_ancestors": sorted(a for a in anc if a in runnable)})
out = {"n_open": len(iss), "held_by_label": dict(collections.Counter(held.values())), "n_blocked": len(blk),
       "runnable_now": runnable, "directly_blocked_by_231": direct_231, "targets": rows,
       "downstream_of_held": [(n, held[n], c) for n, c in down.most_common() if n in held][:12],
       "downstream_of_runnable": [(n, c) for n, c in down.most_common() if n in runnable][:12]}
(R / "snapshot/critical_path.json").write_text(json.dumps(out, indent=1))
print(json.dumps({k: v for k, v in out.items() if k != "targets"}, indent=0))
for r in rows:
    print(r)
