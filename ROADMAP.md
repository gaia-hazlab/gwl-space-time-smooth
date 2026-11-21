# Roadmap — GAIA Digital Twin of Soil

The durable plan. **This file, plus the linked GitHub issues, is the source of truth** — not any
agent's context. If a session loses its memory, start here.

Everything below is measured, not asserted. Where a number appears, it came from data, and the
command or record that produced it is named.

*Last revised 2026-11-21, after the PI approved design record #265 (section A) and the pilot domain
#269.*

---

## The operating loop (the project's spine)

The twin is one repeating loop. Every milestone serves a stage of it; this is the axis the book, the
milestones, and this roadmap should all be read against (not the subsystem inventory, which is a
consequence, not the spine). Derived from the codex editorial review and set out in
[`docs/reviews/opus-digital-twin-evolution-review-2026-07-21.md`](docs/reviews/opus-digital-twin-evolution-review-2026-07-21.md).

> **Represent → advance → observe → correct → propagate → evaluate → act.**
>
> The scientific claim: **the state lives at 90 m; every observation retains its own footprint** — and
> its mirror: **every hazard consumes at its own scale, too.** *Native support in (observations), native
> support out (hazards); 90 m is the common ledger, neither the finest input nor the finest product.*

| Loop stage | Job | Milestones |
|---|---|---|
| **Represent** | state at the scale each hazard needs; prior uncertainty | v0.2 · v0.3 (Vs30) · v0.4/v0.5 (domain) · MODFLOW core (structure, layers) |
| **Advance** | evolve water & stiffness, conserving mass | Water budget (land surface) · **MODFLOW 6 core** · v0.6 (memory) |
| **Observe** | predict each sensor at its native support | Applied math (operators) |
| **Correct** | data update the state, reduce uncertainty | Applied math (estimator) |
| **Propagate** | posterior distribution → forecast | v0.7 |
| **Evaluate** | score in observation space, held-out | v0.7 · Applied math |
| **Act** | state distribution → hazard probability, at the hazard's scale | Landslide (≤10 m) · Liquefaction (90 m screen) · Flood (reach network) · Wildfire |

*Cross-cutting:* Software (CI, tests, reproducibility, scale) underpins every stage.

Milestone descriptions carry a `[loop: …]` tag recording their stage.

---

## The model (approved 2026-11-21)

The groundwater is modelled with physics: MODFLOW 6 solves groundwater flow below the root zone. The
soil water above it stays in a 90 m land-surface model with a root-zone bucket. The PI chose this on
2026-10-18 and approved the design record, section A of
[#265](../../issues/265), on 2026-11-21. The plan text is
[`docs/reviews/2026-10-18-modflow-groundwater-core/plan.md`](docs/reviews/2026-10-18-modflow-groundwater-core/plan.md),
read with the amendments of 2026-11-09 (#296) and 2026-11-11 (#319); where they disagree, #265
governs.

```
forcing (PRISM daily hindcast; HRRR / ACE2 forecast, decision #333)
   │
   ▼
land-surface model, 90 m ── snow · canopy · root-zone bucket          (soil moisture)
   │ drainage ↓        ↑ seepage, groundwater ET
   ▼
MODFLOW 6 ── UZF (unsaturated zone) · GWF (heads, by hydrostratigraphic unit) · SFR (streams)
   │
   ├── observation operators at native support: wells, gauges, soil-moisture probes,
   │   SMAP / NISAR, SNOTEL, dv/v, GNSS
   ▼
ensemble Kalman filter through modflowapi (states)   +   PEST++ IES offline (parameters)
   │
   ▼
diagnosed products: depth to water, θ(z), pore pressure, effective stress, Vs → hazard consumers
```

What section A fixes, in short: one owner per store and one water ledger (#232); a structured grid
in EPSG:5070 with cells of k × 90 m, k set by the convergence study (#283); layers by
hydrostratigraphic unit, with geometry uncertainty as realizations (#292); one groundwater model per
watershed in a single simulation; daily stress periods from water year 2001; parameters estimated
offline and states by the cycling filter, with one role per well-year and per gauge-year (#235);
the posterior is the ensemble of members; only forward operators enter the filter, and depth to
water is diagnosed from heads, never assimilated; hydrology drives mechanics one way (#338); and
nothing scales out before the pilot passes held-out validation (#286).

The legacy store model in `src/models/water_budget.py` is no longer the groundwater model. It
survives as the land-surface and root-zone component and as a skill baseline the MODFLOW pilot
must beat.

### What approval did not settle

Section B of #265 stays open. Each row is decided by a named test or a PI decision, and an issue
that implements a row before its test is out of order. The ones on the critical path:

| ID | Question | Decided by | Status |
|---|---|---|---|
| B1 | Where MODFLOW's top sits: at the root base, with the bucket above it (option B), or at land surface, with UZF owning the whole unsaturated column (option A) | column test against a Richards reference, [#302](../../issues/302) | waits on #275 |
| B2 | Whether the root zone is refilled from below by capillary rise, and how residual PET is split | PI decision [#307](../../issues/307) | waits on #302 |
| B3 | Cycling by pause and resume, or by cold restart | [#303](../../issues/303), then PI decision [#308](../../issues/308) | waits on #275 |
| B4 | Which snow model and which root-zone bucket survive (the code has two of each) | PI decision [#309](../../issues/309) | **undecided**; draft on the issue; evidence in PR #315 |
| B5 | Hydrostate: Richards reference column, or a regional back end | PI decision [#310](../../issues/310) | waits on #302 |
| B6 | Constrained analysis update versus clip-and-book | [#304](../../issues/304) | waits on #289 |
| B7 | Filter variant, ensemble size, localization | [#322](../../issues/322) | open |

B1 matters most to the claim about partially saturated soil. Under option B the bucket keeps the
root zone, UZF carries water from the root base to the water table, and UZF is a kinematic-wave
model, not Richards. As #280 is written, option B never moves water from the aquifer back up into
the root zone, so a shallow water table cannot wet the soil above it. #302 measures that error
against Richards before anyone builds the exchange.

---

## The pilot (approved 2026-11-21)

**Enumclaw plateau around Newaukum Creek** ([#269](../../issues/269)). The domain encloses the whole
Newaukum Creek basin (gauge 12108500, 79 km², 21 NWIS wells, 11 with ≥12 months), bounded by the
Green River and the White River as stream boundaries with gauged inflows; both rivers are regulated
(Howard Hanson Dam, Mud Mountain Dam, the Buckley diversion). The Osceola lahar cap makes most plateau
wells semiconfined, which tests the layer-aware well operator (#9). Benchmark and starting framework:
the USGS southeast Puget Sound model, SIR 2024-5026, if #295 finds its footprint covers the pilot.

Still owed: the overlay of the 12108500 basin on the DNR bedrock contact (#21). The decision did not
wait for it; #281 reports the bedrock fraction when it builds the domain.

**The Puyallup River is also a domain of interest.** Seismic stations recorded proxies for river stage
and discharge during the December 2025 floods, an observation stream the other basins lack. Related
work: the December 2025 atmospheric-river hindcast on the Rainier box (#224) and the seismic discharge
proxy in [`docs/twin/05-state-evaluation.qmd`](docs/twin/05-state-evaluation.qmd). Two facts bound
what it can do. The White River, a pilot boundary, is a Puyallup tributary. The Puyallup gauge basin
at Electron (12092000, 238 km²) contains no NWIS wells, so there the seismic proxy would constrain
flux, not heads. Clarks Creek (12102078, 16 wells), the alternative pilot, is spring-fed from the
Puyallup valley wall.

The observation operator and error model for the seismic river proxy, tested on the December 2025
floods, are [#355](../../issues/355); it recommends whether the proxy enters the filter (through the
admission contract, #324) or serves as held-out validation. Still open, with no issue: whether the
Puyallup is an extension of the pilot or the second domain.

---

## Where we are (2026-11-21)

| component | status |
|---|---|
| Static layers (terrain, soils, Vs30) at 90 m | **done** — western Cascades, 2.96 M cells (v0.4) |
| Vs30 from the SVM (Grant, Wirth & Stone 2025) | **done**, staged as Zarr on Kopah |
| Store-model water budget, daily, with snow | **done**, now the land-surface component and the baseline (see below) |
| Petrophysical coupling (water → Vs, Hertz–Mindlin) | **done** — not a fitted correlation |
| Observed forcing (PRISM daily), state (NWIS wells), flux (USGS gauges) | **done**, Fall–Winter 2025-26; multi-year forcing is #70 |
| FuXi 15-day AI forecast adapter | **written, never run on a GPU**; forcing choice reopened in #333 |
| **MODFLOW 6** | **design approved, no code.** Nothing in the repo builds or runs MF6; #275 is first |
| Soil-state validation ladder (#296) | experiments recorded in review PRs #313–#318; PI review is #312 |
| Roadmap coverage review (#319) | 61 requirements checked against the issues; record in PR #351 |

### The store-model baseline

The v0.4 calibration, in daily mode against gauges and wells, with the snow clock on:

| | model | observed |
|---|---|---|
| baseflow index | 0.52 | 0.47 (Lyne–Hollick, 6 gauges) |
| runoff coefficient Q/P | 0.71 | 0.57–0.73 (per-basin closure) |
| seasonal amplitude | 1.02 m | 1.06 m (26,816 shallow-well obs) |
| water-table peak month | 5 | 4 |

It is a three-parameter fit (`S_y` ← amplitude, `k_aniso` ← Q/P, `recharge_ref` ← BFI). The six
mountain gauge basins that set BFI and Q/P contain zero NWIS wells; only Newaukum Creek (21) and
Clarks Creek (16) have any (plan, section 2). The amplitude match therefore compares a domain-wide
model with lowland wells outside most of the calibration basins. The fitted `Ka = 2` is below the
10–100 literature range for forest-soil anisotropy, and the peak is one month late. The 2026-10-08
audit found capillary rise creating water and valley cells with no sink (#232, #233). These are the
reasons the groundwater moved to MODFLOW.

---

## The plan, in order

Milestones: *Groundwater model: MODFLOW 6 hydrogeologic core* (13), *Water budget: land surface and
root zone* (10), *Applied math: DA estimator correctness* (9), *Groundwater model: scale-out* (14).
The epic is [#274](../../issues/274). Each issue's body carries its own `Blocked by:` line, and the
queue reads it; the order below follows those lines.

### 1. Foundation — no blockers, the queue can start now

| issue | what |
|---|---|
| [#275](../../issues/275) | **MF6 toolchain in pixi + a CI smoke model.** First on the critical path: #295, #278, #302, #303, #280, #281 and #289 all wait on it |
| [#276](../../issues/276) | Hydrostratigraphic framework on the 90 m grid |
| [#277](../../issues/277) | WA Ecology well logs: lithology and screen depths |
| [#10](../../issues/10) | Puget Sound coastal head boundary |
| [#279](../../issues/279) | Pumping and return flows, or a bounded omission |
| [#232](../../issues/232) | Whole-system water ledger (land-surface slice now) |
| [#235](../../issues/235) | Continuous recorders + frozen holdout manifest (pilot held-out years and wells go here) |
| [#70](../../issues/70) | Multi-year daily PRISM forcing and spin-up |
| [#21](../../issues/21) | DNR lithology crosswalk (the bedrock overlay for the pilot) |

### 2. The partition tests — decide how the bucket and MODFLOW meet

#302 (option A vs B against Richards) → decisions #307 and #310. #303 (UZF restart memory) →
decision #308. #309 (snow model and bucket owner) waits on the PI; its evidence is in PR #315.
The exchange #280 is blocked by #302 and #307.

### 3. The pilot model

#295 (USGS benchmark) · #278 (stream network) · #280 (land surface ↔ MF6 exchange) →
#281 (builder + steady state) → #282 (transient, daily, UZF) → #283 (grid convergence),
#292 (framework realizations), #130 (perched water on the till or lahar cap), #174 (upland lateral
flow) → #284 (PEST++ IES setup) → #285 (history match on Hyak, `needs-compute`) → #236 and
**#286, held-out validation against the store-model baseline.** #286 is the gate for everything in
section 5.

### 4. Assimilation on the pilot

#187 (state contract with MF6 heads) · #289 (ensemble runner over modflowapi) · #9 (well operator) ·
#237 (gauge operator on SFR) · #290 (soil-moisture operators) → #304 → #188 (cycling filter, exact
case and OSSE) → #306 (pilot, wells only) → #327 (multi-sensor). Specification and error budget:
#322, #323, #324. Retrospective product: #325.

### 5. Scale-out, after #286 passes

#287 (one model per watershed, joined by exchanges) · #288 (mountain basins with no wells,
`needs-compute`) · #293 (lakes and reservoirs) · #294 (ParFlow-CLM benchmark, held for a PI
decision). The Puyallup domain belongs here unless the PI makes it a pilot extension. Then v0.5
(Stehekin, [#99](../../issues/99)): east of the crest the hydrology is snowmelt-dominated, and FuXi's
0.25° grid cannot resolve the crest, so orographic downscaling becomes a blocker.

### Parallel tracks

- **Hazard consumers.** Landslide (milestone 6), liquefaction (7), flood (12; National Water Model
  adapter #339 and the skill test #340), wildfire (15; epic #347). Each stays a static susceptibility
  or antecedent-state product until a consumer is executed and validated on events (#265 A12).
  Shared output schema: #335.
- **Mechanics as state products.** Pore pressure and effective stress (#336), suction stress (#337),
  one-way coupling bound (#338), geotechnical parameters per unit (#342).
- **v0.6 Memory and disturbance** ([milestone](../../milestone/5)). Capillary hysteresis (#120),
  coseismic damage and healing (#121), surface disturbance (#122), dv/v attribution (#123). dv/v is
  the shared observable, so the problem is attribution across timescales.
- **v0.3 Vs30 densification** ([milestone](../../milestone/2)), *paused* by the PI until the water
  work lands. Vs30 is the coarsest static layer (SVM is 200 m native) and the binding constraint on
  liquefaction.
- **Forcing.** Forecast sources by lead range (#333), hourly precipitation (#332), near-surface
  meteorology (#331, #334).

---

## Decisions

**Taken**

| date | decision | where |
|---|---|---|
| 2026-10-08 | Keep the store model as the DA model | #265 archive; **superseded 2026-10-18** |
| 2026-10-18 | MODFLOW 6 replaces the store model below the root zone; watershed models; water table and soil moisture in the state; assimilate raw, proxy and satellite data | #265, plan.md |
| 2026-11-10 | Wildfire is a fourth hazard consumer; flood work integrates the National Water Prediction Service | #265 |
| 2026-11-21 | Design record section A approved | [#265](../../issues/265) |
| 2026-11-21 | Pilot: Enumclaw plateau / Newaukum Creek; Puyallup River a domain of interest | [#269](../../issues/269) |

**Waiting on the PI** (label `needs-human-decision`): #309 (snow model and bucket owner, evidence
ready); #307, #308, #310 (each after its test); #311 (products made with the sign-inverted Stage-3
water table); #333 (forecast forcing); #312 (review of the validation ladder); and the rest of the
list on GitHub. Superseded store-model issues (#171 and its children, #266, #89, #137, #177) are
held by the queue; closing them is the PI's call.

---

## Traps this project has already hit (do not re-learn these)

1. **`GraphCastOperational` emits `tp06` as literal zeros.** It does not predict rain at all. It is
   also the obvious pick (0.25°, "operational"). Selecting it silently forecasts a **drought** with no
   error raised. `assert_precipitation_is_real()` refuses it by name. **Use FuXi.**
2. **Silent fallbacks lie.** A staged-but-broken SVM netCDF once shipped a Wald-Allen slope proxy
   *labelled as SVM*. Staged-but-broken must now **fail loudly**; not-staged may fall back.
3. **Monthly ≠ daily.** The rate parameters are per-month; driving them with mm/day drains the column
   ~30× too fast, and the legacy `drain_frac=0.6/month` implies an unphysical ~33-day drainage
   timescale.
4. **Wells are not a random sample.** They sit in valleys. Compare the model *at the well locations*,
   never the domain mean.
5. **Q > P is not a mass violation** — it means you averaged precipitation over the wrong area.
6. **A perfect fit can be right for the wrong reason.** The monthly calibration reproduced the well
   seasonal cycle *exactly* by under-draining, compensating for missing physics.
7. **Do not attribute a lag to diffusion before checking the reservoir.** The 4-month rain→water-table
   lag was blamed on unsaturated travel time; it is **snowmelt**. Always ask *what is storing the
   water* before inventing a transport delay.
8. **Check that the flux is even RECORDED before calling it zero.** "Model BFI = 0.00" was largely an
   accounting artefact: the river sink removed head but the flux was never written to an output field.
9. **A calibration objective must contain every quantity whose parameter you claim to constrain.**
   Omitting the water-table amplitude left `specific_yield` free; it drifted to the grid edge and gave
   a 5.4 m seasonal swing with the fluxes still looking right.
10. **A domain mean can erase the physics.** Driving the budget with the domain-mean temperature formed
    **no snow at all** — the mean of a cold mountain and a warm lowland is ~7 °C. The elevation
    dependence *is* the mechanism.
11. **Fit the quantity the physics needs, not the convenient one.** Calibrating snow on SWE *RMSE*
    (dominated by accumulation) chose a melt factor so slow the pack lingered into June. Fitting
    **melt-out timing** recovered the April peak.
12. **A calibration gauge with no wells cannot pin a water table.** The six mountain gauge basins
    contain zero NWIS wells. Count the observations inside the control volume before claiming a
    state is constrained.

---

## Compute

- **FuXi needs a GPU.** 9.4 GB of weights, 60 six-hourly steps. GraphCast's `jax[cuda13]` will not
  even install on arm64. Run on **Hyak Tillicum (H200)** via SkyPilot: `deploy/tillicum-fuxi.yaml`.
  Slurm nodes **do not autostop** and `time` is a hard kill — size it for the whole init sweep.
- **Kopah** (`s3://gaia/soil-twin/...`) is the staging layer. SkyPilot `file_mounts` **do not work**
  with Kopah's custom endpoint — write with the S3 API.
- **MODFLOW 6.** The conda-forge build is serial, without PETSc/MPI; the multi-model run (#287)
  needs the parallel build compiled on Hyak. PEST++ includes GPL-3.0 code: call it as an external
  program, never vendor it. History matches (#285, #288) run on Hyak and carry `needs-compute`.
  CI never runs a real watershed model, only the synthetic fixture from #275. The ensemble's cost
  is measured in #320, not projected.

---

*The 2026-11-21 revision was drafted by Claude Code (Opus 5.5) at the PI's direction, from the
GitHub issues and the merged plan; the decisions recorded here are the PI's. Earlier versions of this
file, including the v0.4 domain-extension record (D1–D8) and the store-model physics debts, are in
git history.*
