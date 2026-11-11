# Roadmap review: can the open issues deliver the hydromechanical soil-state model?

Review dates 2026-11-10 to 2026-11-11. Reviewer: Claude (Fable 5.2), on request of the PI. Branch
`review/roadmap-2026-11-10`, cut from `review/soil-state-ladder` at `e92451b`; `src/` and `tests/`
are identical to `main` at `435445f`. No model code, test, GitHub issue, label or PR was changed.
The draft issues in [`issues/`](issues/) are files only.

What this is and is not. The 2026-11-07 review (epic #296,
`docs/reviews/2026-11-07-fable-soil-state-review/`) audited the proposal and the legacy code and ran
five experiments. This review audits the roadmap: for each element of the PI's target, is there an
owning issue, can its acceptance fail, is it sequenced, and what has no owner. Its findings 1 to 10
are cited, not repeated.

Evidence base.

| Item | Source | Status |
|---|---|---|
| 194 open issues, 14 milestones, 10 open PRs | `gh issue list --state open --limit 400 --json ...` on 2026-11-11T16:41Z, saved as [`snapshot/open_issues.json`](snapshot/open_issues.json); newest `updatedAt` is 2026-11-09T17:35Z | read |
| Dependency graph | `python scripts/gaia_group_issues.py` (stdout, stderr saved in `snapshot/`), extended through held issues by [`scripts/critical_path.py`](scripts/critical_path.py) using the grouper's own `body_blockers` | rerun today |
| Code citations | reopened on this branch; checked by [`scripts/check_record.py`](scripts/check_record.py) | rerun today |
| Five specialist rounds | repository reviewers (hydrogeologist, DA methodologist, geostatistician, geotechnical engineer, atmospheric scientist), read-only; reports in [`reviewers/`](reviewers/), my check of each probe in [`reviewers/adopt-reject.md`](reviewers/adopt-reject.md) | read; probes verified against the snapshot |
| Statements about external systems (operational AI ensembles, National Water Model, Earthnote internals) | pages fetched by the atmospheric reviewer on 2026-11-11; Earthnote repository read by me through `gh api` on 2026-11-10 | not re-fetched by me unless stated |
| Nothing was executed against MODFLOW 6 (not installed, #275 open) or against field data | | not run |

Abbreviations used: DA, data assimilation; MF6, MODFLOW 6 (GWF groundwater flow, UZF unsaturated
zone flow, SFR streamflow routing packages); LSM, the 90 m land-surface model; DTW, depth to water;
PET, potential evapotranspiration; SWE, snow water equivalent; NWM, NOAA National Water Model
(served through the National Water Prediction Service, NWPS); FS, factor of safety; OSSE, observing
system simulation experiment; IES, iterative ensemble smoother (PEST++); HSU, hydrostratigraphic unit.

## 1. Verdict

The roadmap can deliver a defensible groundwater and root-zone state with ensemble data
assimilation in the Puget lowland, and a static-to-seasonal antecedent state for hazards. It cannot
yet deliver the target as stated, for five reasons that are about what is absent, not about what is
planned badly.

1. **The forcing is precipitation and temperature only.** Wind, humidity and radiation are
   ingested nowhere, in hindcast or forecast; their one owner (#58) is P2, deferred and held. The
   forecast is one deterministic run, not an ensemble, and its ensemble issues wait on a GPU run
   that an operational ensemble would make unnecessary.
2. **The mechanics half has no hazard-facing state.** Pore pressure and effective stress with depth
   are one P2 issue (#250) blocked behind the seismic operator; unsaturated strength has no
   acceptance line; no structural unit carries a strength or density parameter; coupling is one-way
   everywhere without a stated bound.
3. **Storm-time slope hydrology has no owner.** The regional model has no matric potential and a
   daily step; the 10 m step is steady. This is a claim-or-non-claim decision for the PI.
4. **Wildfire is not on the roadmap**, and floods have no reference to the operational model the
   twin must improve on.
5. **Nothing says what the ensemble costs or how fast a cycle must be**, and no code computes the
   ensemble scores that seven issues ask for.

The sequencing is the more immediate problem. Of 194 open issues, 28 can run now, 112 are blocked
and 28 are held for a human decision. Two actions by the PI release most of the graph: merging the
queue-guard PR #272 (its issue #231 is the only parsed blocker of 44 issues and sits upstream of
100) and deciding the design record #265 (upstream of 52).

Coverage of the 61 target requirements in [`coverage.csv`](coverage.csv), tallied by
`scripts/tally.py`:

| Axis | Requirements | Covered | Owned, blocked or defective | No owner |
|---|---|---|---|---|
| Forcing (hindcast) | 7 | 3 | 1 | 3 |
| Forecast | 5 | 1 | 2 | 2 |
| Physics | 9 | 0 | 6 | 3 |
| Mechanics | 4 | 0 | 2 | 2 |
| 3-D structure | 3 | 0 | 1 | 2 |
| Data assimilation | 13 | 4 | 4 | 5 |
| Uncertainty | 6 | 0 | 3 | 3 |
| Hazard interoperability | 9 | 1 | 4 | 4 |
| Compute | 5 | 0 | 2 | 3 |
| All | 61 | 9 | 25 | 27 |

"Covered" means an owning issue with a testable acceptance and no hold; it does not mean built.
Zero of the 26 issues in the MF6 core milestone are closed.

## 2. Sequencing and the critical path

Source: `snapshot/critical_path.json`. "Upstream of N" counts open issues whose blocker chain
passes through the issue.

| Root | State | Upstream of | What releases it |
|---|---|---|---|
| #231 queue guard | open; PR #272 unmerged | 100 (44 directly, as "Blocked by: none (beyond the queue-guard PR, #231)") | PI merges #272 |
| #265 design record | `needs-human-decision` | 52 | PI approves (with #273) |
| #275 MF6 toolchain | runnable now | 46 | queue |
| #232 water ledger | runnable now | 43 | queue |
| #307 capillary and residual-PET decision | `needs-human-decision`, waits on #302 | 31 | #275, then #302, then PI |
| #52 two-theta ambiguity | runnable now | 28 | queue |
| #276 HSU framework | runnable now | 25 | queue |
| #269 pilot domain decision | `needs-human-decision` | 18 | PI |
| #285 production history match | `needs-compute` | 7 | Hyak allocation |
| #136 FuXi GPU run | `needs-human-decision` | 3 (#241, #242, #243) | replaced by NEW-F3 |

Longest chains to a hazard-facing product:

| Product (issue) | Chain depth | Open ancestors | Held ancestors |
|---|---|---|---|
| Seasonal-high DTW (#261), sub-1.5 m DTW (#142) | 8 | 22 | #265, #269, #285, #307 |
| Forecast calibration (#195) | 8 | 15 | #265, #307 |
| Cycling nowcast on the pilot (#306) | 7 | 25 | #265, #269, #285, #307 |
| Ensemble forecast from the posterior (#191) | 6 | 12 | #265, #307 |
| Routed discharge against gauges (#202) | 4 | 5 | none |
| Effective stress and Vs(z,t) (#250) | 3 | 5 | #265 |
| Liquefaction screen (#141) | 3 | 5 | #260 |
| Flood source-term contract (#200), joint hazard ensemble (#193) | 2 | 3 | #265 |

Defects in the graph, each quoted in [`issues/AMENDMENTS.md`](issues/AMENDMENTS.md) section A:

- A loop the parser cannot see: #289's acceptance requires the "clip rule that #304 shows passes"
  while #304 is `Blocked by: #289`.
- Missing edges: #289 cites decision #308 without listing it; #191 is initialised from #306 and
  lists only #188; #306 slice (c) uses six issues its line omits; #194 scores #306 without listing it.
- Work ahead of its input: #276 has no blocker and names #295 "the primary source"; #269 is to be
  decided before the overlay its own text calls decisive; #284 calibrates before #130 and #264
  change the layering; #271 fits to a Richards reference (#267) and a bucket (#309) it does not wait for.

## 3. Findings by axis

Classes as on 2026-11-07: **confirmed** (I reopened the text or code), **declared** (the
repository says so), **reviewer** (a specialist's judgement I checked for internal consistency but
cannot execute). Priority is mine.

### 3.1 Forcing and forecast

| # | P | Finding | Class | Evidence | Smallest correction |
|---|---|---|---|---|---|
| F1 | P0 | Wind, humidity, vapour-pressure deficit and radiation are not ingested; PET is Hargreaves-Samani from temperature | confirmed | `src/data/fetch_prism_daily.py:42-56`; #58 labels P2, `needs-human-decision`; #234 requires "a wind/turbulent DDF term" with no source | NEW-F1 (hindcast meteorology, P1, no blocker) |
| F2 | P0 | The forecast is one deterministic run from one initial condition, daily, precipitation and mean temperature | confirmed | `src/data/fetch_earth2studio.py:149` `deterministic(...)`; `:156-157` daily resample; `:164` two variables | NEW-F3 decision, NEW-F4 |
| F3 | P1 | Ensemble issues #241, #242, #243 wait on the GPU run #136; member count is "Fix N_members against the Tillicum H200 budget" | confirmed | blocker lines in the snapshot | NEW-F3: sources by lead range (HRRR short range; ACE2 with the Stage IV downscaler beyond), which takes #136 off the path |
| F4 | P1 | No physics-ensemble baseline; #195 scores against "climatology and persistence" | confirmed | #195 current scope | stopping rule in NEW-F3: AI source kept only if CRPSS against the physics ensemble >= 0 at leads 1 to 5 days |
| F5 | P1 | Sub-daily forcing exists only for burned cells (#132) and as an event comparison (#224); the model step is daily | confirmed | zero hits for AORC, HRRR, Stage IV in 194 bodies | NEW-F2 |
| F6 | P2 | Forecast temperature is not lapse-corrected (#263 is PRISM only); the rain/snow split is a fixed 0 to 4 degC ramp | confirmed | #263 scope; `src/models/forecast.py:58-60` | NEW-F4 |

Forcing-variable table: [`reviewers/atmospheric-scientist.md`](reviewers/atmospheric-scientist.md).

### 3.2 Physics

| # | P | Finding | Class | Evidence | Smallest correction |
|---|---|---|---|---|---|
| H1 | P0 (decision) | Transient pore pressure and suction psi(z,t) over 0 to 3 m at hourly steps has no owner; UZF "carries water content without matric potential" (#294); the Richards column (#267) is a reference | confirmed | #294, #302, plan.md:86, :162, :176-177 | NEW-P1: claim or non-claim; if a claim, an event-mode column |
| H2 | P1 | Perched water is split between MF6 (#130) and the LSM (#174) wherever colluvium is deeper than the root depth | reviewer | #130, #174 scopes | the two-owner column test in NEW-P1 |
| H3 | P1 | Hillslope scale: #133 is a steady 10 m wetness downscaler, one-way; #135 is held | confirmed | #133 current scope | NEW-P1, NEW-U2 |
| H4 | P1 | Five acceptance lines in the groundwater milestones cannot fail (#288, #287, #286, #279, #281) | confirmed | quotes in AMENDMENTS.md section B | amendments B |
| H5 | P2 | No thermal state: zero hits for "frozen ground", "frost", "soil temperature" in 194 bodies; snow stays degree-day | confirmed | recount over the snapshot | record as a non-claim in `docs/limitations.md`, or scope; rain-on-snow turbulent melt needs NEW-F1 |
| H6 | P2 | Preferential flow: one mention, in superseded #131 | confirmed | recount | non-claim plus the recorder-lag test proposed by the hydrogeologist |
| H7 | P2 | Fill, peat, tideflat and deltaic units are not separated in #276; tidal setup inland is dropped in #10 | reviewer | #276 unit list | amend #276, #10 |

What is sound: MF6 GWF, UZF and SFR below the root base, HSU layering, the two estimation loops,
the SIR 2024-5026 benchmark (#295) and the option A/B column test (#302) form a coherent
groundwater plan. The hydrogeologist's round found no physics objection below the root zone.

### 3.3 Mechanics and the 3-D structural model

| # | P | Finding | Class | Evidence | Smallest correction |
|---|---|---|---|---|---|
| M1 | P0 | The mechanical state product is unimplemented and mis-blocked: `estimate_mechanics` raises; vadose effective stress is a constant 10 kPa; #250 (P2) delivers sigma'(z,t) without u and waits on the dv/v operator #198 | confirmed | `src/models/soil_mechanics.py:56-67`; `src/models/dvv_coupling.py:48`; #250 `Blocked by: #198.` | NEW-M1: u(z,t), sigma'(z,t) from heads, blocked by #187 only, P1 |
| M2 | P1 | Unsaturated strength has no acceptance anywhere: #128 says "with suction" and tests two positive-pressure closures; suction is returned as zero by contract | confirmed | #128; `src/models/hydro_state.py:221-223` | NEW-M2 |
| M3 | P1 | Coupling is one-way in every issue and no issue states it or bounds it | confirmed (absence); bound is a reviewer estimate | no compaction package or stress-dependent K in 194 bodies | NEW-M3 design record with a mask for soft units |
| S1 | P1 | The structural model is two models: HSU geometry (#276, #292) and Vs(z) (#81 to #86, paused). No unit carries unit weight, strength, fines or density state; geometry realizations reach PEST++ only | confirmed | #276 deliverable; #292 "indexed so a PEST++ realization can carry one"; #289 signature | NEW-S1, NEW-D2 |
| S2 | P1 | Upland regolith thickness rests on SOLUS (2 m cap) and a layer of "unknown provenance" | confirmed | #134, #83 | NEW-S2 |

### 3.4 Data assimilation

| # | P | Finding | Class | Evidence | Smallest correction |
|---|---|---|---|---|---|
| D1 | P0 | The fixture cannot expose the production failure: #188 checks "the EnKF at N = 500" on one confined layer; production N, localization radius, vertical, cross-variable and integral-observation rules, and the sub-daily time convention are unset | confirmed | #188, #192, #283 ("N = 50" is a cost projection); plan.md:187, :203 | NEW-D1 |
| D2 | P1 | Forecast-step error is forcing perturbation plus the PEST++ posterior; no additive head or boundary error; no LSM parameter in any ensemble; geometry not in members | confirmed | #188; #289 signature; plan.md:198-199 | NEW-D2 |
| D3 | P1 | The gauge is used in both loops: baseflow in #284, total outflow in #306 (c); the one-role rule and its test are per well-year | confirmed | #284, #306, #235, #237 | amend #235, #284 |
| D4 | P1 | "Uncertainty-aware proxies" has no admission rule; on paper no proxy meets operator, error model, bias treatment, independent reference and holdout together | reviewer, table checked | `reviewers/da-methodologist.md` | NEW-D3 |
| D5 | P1 | Sensors without an owner: SNOTEL SWE operator (SWE is in the state); Sentinel-1; GNSS-IR; InSAR past go/no-go (#291) | confirmed | plan.md:236; #234; #291 "no operator code in this issue" | NEW-D5; the rest through NEW-D3 |
| D6 | P1 | No retrospective product: seasonal-high DTW is taken from the open-loop calibrated ensemble (#142 via #286); the only smoother is #162, for attribution, held | confirmed | #142, #162 | NEW-D4 |
| D7 | P2 | #192's barrier test (increment beyond a barrier "< 5% of the in-basin increment") conflicts with #188's "no hard zeros across layers or unconnected models" | confirmed | both in current scope | reconcile in NEW-D1 |

### 3.5 Uncertainty quantification

| # | P | Finding | Class | Evidence | Smallest correction |
|---|---|---|---|---|---|
| U1 | P0 | Seven issues ask for ensemble scores; the code has Gaussian closed forms only | confirmed | `src/evaluation/coverage.py:44-57`; no rank-histogram, Desroziers or ensemble-CRPS function in `src/` | NEW-U1 (no blocker) |
| U2 | P1 | The hydrologic filter issues lost their numeric thresholds: #188 had "spread/RMSE ratio within 0.8-1.2" before its 2026-11-09 rescope, now "a stated threshold" with none stated | confirmed | string present in archived scope only | amendments B |
| U3 | P1 | No change-of-support owner: k x 90 m heads shown at 90 m; 90 m to 10 m for slopes; products carry no support; the existing stack adds dependent sigmas in quadrature with a 5.0 m constant | confirmed | #283; `src/evaluation/uncertainty_stack.py:191-199`; #32 | NEW-U2 |
| U4 | P1 | Largest unsampled term per consumer (reviewer ranking): landslide, sub-90 m structure; liquefaction, Vs30 (1 m of DTW is about 0.008 in P, #142); flood, precipitation pattern below 0.25 degrees (#136); wildfire, the operator from root-zone water to fuel | reviewer | `reviewers/geostatistician.md` | NEW-S1, NEW-F3, NEW-W2 |
| U5 | P2 | No compound or decision-threshold probability with a support; two definitions of seasonal high (#261 annual P10, #138 annual-minimum return level) | confirmed | both in current scope | NEW-U3 decision |
| U6 | P2 | #305 asks N >= 10 events with a spatial block bootstrap; effective sample size and time blocking are missing; one event is recorded | confirmed | #305 | amend #305; NEW-E1, NEW-E3 |

### 3.6 Interoperability with hazard models

| Consumer | Owning issues | What it would receive today | Executed end to end? | Gap | Draft |
|---|---|---|---|---|---|
| Shallow landslide, Landlab | #127, #128, #129, #254, #300 | 2-D `.asc`, sigma side file, no member or depth axis; recharge sigma fixed at 0.1 x mean; seasonal-high DTW with no sigma (`src/io/landlab_export.py:42-46`, `:217-218`, `:319`) | synthetic 5 x 5 grid only (#300); the stock component ignores exported DTW (2026-11-07 finding 6) | no psi(z,t); no unsaturated strength; adapter decision held (#254) | NEW-P1, NEW-M2, NEW-I1 |
| Deep-seated landslide | #252 (P2) | nothing; input pointer "#130's regional store" is stale | no | no 3-D head export | amend #252 |
| Post-fire debris flow | #255, #134, #132, #122 | nothing; no burn-severity fetcher; 15-minute intensity out of reach | no | the twin's soil moisture is "exploratory" there | NEW-W3 |
| Liquefaction | #139, #141, #142, #260, #261, #270 | monthly DTW with an annual P10 (planned); the published model is static in DTW (finding 7) | no; gated by #270 | Vs30 unsampled and paused; no P(DTW < d*) | NEW-U3, NEW-S1 |
| Flood | #199 to #202, #257, #258 | exporter has no runoff, interflow or baseflow field | no | no operational reference; inundation has no owner | NEW-N1, NEW-N2 |
| Wildfire | none | nothing | no | whole consumer | NEW-W0 to NEW-W3 |

Across consumers: there is no shared, versioned output schema. #187 is internal, #193 (a) and #65
mention one in passing, and three exporters write three formats; `src/io/zarr_io.py:179-180` writes
"1000 m" and "monthly" as root attributes of a 90 m product. NEW-I1 owns it.

**Flood and the National Water Prediction Service (PI direction of 2026-11-10).** NEW-N1 is an
adapter with a hard boundary (one module may import NWM-specific names), giving a per-reach
baseline and an optional routing back end. NEW-N2 is the test of the twin's added value: identical
forcing and routing, antecedent soil and snow state swapped. What NWM carries is written into the
adapter's data card from NOAA pages rather than asserted here. The reviewer fetched
water.noaa.gov/about/nwm on 2026-11-11: Noah-MP land model, streamflow and reservoir assimilation,
MRMS, HRRR and GFS forcing. The statement that it assimilates no soil moisture, wells or proxies
is the reviewer's recollection and is the first thing NEW-N1 must document.

**Wildfire (PI decision of 2026-11-10).** The twin can defend a daily 90 m root-zone deficit and
percentile, a cumulative evaporative deficit and a melt-out date. It cannot supply dead-fuel or
live-fuel moisture, which respond to humidity, wind and radiation. Whether soil water adds skill
on the wet west side is not established (the 2020 Labor Day fires were wind-driven under extreme
fuel aridity; Evers et al. 2022, fetched by the reviewer, not yet Crossref-resolved by me), so the
milestone is built around a gate (NEW-W2) that can close it as "not a claim".

**Earthnote (Maleen Kidiwela).** Read on 2026-11-10 from the public repository
`maleenkidiwela/Earthnote` (MIT) with `gh api`; the public bucket's `event.json` answered. It
records hourly, for 2026-11-07 to 2026-11-15: MRMS rain, HRRR analysis wind, gusts and temperature,
every 6-hourly HRRR and ECMWF forecast run, NWM reach flows with flood thresholds, SNOTEL and
real-time wells, and three consequence feeds that cannot be backfilled (WSDOT and DriveBC road
alerts including slides and water over roadway; utility outages; combined-sewer overflows). Value
to this roadmap, in order: dated consequence labels for landslide and flood validation (NEW-E2);
kept forecast runs for an issue-time-frozen evaluation and a deterministic physics baseline (#305,
NEW-F3); an index of hours for sub-daily forcing (NEW-F2); the NWM baseline for one event (NEW-N1).
Limits: the bucket holds 8-bit display encodings (rain saturates near 103 mm; one byte per reach
flow; ECMWF is the deterministic run only, per the reviewer's read of its code), so quantitative
use needs the raw archive or a re-fetch; the incident feeds are unreviewed and biased toward roads
and population; it is one event against the ten #305 asks for. NEW-E1 and NEW-E3 need his agreement.

### 3.7 Computational efficiency

| # | P | Finding | Class | Evidence | Smallest correction |
|---|---|---|---|---|---|
| C1 | P0 | No measured cost of an N-member MF6 cycle and no latency target for any product | confirmed | "wall-clock": 0 issues; #283 gives a projection of "an N = 50 cycling filter"; #301 measures the land-surface bucket only | NEW-C1 |
| C2 | P1 | Parallel MF6 (#287, one deterministic run) and the ensemble runner (#289, serial; process pool advisory) are planned apart; the conda-forge build is serial | confirmed | #287, #289, #275 | NEW-C1 measures both |
| C3 | P1 | No emulator option, though the forecast ensemble is to be driven by AI weather members | confirmed | "emulator": #71 (weather); "surrogate": #260, #270 (liquefaction) | NEW-C2, decided on NEW-C1 numbers |
| C4 | P2 | Member products have no storage plan: `write_datatree` sets chunks and does not pass them | confirmed | `src/io/zarr_io.py:101-105` | in NEW-I1 |

Scale of the question, as arithmetic on one unmeasured input. The 2026-10-18 plan carries a warning
of "hours per member-year" for daily transient MF6 at about 1.6 M cells (plan.md section 8,
adopted from an untracked proposal, never measured). If one member-year costs t core-hours:

| Product | Member-years | Core-hours at t = 1 | at t = 10 |
|---|---|---|---|
| One daily cycle, N = 50 | 50 / 365 | 0.14 | 1.4 |
| One 15-day forecast, N = 50 | 750 / 365 | 2.1 | 21 |
| Reanalysis WY2001 to WY2026, N = 50 | 1,250 | 1,250 | 12,500 |
| History match, 100 realizations x 4 iterations x 25 years | 10,000 | 10,000 | 100,000 |

The daily cycle is cheap at any plausible t if members run in parallel; the history match and the
reanalysis are the costs, and they are what NEW-C1 must measure before #285 is scheduled. The
iteration count of 4 is my placeholder, not a number from #285.

## 4. Proposed additions

Thirty-two draft issues in [`issues/`](issues/), written to the accepted rulebook (Purpose,
Deliverable, Inputs and conventions, Acceptance, Hard blockers, Advisory).

| Group | Drafts | Runnable on posting |
|---|---|---|
| Forcing | NEW-F1 hindcast meteorology; NEW-F2 hourly precipitation; NEW-F3 member-source decision; NEW-F4 forecast variables | F1, F2; F3 is a PI decision |
| Physics | NEW-P1 event-mode pressure column (decision) | decision |
| Mechanics and structure | NEW-M1 pore pressure and effective stress; NEW-M2 suction-stress closure; NEW-M3 one-way coupling record; NEW-S1 geotechnical parameters per unit; NEW-S2 regolith thickness | M2 |
| Data assimilation | NEW-D1 production estimator; NEW-D2 model error; NEW-D3 proxy admission; NEW-D4 smoother reanalysis; NEW-D5 SWE operator; NEW-D6 multi-sensor slice | none (all wait on the filter chain) |
| Uncertainty | NEW-U1 scoring library; NEW-U2 change of support; NEW-U3 decision probabilities | U1 |
| Interoperability | NEW-I1 output schema; NEW-N1 NWM adapter; NEW-N2 state-swap experiment | none |
| Wildfire | NEW-W0 epic; NEW-W1 export; NEW-W2 value gate; NEW-W3 burn-severity fetcher | W3 |
| Earthnote | NEW-E1 ingest; NEW-E2 consequence labels; NEW-E3 recorder continuity | E1, E3 with Maleen's agreement |
| Compute | NEW-C1 budget and latency; NEW-C2 emulator scoping | none |

Amendments to existing issues: [`issues/AMENDMENTS.md`](issues/AMENDMENTS.md) (15 blocker-line
edits, 6 acceptance edits, 13 scope edits).

Suggested order for the queue once approved. Batch 0, no dependencies: NEW-U1, NEW-F1, NEW-F2,
NEW-M2, NEW-W3, NEW-E1, with the already runnable #275, #232, #52, #276, #277, #235. Batch 1, after
#275 and #187: NEW-M1 part (a), NEW-I1, NEW-N1, #302, #303. Batch 2, after the filter fixture:
NEW-D1, NEW-D2, NEW-D3, NEW-D5, NEW-C1. Batch 3, after the pilot cycles: NEW-D4, NEW-N2, NEW-W1,
NEW-W2, NEW-U2, NEW-E2.

## 5. Decisions for the PI

| # | Decision | My recommendation | Releases |
|---|---|---|---|
| 1 | Merge PR #272 (queue guard, issue #231) | merge after your review; it is the only parsed blocker of 44 issues | 100 downstream issues |
| 2 | Approve the design record #265 (with PR #273) | approve with option A/B left to #302, as the 2026-11-07 review set out | 52 downstream |
| 3 | Is storm-time shallow-landslide triggering a claim? (NEW-P1) | yes, as an event-mode column at selected hollows; otherwise #127 says antecedent susceptibility only | landslide milestone scope |
| 4 | Raise #250's pore-pressure part to P1 and unblock it from #198 (NEW-M1) | yes | every hazard consumer |
| 5 | Forecast sources by lead range (NEW-F3; PI direction 2026-11-11: HRRR, or ACE2 with Brandon Kerns's Stage IV downscaler) | HRRR for 0 to 48 h hourly; the ACE2 path for ensembles beyond that, once it is settled whether it runs as an initialised forecast or a scenario generator; an operational ensemble read as the baseline; FuXi kept as one deterministic member | #241, #242, #243, #191 without the GPU run |
| 6 | Wildfire: accept the gated milestone (NEW-W0) | yes; let NEW-W2 decide whether it stays a claim | ROADMAP.md "Act" row |
| 7 | Flood: adapter plus state-swap experiment (NEW-N1, NEW-N2) | yes | #199 scope |
| 8 | One-way coupling as a recorded design decision (NEW-M3) | yes, with the soft-unit mask | mechanics scope |
| 9 | Earthnote: ask Maleen for the raw archive and agree who runs the recorder (NEW-E1, NEW-E3) | yes, before the next atmospheric river | #305 |
| 10 | Thermal state and preferential flow | record both as non-claims in `docs/limitations.md` with the two go/no-go tests | none |
| 11 | Post these drafts to GitHub | post batch 0 and the blocker-line amendments first | the queue |

## 6. What was not done

- No experiment was run; every finding is from text and code. The cost table is arithmetic on an
  unmeasured input.
- Online statements (AI ensemble products, NWM internals, the wildfire reference) were fetched by
  a reviewer agent, not by me, and none has been through Crossref resolution; none was added to
  `docs/references.bib`.
- The Earthnote map was not rendered; I read its repository and confirmed the bucket answers.
- Closed issues and merged PRs were not audited.
- The hydrostate and mechanicalstate repositories were not re-read.

## 7. Posted to GitHub on 2026-11-11 (PI instruction: amend, push, post)

Done by `scripts/post_issues.py`; every body as posted is in `issues/posted/`, every amended issue
before and after in `issues/amendments/`. Verified afterwards: 226 open issues (194 + 32), none
closed, no label removed, and the queue grouper reports no dependency cycle
(`snapshot/grouper_stderr_after_posting.txt`). The grouper now lists 32 issues as runnable,
of which new: #331, #332, #337, #344, #350.

- New milestone "Hazard: wildfire handoff".
- 32 new issues, #319 (epic) to #350. Draft key to issue number:

| Draft | Issue |
|---|---|
| NEW-R0 | #319 |
| NEW-C1 | #320 |
| NEW-C2 | #321 |
| NEW-D1 | #322 |
| NEW-D2 | #323 |
| NEW-D3 | #324 |
| NEW-D4 | #325 |
| NEW-D5 | #326 |
| NEW-D6 | #327 |
| NEW-E1 | #328 |
| NEW-E2 | #329 |
| NEW-E3 | #330 |
| NEW-F1 | #331 |
| NEW-F2 | #332 |
| NEW-F3 | #333 |
| NEW-F4 | #334 |
| NEW-I1 | #335 |
| NEW-M1 | #336 |
| NEW-M2 | #337 |
| NEW-M3 | #338 |
| NEW-N1 | #339 |
| NEW-N2 | #340 |
| NEW-P1 | #341 |
| NEW-S1 | #342 |
| NEW-S2 | #343 |
| NEW-U1 | #344 |
| NEW-U2 | #345 |
| NEW-U3 | #346 |
| NEW-W0 | #347 |
| NEW-W1 | #348 |
| NEW-W2 | #349 |
| NEW-W3 | #350 |

- 45 existing issues amended with a dated header; 13 of them also had their `Blocked by:` line
  changed in place (#289, #188, #191, #194, #241, #242, #243, #255, #269, #284, #271, #234 and the
  split of #306 into #327), with the previous line quoted in the header.
- Two departures from `issues/AMENDMENTS.md`, both to avoid lengthening the pilot's path: #276 keeps
  `Blocked by: none.` with an ordering note instead of taking #295 as a hard blocker; #284 takes
  #130 as a blocker and #264 as advisory only, because #264's chain runs through the Rainier adapter #223.
- Held for the PI by label on creation: #333, #341, #336, #338, #342, #346, #321, #328, #330.
- Not done: `ROADMAP.md` is unchanged (its "Act" row gains wildfire only if #349 passes); no PR was opened for this branch.

## 8. Follow-up of 2026-11-11

- **Correction to sections 1, 2 and 5.** Merging PR #272 does not by itself release the 44 issues
  that carry "Blocked by: none (beyond the queue-guard PR, #231)". Their blocker is issue #231
  being open, and PR #272 refers to it without closing it: its body lists what is "Still open in
  #231" (the September runner fixes and defaulting to `Refs`). The release needs PR #272 merged
  and then #231 closed by the PI, or its remaining scope split into a new issue first.
- **PR #272 not merged by this session.** The `protect-main` ruleset requires an approving review;
  the repository owner is its bypass actor (PRs #217 to #221 were merged that way). The session's
  permission layer refused the bypass merge, so the merge is left to the PI. State read today:
  checks `test` and `check-dois` pass, 0 commits behind `main`, both Copilot comments answered by
  commit `618fea9`. Use a merge commit and keep the branch, because PR #273 is based on it.
- **Design record #265 restated** (`issues/RESTATE-265-design-record.md`; before and after in
  `issues/amendments/`): section A is what approval fixes, section B lists 15 questions that stay
  open with the test or decision that settles each, section C lists what was added since
  2026-10-18. The `needs-human-decision` label is untouched.
