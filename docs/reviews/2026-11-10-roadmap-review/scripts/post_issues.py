"""Post the review's draft issues and amendments to GitHub (run 2026-11-11 on the PI's instruction).

    python docs/reviews/2026-11-10-roadmap-review/scripts/post_issues.py --dry-run
    python docs/reviews/2026-11-10-roadmap-review/scripts/post_issues.py --create      # new issues, then NEW-xx -> #N
    python docs/reviews/2026-11-10-roadmap-review/scripts/post_issues.py --amend       # header + blocker-line edits

Never closes an issue, never removes a label. Amendments prepend one dated header and, where listed,
replace the single "Blocked by:" line of the current scope (above the first <details>); the previous
line is quoted in the header and the full previous body is saved under issues/amendments/before/.
"""
import json, pathlib, re, subprocess, sys

R = pathlib.Path(__file__).resolve().parents[1]
MAP = R / "issues/posted.json"
MILESTONES = {
    "Software": "Software: CI, tests, reproducibility, scale",
    "Water budget": "Water budget: land surface and root zone (feeds MODFLOW 6)",
    "v0.7": "v0.7 — Probabilistic nowcast and ensemble forecast",
    "Applied math": "Applied math: DA estimator correctness",
    "Groundwater model": "Groundwater model: MODFLOW 6 hydrogeologic core",
    "Hazard: LandLab": "Hazard: LandLab landslide handoff",
    "Hazard: flood": "Hazard: flood / inundation handoff",
    "Hazard: wildfire": "Hazard: wildfire handoff",
}
LABELS = ["epic", "hydrogeology", "validation", "uncertainty", "landlab", "stage-3", "geotech", "P0", "P1", "P2",
          "atmospheric", "water-budget", "needs-human-decision", "modflow", "needs-compute"]
RECORD = "docs/reviews/2026-11-10-roadmap-review/"


def gh(*a, inp=None):
    return subprocess.run(["gh", *a], input=inp, text=True, capture_output=True, check=True).stdout.strip()


def parse(path):
    lines = path.read_text().splitlines()
    key = re.match(r"# (NEW-[A-Z]\d)", lines[0]).group(1)
    title = re.sub(r"^# NEW-[A-Z]\d(?: \(amends #\d+\))?: ", "", lines[0])
    title = title[0].upper() + title[1:]
    head_end = next(i for i, l in enumerate(lines) if l.startswith("## "))
    head = " ".join(lines[1:head_end])
    ms = next((v for k, v in MILESTONES.items() if re.search(r"[Mm]ilestone:? \"?" + re.escape(k), head)), None)
    lab_txt = head.split("Labels:")[1] if "Labels:" in head else ""
    labels = [l for l in LABELS if re.search(r"(?<![\w-])" + re.escape(l) + r"(?![\w-])", lab_txt)]
    if "P1 (proposed" in lab_txt:
        labels = [l for l in labels if l != "P2"]
    notes = [s.strip() for s in re.split(r"(?<=\.)\s", head) if s.strip() and not s.startswith(("Milestone", "Labels", "Proposed new milestone"))]
    body = "\n".join(lines[head_end:]).strip()
    return key, title, ms, labels, notes, body


def sub(text, m):
    return re.sub(r"NEW-([A-Z]\d)", lambda x: f"#{m['NEW-' + x.group(1)]}" if "NEW-" + x.group(1) in m else x.group(0), text)


def create(dry):
    m = json.loads(MAP.read_text()) if MAP.exists() else {}
    drafts = sorted((R / "issues").glob("NEW-*.md"), key=lambda p: (p.name[4] != "R", p.name))  # epic first
    if not dry and MILESTONES["Hazard: wildfire"] not in gh("api", "repos/{owner}/{repo}/milestones?state=all&per_page=100", "--jq", ".[].title"):
        gh("api", "repos/{owner}/{repo}/milestones", "-f", "title=" + MILESTONES["Hazard: wildfire"], "-f",
           "description=Wildfire as a fourth hazard consumer (PI decision 2026-11-10): soil-water export, a value gate that can close the claim, burn-severity ingest.")
    parsed = [parse(p) for p in drafts]
    for key, title, ms, labels, notes, body in parsed:
        print(key, "|", title[:70], "|", ms, "|", labels)
        assert ms, key
        if dry or key in m:
            continue
        url = gh("issue", "create", "--title", title, "--milestone", ms, *sum((["--label", l] for l in labels), []), "--body", "posting…")
        m[key] = int(url.rsplit("/", 1)[1])
        MAP.write_text(json.dumps(m, indent=1))
    if dry:
        return
    for key, title, ms, labels, notes, body in parsed:
        epic = "" if key == "NEW-R0" else f", epic #{m['NEW-R0']}"
        head = f"**Created 2026-11-11 from the roadmap review (record `{RECORD}`{epic}).**"
        if notes:
            head += " " + " ".join(notes)
        final = sub(head + "\n\n" + body, m) + "\n"
        (R / "issues/posted").mkdir(exist_ok=True)
        (R / f"issues/posted/{m[key]}.md").write_text(f"# {title}\n\n{final}")
        gh("issue", "edit", str(m[key]), "--body-file", "-", inp=final)
    print(json.dumps(m))


# issue -> (header text, new "Blocked by:" line or None)
AMEND = {
    289: ("Decision #308 added to the blocker line (the body already says it \"fixes the operation mode\"). The acceptance bullet on the constrained update is read as: this issue exposes the analysis-constraint hook; #188 adopts the rule #304 selects. That removes a loop the queue parser could not see (#304 is blocked by this issue).", "Blocked by: #275, #280, #155, #308."),
    188: ("#304 added to the blocker line: the constrained update is decided before the filter fixture is accepted. Numeric thresholds restored: spread/RMSE within 0.8 to 1.2 over the fixture cycles (the value this issue carried before its 2026-11-09 rescope, and #241's), and 90 % coverage within +-0.05 of nominal (#194). Production ensemble size, localization and the time convention are specified in NEW-D1.", "Blocked by: #289, #187, #304."),
    191: ("Blocker line completed from this issue's own text (\"Posterior initial conditions come from #306\") and from the forecast-source decision NEW-F3. Products carry a support attribute (NEW-U2) and are written in the shared hazard schema (NEW-I1).", "Blocked by: #187, #306, NEW-F3."),
    306: ("Slice (c), multi-sensor, moved to NEW-D6 with its own blocker line; this issue keeps slice (b), wells only. Numeric thresholds restored as on #188: spread/RMSE within 0.8 to 1.2 and 90 % coverage within +-0.05 at withheld wells.", None),
    194: ("#306 added to the blocker line: this issue scores the cycling nowcast. Scores come from the ensemble scoring library NEW-U1.", "ADD #306"),
    241: ("The member source is the decision NEW-F3 (HRRR for 0 to 48 h; ACE2 with the Stage IV downscaler beyond; an operational ensemble as baseline), not the FuXi GPU run #136, which leaves this issue's path.", "Blocked by: NEW-F3, #187."),
    242: ("Blocked by the forecast-source decision NEW-F3 instead of #136. The coarse grid to downscale from follows that decision (about 4 km if the Stage IV downscaler is adopted); the conservation acceptance is unchanged.", "Blocked by: NEW-F3."),
    243: ("Blocked by the forecast-source decision NEW-F3 instead of #136. Forecast wind, humidity and freezing level are NEW-F4; hindcast wind, humidity and radiation are NEW-F1.", "Blocked by: NEW-F3."),
    250: ("Split. Pore pressure u(z,t) and effective stress sigma'(z,t) from MODFLOW heads move to NEW-M1, which does not wait on the dv/v operator. This issue keeps the Vs(z,t) and Vs30(t) product behind #198.", None),
    255: ("Blocked by the burn-perimeter and severity fetcher NEW-W3 instead of #134. Rainfall intensity: evaluate at published design-storm 15-minute intensities, cited in the PR, since the forcing cannot supply them (#132).", "Blocked by: NEW-W3."),
    276: ("Ordering note: this issue has no blocker and names #295 \"the primary source\" inside its footprint. It starts from the published regional surfaces; #295 refines the surfaces where it covers the domain, and the PR states which cells came from which source. Units: artificial fill, peat, tideflat and deltaic deposits are separated from \"Holocene alluvium / Vashon recessional outwash\"; geotechnical parameters per unit are NEW-S1.", None),
    269: ("#21 added to the blocker line: the body calls the bedrock-contact overlay the \"Decisive check before deciding\", and that overlay needs the DNR lithology crosswalk.", "Blocked by: #21."),
    284: ("#130 added to the blocker line: the perched-cap layer changes the layering, and calibrating before it would fit parameters to a structure that then changes. #264 (lahar-cap class) is advisory, not a blocker, because its chain runs through the Rainier adapter #223. Role rule: a gauge-year is one datum, like a well-year; the control-file test rejects any gauge-year outside the calibration role (see #235).", "Blocked by: #282, #235, #130."),
    271: ("#267 and #309 added to the blocker line: this issue fits store parameters \"to the Richards oracle per HRU\" (#267) for a root-zone bucket whose single owner is decided in #309.", "Blocked by: #268, #267, #309."),
    234: ("#263 added to the blocker line (melt-out above the calibration elevation needs lapse-corrected temperature). The \"wind/turbulent DDF term\" has no wind source in the repository; it reads NEW-F1 when that lands, and until then the term is off and the PR says so. A SNOTEL SWE observation operator is NEW-D5.", "Blocked by: #263."),
    288: ("Acceptance sharpened, because \"A plain statement of which quantities remain prior-dominated\" cannot fail: the gauge-only OSSE reports the K to S_y posterior correlation, and a cell head is released as a product only if its posterior/prior variance ratio is below a threshold fixed in the PR before the run.", None),
    287: ("Acceptance sharpened: the divide test keeps no-flow at a divide only if the joined run changes baseflow by less than the gauge sigma of the #189 table; at least three divides are tested, one of them in glacial drift. Runtime and memory of the joined run feed NEW-C1.", None),
    286: ("Acceptance sharpened: the metrics and the baselines to beat are listed in the PR before the run; \"validated for a consumer\" requires that consumer's target per hydrostratigraphic unit (#142). Rank histogram and 90 % coverage within +-0.05 (as restored on #188), scored with NEW-U1.", None),
    279: ("Acceptance sharpened: the omission memo carries a ceiling. If an omitted term exceeds a fraction of mean recharge stated in the PR before the arithmetic, it is implemented, not omitted.", None),
    281: ("Acceptance sharpened: two of the \"Reported, not gated\" items become gates, the dry-cell fraction and the sign of the mean head residual per hydrostratigraphic unit, with thresholds stated in the PR before the run.", None),
    58: ("Hindcast wind, humidity, vapour-pressure deficit and radiation move to NEW-F1 (P1, no blocker), because snow (#234), wildfire (NEW-W1) and any Penman-Monteith path need them regardless of the PET decision. This issue keeps the decision of which PET drives the model.", None),
    127: ("Scope decision added: whether storm-time shallow-landslide triggering is a claim of this system (NEW-P1). Until decided, products are antecedent-state susceptibility. Unsaturated strength is NEW-M2; upland regolith thickness NEW-S2.", None),
    128: ("The plain-words line says \"with suction\"; the acceptance tests two positive-pressure closures. The third closure, suction stress, and its acceptance are NEW-M2.", None),
    142: ("One definition of seasonal high across #261, #138 and this issue is decided in NEW-U3; this issue delivers P(depth to water < d*) for stated d* beside the quantile. The retrospective product comes from the smoother reanalysis NEW-D4, not the open-loop ensemble.", None),
    261: ("Seasonal-high definition (annual P10 here, annual-minimum return level in #138) is decided in NEW-U3. Export is a view of the shared schema NEW-I1. Source of the retrospective series: NEW-D4.", None),
    193: ("The shared joint-member hazard contract of task (a) is NEW-I1; wildfire joins as a consumer (NEW-W1). Joint probabilities across hazards from shared members: NEW-U3.", None),
    200: ("The export is a declared view of the shared schema NEW-I1. The operational reference for routed flow is the National Water Model adapter NEW-N1.", None),
    254: ("The Landlab export becomes a declared view of the shared schema NEW-I1 (members and depth axis kept; marginal sigma derived).", None),
    65: ("STAC items carry the schema version, member count and lead times of NEW-I1.", None),
    199: ("PI direction 2026-11-10: integrate the National Water Prediction Service, modular. NEW-N1 is the adapter (baseline scores per reach; optional routing back end; only that module imports model-specific names). NEW-N2 is the value test: identical forcing and routing, antecedent soil and snow state swapped. Hourly consequence labels for one event: NEW-E1, NEW-E2.", None),
    201: ("The routing component sits behind the `RoutingBackend` interface of NEW-N1, so the twin's own routing and National Water Model discharge are interchangeable.", None),
    202: ("The comparison \"against NWM retrospective discharge\" is supplied by NEW-N1, with nudged gauges flagged. The test of added value is NEW-N2.", None),
    257: ("Implements the twin-side `RoutingBackend` of NEW-N1.", None),
    235: ("Role rule extended from \"each well-year\" to each gauge-year: one role per datum across PEST++ calibration, filter assimilation and held-out. The November 2026 event labels (NEW-E2) are entered as held-out.", None),
    252: ("Stale input corrected: \"#130's regional store\" no longer exists (#130 is the perched-cap layer). The piezometric input is per-member MODFLOW layer heads and layer geometry in the shared schema (NEW-I1), from #282.", None),
    10: ("Addition: mean tidal setup inland of the shoreline in fill and deltaic units (see the unit split on #276), tested at near-shore wells as (head - mean sea level) against distance from shore.", None),
    283: ("The runtime and peak-memory numbers of this issue feed the measured compute budget NEW-C1, which replaces the projection of \"an N = 50 cycling filter\" with a measurement. Change of support from k x 90 m to 90 m is NEW-U2.", None),
    301: ("Feeds the compute budget NEW-C1.", None),
    187: ("Addition: the ensemble carries a framework-realization index so geometry uncertainty (#292) reaches the filter members (NEW-D2). The hazard-facing schema is NEW-I1; pore pressure and effective stress as derived variables are NEW-M1.", None),
    305: ("Additions: effective sample size per stratum and a bootstrap blocked in time as well as space (NEW-U1). The November 2026 atmospheric rivers enter the manifest from the recorded event NEW-E1; recorder continuity for later events is NEW-E3.", None),
    138: ("The seasonal-high definition of m2 (annual-minimum depth with a return level) and #261's annual P10 are reconciled in NEW-U3.", None),
    192: ("The barrier test (increment beyond a barrier \"< 5% of the in-basin increment\") and #188's \"no hard zeros across layers or unconnected models\" are reconciled in NEW-D1. Additive model error and land-surface parameters: NEW-D2.", None),
    134: ("The burn-perimeter and severity fetcher this issue notes as missing is NEW-W3.", None),
    290: ("Each stream here is admitted to the filter under the proxy admission contract NEW-D3.", None),
    291: ("The scoping arithmetic also reports skeletal strain per hydrostratigraphic unit, which is the input of the one-way coupling record NEW-M3.", None),
}


def amend(dry):
    m = json.loads(MAP.read_text())
    epic = m["NEW-R0"]
    bdir, adir = R / "issues/amendments/before", R / "issues/amendments/after"
    bdir.mkdir(parents=True, exist_ok=True); adir.mkdir(parents=True, exist_ok=True)
    for n, (text, line) in AMEND.items():
        body = gh("issue", "view", str(n), "--json", "body", "--jq", ".body")
        if "Amended 2026-11-11 by the roadmap review" in body:
            print(n, "already amended"); continue
        cur, sep, rest = body.partition("<details")
        prev = ""
        if line:
            found = re.findall(r"^\s*\**Blocked by\**:?\**[^\n]*$", cur, flags=re.M)
            assert len(found) == 1, (n, found)
            old = found[0].strip()
            new = line if not line.startswith("ADD ") else old.rstrip(". ").replace("none", "").rstrip(": ") + (", " if re.search(r"#\d", old) else ": ") + line[4:] + "."
            cur = cur.replace(found[0], new)
            prev = f" Previous blocker line: `{old}`"
        head = f"**Amended 2026-11-11 by the roadmap review (#{epic}; record `{RECORD}`).** {text}{prev}"
        final = sub(head + "\n\n" + cur + sep + rest, m).rstrip() + "\n"
        (bdir / f"{n}.md").write_text(body + "\n"); (adir / f"{n}.md").write_text(final)
        print(n, "| blockers ->", re.findall(r"^\s*\**Blocked by[^\n]*$", sub(cur, m), flags=re.M))
        if not dry:
            gh("issue", "edit", str(n), "--body-file", "-", inp=final)


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if "--create" in sys.argv or dry and "--amend" not in sys.argv:
        create(dry)
    if "--amend" in sys.argv:
        amend(dry)
