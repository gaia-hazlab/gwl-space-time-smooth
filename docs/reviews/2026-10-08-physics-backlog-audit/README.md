# Soil-state twin: physics and backlog audit before the GAIA launch

> **Archive note.** Internal record for the team and for future AI agents (GAIA). Nothing here changed GitHub issues or code. `lenses/` holds the five physics assessments with adversarial verdicts, `issues/` the eight issue-family audits with proposed new issues, `issue_verdicts.json` one verdict per open issue (2026-10-07 snapshot), `probes/` the scripts behind the numbers, and `queue_sim.jsonl` / `queue_held.txt` the GAIA queue simulation on origin/main 435445f. Re-verify against current main before acting.

**Date:** 2026-10-08. **Written for:** Marine Denolle and the GAIA hazard-lab team.
**Code audited:** `gaia-hazlab/gwl-space-time-smooth` origin/main `435445f`. The local checkout on Marine's laptop is behind origin/main and was not used for code claims.
**Prototype audited:** `Denolle-Lab/mt-rainier-digital-model` (rainier3d) main `d61305c`, including the critical-zone module added on 2026-10-03 (`6ad0fe7`) and the paper `docs/paper/rainier3d_paper.md`.
**Reviews read:** peer review (2026-07-07); codex editorial; sensor-uncertainty; Sonnet and Opus strategy reviews (2026-07-21); the 2026-09-10 system audit, science, roadmap and automation reviews and the operational plan (unmerged branch `docs/soil-twin-audit-and-plan-revision-2026-09-10`); the 2026-09-28 rainier3d leverage review (unmerged branch `docs/rainier3d-leverage-2026-09-28`).
**Method:** two mapping agents, five physics lenses with an adversarial verifier each, and eight issue-family auditors with an adversarial verifier each, covering all 132 open issues. No verifier refuted a lens claim outright. Many claims were marked "partially", with corrections that are folded in here. The integrator and critic agents failed on usage limits, so this synthesis was written by the main session from the archived results. Per-lens and per-family details are in `lenses/` and `issues/`. Every issue verdict is in `issue_verdicts.json`.

---

## 1. Bottom line

1. **The physics direction is right, but the water model it rests on does not conserve water.** The reviews agree on the target: a storage-based state at 90 m, observations at native support, a cycling ensemble, and hazards at their own scale. The model underneath is one root-zone bucket plus one linear-reservoir head per 90 m cell, with no store between them and no exchange between cells. Three independent probes show it creates and destroys water (section 3).
2. **Fix the hydrologic core as one designed topology, not as a dozen patches.** Issues #131, #172, #173, #174, #175, #130, #133, #137 and #176 all edit the same ~100-line loop, and each adds a piece of the same missing vadose, perched and lateral storage. GAIA would hand them to different agents in different batches.
3. **Start from rainier3d for the hydromechanics, not for the water budget.** rainier3d is a static digital model. Its new critical-zone column has the right hydromechanical structure: effective stress from overburden, Lu–Godt–Wu suction stress, Hertz–Mindlin/soft-sand, Gassmann–Brie, and disba kernels on a layered profile. That makes it the natural reference operator for P0 #198. Its 1D Richards solver is a good oracle but cannot be the regional cycling model. The Rainier box is a good hydromechanics pilot and a poor water-budget closure pilot.
4. **The backlog is not ready for unattended agents.** Only 5 of 132 issues survive as written, and only 19 are executable by an agent today. The GAIA grouper on main ignores human holds, blocks the whole DA chain on an epic that only a human can close, and dispatches the Rainier, hazard and dv/v issues before their own prerequisites. The September runner fixes that the team accepted (A2 "revise is not approve", AUTO-06 hold filter) were never merged to main.

---

## 2. What the twin physically is today

- **Root zone.** One store θ·z_r, with z_r from SOLUS clipped to 0.1–2 m. Saxton–Rawls retention (`src/models/water_budget.py:150-153`).
- **Groundwater.** One head anomaly h about a static statistical datum d0, wt = d0 − h, drained toward HAND by a coefficient anchored on a domain-constant R_ref = 3 mm/d (`:157, :188-197, :266-279`).
- **Snow.** A degree-day pre-processor outside the ledger. SWE starts at zero and is not carried between runs (`src/models/forecast.py:105-131`). A forecast launched over an existing spring snowpack melts nothing.
- **Lateral flow.** None. Runoff, interflow and baseflow leave the cell in the step they form. `topmodel_watertable` is a static prior. `accumulate_runoff` rescales runoff in place and gains mass, by about 55% in one probe and up to 2× (`:287-311`).
- **Three parallel θ models.** The shipped θ product comes from `total_water_bucket`, which drains and clips water without reporting it (`src/models/soil_moisture.py:162-190`). The forecast uses `coupled_water_budget`. The LandLab export uses a third path with no snow (`src/io/landlab_export.py:304`).
- **GWL product.** The Stage 1–3 statistical product and the process-model head are separate estimates. Pooled block-CV RMSE is 18.5 m, bias +3.5 m, R² 0.09, with effectively four folds because folds 0 and 4 are identical.
- **Hydromechanics.** P_e = 10 kPa + S_e·P_c with no depth axis; G ∝ P_e^{1/3}; saturated-zone dv/v = 5×10⁻⁴·Δh (`src/models/dvv_coupling.py:45-106`). `soil_mechanics.estimate_mechanics` raises `NotImplementedError`.
- **DA.** A snapshot BLUE (`src/models/observability.py:1217-1263`), never cycled. The demonstration notebook assimilates climatology-infilled wells and dv/v drawn from its own prior (`notebooks/make_twin_gif.py:215-246`).

**New P0 found during this audit (needs a one-line test to confirm).** The Stage-3 assembly sets `dtw_final = baseline_dtw + cr_cube + residual_cube` (`src/models/interpolate_residuals.py:203-207`). Both added terms are water-table *elevation* anomalies, positive upward: the Stage-2 output is `wte_anomaly_m` (`climate_response.py:399`), and the residual is observed minus that (`interpolate_residuals.py:174`). So a rising water table is written as a deeper one, and `wte_final` inherits the error. The pipeline feeds the seasonal-high field used by the LandLab export. The defect was noted in an August science-panel comment on #186 but has no issue.

---

## 3. Water-budget closure

### 3.1 Verified defects (probes in `probes/`)

| Defect | Evidence | Size in probes |
|---|---|---|
| Capillary rise is credited to the root zone and never debited from head | `water_budget.py:217-219` vs `:266` | Residual equals −Σ capillary rise exactly: −43 to −102 mm per 300 days on shallow-table cells. Every other branch closes to ≤5×10⁻⁵ mm |
| No groundwater sink where HAND ≤ d0 (valley fill, terraces) | `:193-196` | Zero forcing for 10 yr: table rises to 4.9 m **above** ground, creating 1,630 mm. Wet year: 290–297 mm/yr created (~23% of P), BFI = 0 |
| Constant R_ref = 3 mm/d makes baseflow a prescribed drain | `:88`, `:188-197` | Ridge cell: 339 mm recharge, 1,072 mm baseflow, Q > P − AET. 20-yr drift: hillslope 15 → 33.5 m, hollow 3 → 12.8 m, e-folding ~12 yr |
| Non-conservative clip of S | `:251` | Silent sink at wet states |
| Root-zone pores counted twice in the saturation-excess deficit | `:230` vs `:235-236` | VSA almost never fires: deficit 1,500 mm at wt = 5 m |
| Daily and monthly modes disagree | #89 | 4.7× in drainage |
| Root-zone θ cannot reach saturation | drainage before recording (`:247-253`) | Peak θ 0.39 against θ_sat 0.45 in a 200 mm atmospheric-river probe |

The D7 calibration (S_y = 0.30, K_a = 2, R_ref = 3) was fitted with all of these active. It must be redone after the fixes.

### 3.2 Calibration is reported as validation

`notebooks/calibrate_fluxes.py` fits K_a, R_ref and S_y on a 5×4×6 grid against BFI, Q/P, amplitude and peak month. It uses domain means over every sixth cell and one 10-month window (Sep 2025–Jun 2026) with no spin-up and no ΔS term. Every number in the book's "closed against observations" table (`docs/twin/03a-physics-hydrology.qmd:216-222`) is therefore a calibration target. Further problems:

- S_y = 0.30 exceeds the Saxton–Rawls drainable porosity of loam (0.18) and clay loam (0.12). It is implausible for till uplands, where S_y ≈ 0.02–0.1.
- Heads alone identify only R/S_y and R_ref/S_y. Jacobian condition numbers are 1.8–4.4×10⁴ for heads alone and 14–17 once discharge is added. θ carries no information about groundwater parameters wherever the table is deeper than z_r + 1 m.

### 3.3 Budget-term inventory for the Cascades–Puget domain

Represented, though crudely:
- rain/snow partition;
- AET from the root zone only, with Hargreaves–Samani PET, no stress function and no snow-cover suppression;
- saturation excess (double-counted);
- interflow as an instantaneous loss;
- recharge.

Missing:
- SWE as a carried store;
- glacier ice ΔS (Nisqually, Carbon, White and Puyallup carry late-summer ice melt);
- canopy interception (order 20–25% of gross rain in old-growth Douglas-fir; *verify* Link et al. 2004);
- vadose transit;
- lateral groundwater (Dupuit/Boussinesq), convergence, and inter-basin and regional flow to Puget Sound;
- seepage-face exfiltration, the root cause of the valley bug;
- two-way stream–aquifer exchange (`to_river` is clipped at 0, `:271`);
- pumping;
- confined vs unconfined units and till leakance;
- channel routing.

Hydrothermal inflow at Rainier is real but likely negligible in volume. It is useful as a tracer.

### 3.4 What "closure" must mean

**Level 1: per-column, per-step ledger.** State is water-equivalent storage:

x = [ice, SWE, canopy, ponded, root zone, vadose transit, perched, unconfined aquifer, confined aquifer, channel]

Every internal transfer is debited and credited. ΔΣx equals boundary fluxes plus logged DA increments. Gates:
- residual ≤ 10⁻⁶ mm per step, accumulated in float64;
- a zero-forcing run creates nothing in any branch (legacy, HAND, valley, terrace, wt < 0, θ at bounds);
- timestep refinement converges, or the monthly path is retired;
- bounds are enforced by flux limiting, never by deleting water.

**Level 2: domain ledger.** Once lateral exchange exists, interior exchanges sum to zero. Only outlet, coastal, pumping and prescribed inflow terms remain.

**Level 3: closure against independent data.** This is a skill metric, not an identity:
- P − ET − Q − ΔS over water years on gauged basins **held out of calibration**;
- Q routed, and BFI computed by applying the same Lyne–Hollick filter to the simulated hydrograph;
- ΔS_snow from SNOTEL plus a SWE product, ΔS_soil from probes, ΔS_gw = S_y·Δh at screened unconfined wells only.

PRISM uncertainty in orographic terrain is roughly 10–30%, so ±10–15% annual Q at held-out gauges is a demanding but meaningful target. GRACE cannot resolve a 24,000 km² domain. GNSS loading (#226) is the right regional total-water-storage constraint, and only after a credible snow model.

**What cannot close until the topology changes:**
- gauge budgets, until routing and lateral groundwater exist;
- lowland basins with losing streams, pumping or Puget Sound outflow;
- glacier basins, until ice is a store;
- any basin while valley creation and ridge mining persist.

---

## 4. Target hydrologic model

**Per 90 m column:**
1. glacier ice/firn (mask);
2. SWE as a carried state, with rain-on-snow and liquid retention;
3. canopy (Rutter or Gash, LAI capacity);
4. infiltration partition: Green–Ampt at sub-daily intensity, plus saturation excess from the true deficit;
5. root zone in 1–2 layers, with an ET stress function;
6. deep vadose transit from root base to water table, using kinematic celerity rather than particle travel time, with its storage counted in the fillable deficit;
7. perched/interflow store on the soil–bedrock or till contact, routed cell to cell.

**On a hydrogeologic grid** (90 m for the shallow unconfined layer, 270 m–1 km for deep units):
- unconfined aquifer with 2D Boussinesq flow;
- till leakance to a confined layer;
- seepage-face exfiltration;
- river-conductance exchange with NHDPlus reaches, in both directions;
- coastal head;
- pumping;
- prescribed inflows.

Channel routing (Muskingum–Cunge or t-route) carries flow to the gauges. Head, DTW and pore pressure are diagnosed from storage; `hydro_state.py:158-204` already provides storage ↔ head.

**The vertical state the hydromechanics needs** is at least four stores with explicit depth bounds:
- 0–0.3 m;
- 0.3 m to the soil base (≤ 2 m);
- soil base to the water table;
- saturated head.

Each store maps onto a fine operator grid through a within-store equilibrium ψ profile.

**Build vs adopt.** Keep the light Python store model as the ensemble and DA emulator; its cost is about 6 core-hours per simulated year for 100 members on 2.96 M cells. Fix its ledger, adopt the topology above, and benchmark it on one or two pilot basins:
- **DHSVM.** Built for PNW forested mountain basins at 30–150 m, with canopy, energy-balance snow and cell-to-cell saturated subsurface flow. It has no deep regional aquifer. *Verify* the maintenance state of its glacier variant.
- **ParFlow, HydroGEN or CONUS2.** Use these for the steady water-table pattern. *Verify* the product resolution and licence.
- **USGS GSFLOW/MODFLOW Puget sub-area models.** Use these for recharge, stream leakage and pumping. *Verify* which models exist.

Choosing among these is a human decision. Agents should not invent lateral groundwater before it is made.

---

## 5. Hydromechanics

**Same family, wrong scaffolding.** The twin's vadose map is the right family: Lu–Godt–Wu suction stress with χ = S_e and a Hertz–Mindlin exponent of 1/3. But it has no depth axis.
- G_REF and P_REF cancel exactly in dv/v, so #176's "calibrate SIGMA0/G_REF" should drop G_REF.
- The magnitude is set by the constant σ0 = 10 kPa. That is the overburden at about 0.6 m: σ0 = 2 kPa gives −30% for the same θ swing, and 200 kPa gives −10%.
- In a drained frame, the saturated sensitivity is dlnVs = (1/6)·dσ′/σ′. That is −1.2 %/m at 10 m depth with the water table at 5 m, and −0.44 %/m at 30 m with the water table at 10 m. Both are 9–24× the scalar K_SAT, which is defensible only as a band-integrated low-frequency coefficient.
- #45's "S_THETA = −2" title is stale: the code uses −1.0, consistent with its own forward chain.
- The Vs30 blend uses thickness rather than travel-time weighting, which understates storm-driven Vs30 change about 2.2×.
- Snow load (1 m SWE ≈ 9.8 kPa) stiffens the near surface by several percent. That is opposite in sign to wetting and is absent from both models.
- Drained-only behaviour is wrong for clayey and lahar-cap units over seasonal periods.

**Depth sensitivity of dv/v (with Marine's correction).** dv/v sensitivity depends on frequency band and is never zero at shallow depth. Illien et al. (2021) show 4–8 Hz dv/v responds to vadose-zone moisture. The observable integrates the whole vadose column, meters to tens of meters thick. The defects are therefore in the operator and the state, not in seismic monitoring:
- the twin has no depth-resolved vadose state to integrate over;
- `KERNEL_FRACTION_TOP1M = 0.08` is hard-coded rather than computed from kernels (`dvv.py:66-69`);
- the twin's default bands stop at 2–4 Hz (`dvv.py:41`), and `peak_depth_km` assumes Vs = 1500 m/s;
- codameter band kernels are not normalised and have negative lobes, e.g. the 0.71 Hz band sums to −0.16 (hydromechanics family auditor);
- the deep aggregate averages the posterior down to 6 km and then divides by K_SAT, which is not a head metric (`dvv.py:327-370`).

Kernels must be computed per observed band on a realistic layered Vs0(z). Bands from roughly 4 to 40 Hz, from permanent stations, nodes and DAS, give the vadose and shallow-saturated sensitivity. rainier3d's synthetic gives half-sensitivity at 8.5–12 m at 10 Hz and 4–5 m at 40 Hz. The paper (~l.513) and `critical_zone.md:210` disagree on the storm amplitude, so do not adopt either number as an acceptance threshold until that is resolved.

**Decision on #198.** Port rainier3d's column *equations and discretisation* as the single reference forward operator. That means σ′(z) from column weight plus suction stress, the soft-sand/Hertz–Mindlin frame, Gassmann–Brie fluid substitution, disba kernels frozen at Vs0(z), and harmonic Vs30. Port it as a dependency-light twin module evaluated at station and footprint columns, not by importing the rainier3d package. Changes needed first:
1. **Drive it with the twin state.** Use θ(z) or ψ(z) and head from the multi-store model, not hydrostatic equilibrium with a static water table. Fan 2017 tables more than 100 m deep under ridges make the near surface artificially dry.
2. **Treat parameters as ensembles.** These are the stress exponent n (prior 0.33–0.5), C·f, φ_c and Brie e. Fix the soft-sand branch, which evaluates at min(φ, φ_c) contrary to its docstring.
3. **Compute kernels for every observed band.**
4. **Derive `linear_saturated` coefficients per band** from the operator, not from a global K_SAT.
5. **Add flags** for drained or undrained response per unit and for surface loads such as snow.
6. **Standardise units.** The twin's van Genuchten α is in 1/kPa and rainier3d's is in 1/m.

Hold the issues that tune SIGMA0, K_SAT and S_THETA until the operator lands: #45, #50, #30, #85, #165 and the constants in #176.

**What factor of safety needs.** Use infinite slope with suction stress: FS = tanφ′/tanβ + 2(c′+c_r)/(γH sin2β) − σ_s(tanβ+cotβ)tanφ′/(γH).
- **Shallow slides** need suction stress at 0.5–3 m and positive perched head on the contact, to about ±0.3 m. Suction loss is first order there: at H = 1 m, wetting drops FS from about 1.7 to 1.08.
- **Deep-seated slides** need head at the slip depth. The median depth of the 453 lidar-protocol deposits is 14.6 m, where each metre of water-table rise costs ΔFS ≈ −0.033. The 351 January 2009 slides have no recorded depths, so #224 currently compares two different populations.
- **Today the twin delivers neither.** The root zone cannot saturate, there is no perched store, interflow is a sink, and the absolute head is unconstrained.
- **#128 must fix its pore-pressure convention.** Vertical saturated thickness and piezometric head differ by 1/cos²β, which is 33% at 30°.
- **LandLab's `LandslideProbability` has its own conventions.** Its soil thickness is slope-normal and its density ratio is hard-coded. It builds wetness from recharge × contributing area, so it needs total drainage. It does not take `water_table__depth`, contrary to `docs/twin/07-hazard-integration.qmd`. The twin exports drainage net of interflow, which is only 37–51% of drainage on failure-prone slopes.

---

## 6. Can we start from the Mt. Rainier prototype?

**Yes, as a library, an oracle and a hydromechanics pilot. Not as the cycling water model.**

| Use | What transfers | Condition |
|---|---|---|
| Static critical-zone medium | `cz.medium` layer bases, porosity, log k, vG, W, σ′; national inputs including POLARIS vG to 2 m | Recompute at 90 m on twin inputs; do not resample the 250 m product. It retires S_y = 0.30 by giving drainable porosity per layer |
| #198 operator | `rockphysics`, `synthetics` (disba) | Section 5 conditions |
| Richards oracle | `richards.py` (Celia modified Picard, mass ledger) | Fix the specific-storage defect (below). Add ET, snowmelt input, a deep free-drainage bottom with a Dupuit lateral sink, and multi-year spin-up. Benchmark against analytic solutions and Hydrus or openRE |
| Ecology and WGS well ingest | `hydromet/wells.py` | 5,591 levels in the Rainier box against the twin's 863 clean NWIS sites. All are single static levels |
| Release and provenance tooling | SHA-256 products registry, bibliography registry | Process value; supports bibliography lane B1 |

**Rainier-specific, does not scale:** the edifice footprint, magma ellipsoid, crack-closure unit table and PNSN-calibrated multipliers, the EM alteration survey, IceBoost tuning, and the single box-wide regional bias. iMUSH already shows that bias fails in the southern part of the box.

**Verified problems before any adapter work:**
- **Richards specific-storage defect.** S_s is added to the capacity but not to θ(h) (`richards.py:21,36-46`). Saturated cells never converge under a free-drainage bottom, drifting 3.5 mm per iteration. This plausibly explains the 8 failed S34 sites. The one-year probe's +1,060 mm is mostly spin-up from a hydrostatic start, not unbounded growth. Even so, a 1D column with no lateral sink only accumulates water, the same disease as the twin's valley cells.
- **Grid coverage.** About 16.5% of the Rainier box (~864 km², south of ~46.6° N) lies outside the twin grid. The twin's current static layers sit on `LEGACY_DOMAIN`, which covers ~0.8% of the box (`src/config/domain.py:124-129`). The v0.4 static rebuild is a prerequisite for #223.
- **The leverage review behind #223–#228 is stale.** It was written at rainier3d `d827cc3` (2026-09-26), before the critical-zone module. Its statements that rainier3d has no saturation term and no soil-moisture state are now false, and so is "the box sits inside the twin domain".
  - #223's layer list omits `/cz`, the S31 wells and S35. No release contains `/cz`; `products-v1.0.0` predates it.
  - #225 points to a conservation contract and test that do not exist on main, on a branch that is not on origin.
  - #228 is an epic, so GAIA never runs its sub-slices.

**Cost** (measured serial rates; compiled and GPU figures are estimates). Per simulated year with 100 members:

| Model | 2.96 M cells | ~12 M cells |
|---|---|---|
| Serial Python Richards | ~9×10⁵ core-h | ~3.7×10⁶ core-h |
| Batched NumPy Richards | ~7×10⁴ core-h | ~3×10⁵ core-h |
| Compiled Richards | ~1.5×10⁴ core-h | ~6×10⁴ core-h |
| GPU/JAX Richards | ~20 GPU-h | ~80 GPU-h |
| Store model | ~6 core-h | ~24 core-h |

Cost does not rule out regional Richards. Physics and identifiability do. A 38–52-layer state with placeholder parameters, no lateral flow and regime-switching non-Gaussian variables gives an EnKF a far larger, worse-conditioned state without information the observations can constrain.

**Recommended three-tier architecture:**
1. **Static tier.** A 90 m critical-zone medium that sets store capacities.
2. **Oracle tier.** Fixed Richards at every assimilated sensor column, serving as the depth operator shared by dv/v (#198) and factor of safety (#128). Also run it on a hydrologic-response-unit library of about 10³ classes (soil class × regolith depth × slope × HAND × cover × elevation band).
3. **Cycling tier.** Mass-conserving stores per cell, with transfer parameters fitted to the oracle and regionalised against held-out gauges and wells. Lateral flow comes from a hillslope store everywhere on steep ground and an explicit 2D Dupuit layer where convergence matters, such as Landlab `GroundwaterDupuitPercolator`. Hillslope drainage times range from about 6 to 350 days, so lateral flow cannot be deferred.

**Pilots: no single domain does both.**
- **Budget-closure pilot first.** Use a rain-dominated lowland gauged basin with dense wells. Candidates are Newaukum Creek (12108500, 79 km², inside the twin grid) or Clarks Creek; *verify* geology and the sensor inventory. USGS returns zero continuous groundwater recorders in the boxes checked, so continuous records must come from the new ingest issue, Washington Ecology or county networks. A possible Osceola lahar cap on the Enumclaw plateau is both a confound and an opportunity for #228's lahar-cap slice.
- **Hydromechanics pilot second.** Use the in-grid Rainier sub-box: the lower Nisqually–Paradise corridor and the Carbon–Puyallup foothills, at permanent stations, nodes and DAS. Reuse the same stores and oracle. Nodes and DAS were not recording in December 2025, so the storm test rests on permanent stations.

---

## 7. Data assimilation consistency

The DA designs (#187, #188, #192, #194) are good textbook DA, but they sit on a model whose own leak (−43 to −102 mm per 300 days) is the size of a 1σ head increment (150 mm at S_y = 0.30). A DA-increment ledger cannot separate model leakage from correction. **#172 and the valley fix are hard prerequisites for #188, not just for release.**

What #187 should state:
- **Storage vs head.** With fixed per-cell S_y the two are equivalent. Storage matters for the mm ledger, for uncertain S_y, and once a vadose store exists.
- **Increments.** Allow increments, but ledger them per compartment. Log every clip as its own ledger term; clipping removed ~1 mm per analysis per metre at wet states in one probe. Treat a persistent mean increment as model bias, never as something inflation should absorb.
- **Static vs dynamic error.** Keep the static offset separate from the dynamic anomaly. Following #192 literally, with B from static residual variograms, would inflate the dynamic σ about 37×.

**Do not assimilate:**
- Stage-3 or `gwl_dynamic` kriged maps, which double-count the wells;
- climatology-infilled wells;
- self-generated dv/v;
- forcing data listed as state observations (GHCN, Stage IV, GNSS PWV in `observability.py:899-907`);
- gauges through a footprint on head (`observability.py:894`). Gauges need a basin-mask, time-lag flux operator.

**Operator defects:**
- `anchor.assimilate_points` is 2–5.6× over-confident against BLUE.
- The soil-probe depth weighting creates step artefacts on sensor dropout (`fetch_insitu_sm.py:77-79`).
- SMAP and NISAR measure 0–5 cm and need a surface operator.
- The gated `water_table_point_footprint` exists but no production path calls it. Its 30 m screen cut-off mislabels deep upland water-table wells.

**Minimal real-data cycling pilot.**
- **Gates:** the ledger fixes, #89 daily calibration, #186 units fix, and a fixed per-cell S_y.
- **Domain:** the closure pilot basin.
- **State:** head anomaly plus S_root, with a perturbed-PRISM forcing ensemble and no parameter augmentation.
- **Assimilate:** per-well anomalies from screened continuous recorders only, so the 18.5 m static bias cancels.
- **Withhold:** the gauge, which tests the physical consistency of the increments; the probes; and one or two wells, to measure CRPS gain over open loop.

Then add, in order: probes through a depth operator; a precipitation multiplier constrained by the gauge; SMAP through a surface operator; dv/v once its gain is calibrated against co-located wells; and GNSS as an aggregate check.

---

## 8. Hazard consumers

**Best first consumer: deterministic discharge hindcasts on gauged basins.** Use a basin sum plus a unit hydrograph, needing no ensemble contract.
- Gauges observe the integrated flux at native support, every year.
- They directly test the partition being rebuilt.
- They allow held-out basins, earlier water years and the January 2009 rain-on-snow storm.
- The December 2025 storm lies inside the calibration window, so it does not test volume.

The queue has this upside down: flood validation #200 → #202 is held behind the ensemble chain (#187, #191).

**Landslide second.**
- Add slope-only and rainfall-threshold baselines; the slope-only control already separates events (27.9° vs 18.5°).
- Add hillslope piezometer validation. The USGS Mukilteo monitoring sites fall inside the grid.
- Rainier's S34 Richards columns can benchmark #131's lag.
- Add an explicit non-claim, or a separate pathway such as Scoops3D, for deep-seated failures.

**Liquefaction last.**
- It needs about ±0.5 m seasonal-high DTW in fill, and none of that skill exists yet.
- Under Zhu et al. (2017)-type coefficients (from recall; *verify*), DTW barely moves the probability: 0.5 → 3 m changes P by 0.02, while a 10% Vs30 change matters about 6× more.
- Pin the model (Sanger and Maurer 2025 is the stated target) and measure its DTW sensitivity before building #141.
- Use 2001 Nisqually as the test event.
- Valley cells saturating to DTW = 0 make the current water-budget route unusable in exactly these units.

---

## 9. GAIA launch readiness

### 9.1 Runner and grouper (fix before any unattended run)

1. **Merge the accepted September fixes.** Commit `98d2c36` exists only on `docs/soil-twin-audit-and-plan-revision-2026-09-10`, and main still treats `revise` as approval. Also unmerged on that branch are the per-issue ledger, safe stop, trusted gates and provenance (O1–O5 in the operational plan).
2. **Honour holds in the grouper.** `needs-human-decision` and paused milestones must not be queued. On main, #163 and #186 carry the label but sit in batches 2–3. The v0.3 Vs30 pause (#81–#86) is not encoded, and #81, the validation anchor, runs after the downscaling it should gate.
3. **Stop blocking on an epic.** `BLOCKED_BY[187]` includes epic #171, which the runner never closes, so the entire DA chain waits on a human.
4. **Reconcile with the issue bodies.** `BLOCKED_BY` is a hand-written partial list and ignores the "Blocked by" lines in bodies. As a result the simulated queue dispatches:
   - #198, #162 and #161 in the first DA batch, before #187, #172 and #176;
   - #227 and #225 in batch 7, before #223 (batch 16) and before the conservation batch #172–#175 (batch 8);
   - #226 while #187 and #189 are held;
   - #224 and #128 with no encoded blockers;
   - #89, #87 and #100 after the #137 calibration they must precede.
5. **Stop co-batching coupled physics.** Batches split at 4 issues by reverse number. That puts #172–#175, four coupled edits to one function, in a single PR. It also splits #130/#133/#174, which overlap, across batches 8 and 22.
6. **Fix stale citations.** Line numbers in #161, #162, #165 and #170 point to old locations in `observability.py` and will misdirect agents.
7. **Fix closing semantics.** "Closes #N" on auto-merge closes physics issues whenever a PR adds a function. Use "Refs" by default and close per issue on accepted evidence.

### 9.2 Verdicts across the 132 open issues

| Final verdict | Count |
|---|---|
| keep as written | 5 |
| rewrite | 68 |
| split | 20 |
| hold for a human decision | 11 |
| merge into another issue | 8 |
| close as superseded | 8 |
| close as done | 5 |
| defer | 7 |

Agent-ready today: 19. The full table is in `issue_verdicts.json`. Issues judged done or superseded must be re-checked by a human before closing.

- **Close as done (verify first):** #20, #28, #64, #125, #152.
- **Close as superseded:** #12, #14, #19, #51, #54, #56, #87, #161. Fold #87 into #131, and #161 into #188.
- **Merge:** #8, #23, #46, #85, #147, #165, #166, #167.
- **Hold for a human decision:** #22, #24, #25, #30, #81, #129, #135, #136, #162, #186, #204.
- **Agent-ready now:** #9, #40, #49, #52, #65, #70, #140, #143, #144, #145, #147, #148, #155, #156, #157, #166, #167, #169, #170.

### 9.3 Missing issues (proposed; details in `issues/*.md`)

**Hydrology core:**
- whole-system water ledger and conservation harness;
- valley HAND < d0 sink and seepage face;
- SWE as a carried state, with rain-on-snow;
- lateral groundwater, two-way stream exchange and pumping, behind a design decision;
- calibration and validation harness: basin masks, model-hydrograph BFI, held-out manifest;
- continuous groundwater-recorder ingest;
- multi-year R_ref drift and spin-up test;
- a single θ product.

**GWL and DA:**
- Stage-3 DTW sign inversion (P0);
- per-domain CV mechanics with no duplicate folds;
- full/block R with Cholesky;
- OU τ estimated per state and domain;
- temporally correlated observation error;
- OSSE hygiene: a nature run through the #198 operator.

**Rainier and hydromechanics:**
- port and fix the Richards oracle;
- 90 m critical-zone static build and HRU library;
- pilot-selection decision record;
- v0.4 static rebuild before #223;
- rewrite #223 to include `/cz`, wells and S35;
- merge the leverage review with a staleness note;
- kernel normalisation;
- non-hydrologic dv/v confounders: temperature, snow and atmospheric loading, tides;
- band-observability requirement for vadose dv/v.

**Hazards:**
- deterministic discharge-hindcast pilot decoupled from #191;
- conservative NHDPlus routing operator;
- LandLab adapter decision with the drainage semantics and the API claim corrected;
- landslide inventory ingest and frozen holdouts;
- slope-only and rainfall-threshold baselines;
- deep-seated landslide pathway or non-claim;
- liquefaction model pin and value-of-information gate;
- 2001 Nisqually event validation;
- seasonal-high DTW time series.

**Forecast:**
- meteorological member source;
- mass-conserving orographic precipitation downscaler;
- forecast-mode PET and lead-0 continuity;
- FuXi daily aggregation aligned to PRISM's 12–12 UTC day;
- fix the FuXi adapter call path before the GPU run.

### 9.4 Proposed corrected dependency table (for `scripts/gaia_group_issues.py`)

"L" is the new ledger issue, "V" the valley-sink issue, "SWE" the snow-state issue, and "G" the v0.4 static rebuild.

```
187: [186, 52, 89, 137, 172, L]      # drop epic 171
188: [187, 189, 172, V, 89, 186]
189: [187, 9]                         # aquifer screening before the well operator
131, 173, 174: [172]
172: [L]
175: [L, V]
137: [172, 173, 174, 175, 131, 100, 89]
89, 100: [70]                         # verifier: #100 blocks on #70, not #137
130: [172, 174]
133: [130, 174]
176: [172, 131, 198]
198: [172, 187]
45, 50, 30, 85, 165: [198]
162: [188, 169]                       # #161 folded into #188
226: [187, 189, 100]
223: [G]
224: [223, 128]
225: [223, L]
227: [223, L, SWE]
128: []                               # narrowed: FS algebra + named closure
129: [128]
141: [liquefaction model decision]
142: [137, 46, 9]
83, 84, 85, 86: [81]                  # plus the v0.3 pause as an explicit hold
200: [187]                            # deterministic routing pilot 201 not behind 191
201: [L]
202: [201]
```

### 9.5 Recommended first waves

1. **Human or supervised, not queued.** Merge the runner fixes and encode holds and blockers. Write the hydrologic-core design record: topology, ledger, adopt or benchmark. Pick the pilot basin. Pin the liquefaction model.
2. **Agent wave 1: low risk, high leverage.**
   - Software hardening: #152 (verify whether done), #153, #155, #156, #157.
   - Foundations: #52 (one θ), #70 (multi-year daily PRISM, which unblocks #89 and #100), #9 (aquifer screening), #49, #40.
   - Documentation and guards: #140, #145, #147, #148.
   - New ledger and conservation harness (L), valley sink (V), Stage-3 sign test.
3. **Agent wave 2: one coherent PR at a time under the design record.** Run the vadose store (#172, #131, #173) as a single package, then interflow (#174, #130, #133), then the aquifer boundary (#175), then the held-out #137.
4. **Then:** the cycling pilot (#187 → #189 → #188 → #192 → #194) and the deterministic discharge hindcast.
5. **Then:** the #198 operator port and the Rainier hydromechanics pilot.

---

## 10. Decisions only the PI can make

1. **Build or adopt.** Choose the hydrologic core topology, whether to benchmark against DHSVM or ParFlow, and whether to retire the monthly path.
2. **Pilots.** Choose the closure basin and the Rainier hydromechanics sub-box.
3. **Rainier operator.** Confirm whether rainier3d's critical-zone column becomes the #198 reference operator, and who owns the port.
4. **Liquefaction model.** Pin the model and its probability semantics, and decide whether dynamic DTW is worth building after the value-of-information test.
5. **Holds.** Release or keep the Vs30 pause and the holds on #163 and #186.
6. **Automation authority.** Decide what GAIA may merge unattended, and whether "Closes" or "Refs" is the default.
7. **Book title.** Decide whether to adopt "State2Hazard" and how to stage the book rewrite (#204) behind the physics.

---

## 11. Caveats

- Probes use synthetic forcing and uniform soils, so magnitudes scale with real forcing. The mechanisms follow directly from the code.
- The domain fraction of cells with HAND ≤ d0 has not been computed; the domain rasters were not available. It is likely large on Puget valley fill.
- Compiled and GPU costs, the Zhu et al. coefficients, DHSVM and ParFlow details, Link et al. 2004 and the Newaukum inventory are marked *verify*.
- The Stage-3 sign inversion is near-certain from variable definitions, but the monthly well-anomaly producer is not in the repo. Confirm with the synthetic test before rerunning products.
- The hydromechanics agent briefly downloaded package files into the local repo and deleted them. `git status` afterwards shows only Marine's three pre-existing untracked files.
