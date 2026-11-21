# Lens: hazard-demands

# What each hazard model needs from the soil-state twin, and what the twin can supply

Scope: the code on origin/main (435445f), the 132 open issues, the GAIA queue simulation, the rainier3d clone and paper, and the unmerged 2026-09 reviews. I wrote two probes that drive the real `coupled_water_budget` with synthetic forcing: `wf/hazard_probe.py` (one 240-day wet season) and `wf/drift_probe.py` (20 years at 1,650 mm/yr). Both are under the scratchpad `wf/` folder. Nothing was written to GitHub or to the repos.

## 0. What the twin physically is today

These are the facts every hazard comparison below depends on.

- **Root zone.** One store holding θ·z_r. z_r comes from SOLUS soil thickness clipped to 0.10–2.0 m (`src/data/fetch_solus_domain.py:126`). The LandLab recharge export uses a fixed scalar of 1.0 m instead (`src/io/landlab_export.py:344`).
- **Water table.** One linear-reservoir head anomaly h around a static statistical datum d0, with wt = d0 − h (`water_budget.py:157,266-279`). There is no perched store and no vadose store between the root base and the table.
- **No cell-to-cell exchange.**
  - Interflow is a fixed fraction f_lat = Ka·tanβ/(1+Ka·tanβ) with Ka = 2, and it leaves the cell in the same step (`:199-206,247-249`).
  - `accumulate_runoff` (`:300-311`) only rescales runoff in place by (1 + normalised accumulation). It moves no water and does not conserve mass. Its only caller is a test that locks in this behaviour (`tests/test_water_budget.py:73-76`).
- **Groundwater sink.** The sink is anchored by a single domain-wide R_ref of 3 mm/d, so that d0 is a steady state only where recharge equals 3 mm/d (`:188-197`). Cells with HAND ≤ d0 get gw_recess = 0, which means they have no sink at all (`:195`).
- **Calibration.** A grid search against domain-wide means of BFI, Q/P and seasonal amplitude, over one 10-month window (`notebooks/calibrate_fluxes.py:35,44,71`, using `prism_daily_2025-09_2026-06.zarr`).
- **Statistical depth to water.** The pooled block-CV result has RMSE 18.49 m, bias +3.54 m and R² 0.089, with only about 24 test wells per fold. Folds 0 and 4 are numerically identical, so there are effectively 4 folds (`data/processed/block_cv_metrics.json`). No per-domain metrics have ever been emitted (#47).
- **No mechanics.** `soil_mechanics.estimate_mechanics` raises `NotImplementedError` (`src/models/soil_mechanics.py:64`). LandLab is not a dependency (`pixi.toml` has only export tasks).

### What the probes show

**1. Drift over multi-year runs.** With 1,650 mm/yr of precipitation and 730 mm/yr of PET, mean recharge is:

| Cell | Mean recharge | R_ref |
|---|---|---|
| 30° hillslope | 1.47 mm/d | 3 mm/d |
| 35° hollow | 1.32 mm/d | 3 mm/d |

Because recharge is below R_ref, the table drains toward a new equilibrium:

| Cell | Year 1 depth to water | Year 5 | Year 20 |
|---|---|---|---|
| Hillslope (d0 = 15 m) | 15.4 m | 21.3 m | 33.5 m |
| Hollow (d0 = 3 m) | 3.5 m | 8.5 m | 12.8 m |

This matches the analytic equilibrium d = HAND − (R̄/R_ref)(HAND − d0). The e-folding time is about 12 years, which is why one 10-month calibration from h = 0 never sees it. It matters for any reanalysis or hindcast that needs spin-up, such as Jan 2009 (#224).

**2. Valley-fill cells (HAND = 1 m, d0 = 2 m).** The table rises to the surface (−0.01 to −0.03 m) and stays there with zero seasonal amplitude. Saturation-excess runoff then removes all further rain. The seasonal-high depth to water is identically 0 m. Issue #177 m5 calls these cells "frozen", but they are not frozen at d0; they saturate. These are exactly the units liquefaction cares about.

**3. A 200 mm, two-day atmospheric river on a 30° slope with a 1 m soil.**
- Root-zone θ peaks at 0.39 against θ_sat 0.45. No saturated layer ever forms.
- The regional table at 15 m rises only 0.2 m, starting the same day (no transit lag).
- Root-zone drainage reaches the table or leaves as interflow within the step.

So any pore pressure on a shallow failure plane would be identically zero.

**4. The exported "recharge" is net of interflow.** The fraction 1 − f_lat of root-zone drainage that the export calls recharge is:

| Slope | Fraction exported |
|---|---|
| 13.3° | 0.68 |
| 27.9° (S24 event median) | 0.49 |
| 35° | 0.42 |
| 40° | 0.37 |

---

## 1. Landslides (#127–#138, #12, #224)

### What the hazard model needs

**Shallow failures** (fall and winter storm debris slides and flows, such as Jan 2009):
- **State variable:** transient positive pore pressure, or saturated thickness m = h_w/z, on the colluvium–bedrock contact at 0.5–3 m depth.
- **Horizontal scale:** 10–30 m (hollows, road cuts).
- **Time scale:** hours to 3 days of intensity, on top of 2–6 weeks of antecedent wetness.
- **Accuracy:** in infinite-slope FS with φ′ = 33°, β = 30–35°, z = 1.5 m and c = 4 kPa, a ΔFS of 0.1 corresponds to Δh_w ≈ 0.26–0.31 m (probe). So the requirement is about ±0.3 m of perched head, or relative wetness to about ±0.2.

**Deep-seated failures** (rainier3d S24 lidar-protocol deposits, median failure depth 14.6 m, n = 453; `rainier/docs/paper/rainier3d_paper.md:1037`):
- **State variable:** head at a 10–30 m shear zone.
- **Horizontal scale:** 10²–10³ m.
- **Time scale:** weeks to months, and multi-year.
- **Accuracy:** with z = 14.6 m, a ΔFS of 0.1 corresponds to Δh_w ≈ 2.5–3.0 m. Movement rates track the seasonal head anomaly rather than absolute DTW, so this is mainly an anomaly requirement.

### What the twin delivers now

**For shallow failures, nothing.**
- The root zone cannot saturate (probe 3).
- There is no perched store (#130).
- Interflow is a sink, not a stress (#133).
- Slope is averaged from 10 m to 90 m (`src/features/compute_terrain_domain.py:172-175`).

The export contract carries no storm information either:
- Saturation fraction is exported as a time mean (`landlab_export.py:238,246`).
- Recharge is exported as a time mean and max on the coarse forcing grid. The default forcing is monthly TerraClimate (`:315-316,341`).
- Precipitation goes in with no snow partition (`:304`).
- Seasonal-high DTW is exported only if an operational DTW series exists, and none does (`:333-336`).

There is also a semantic mismatch with LandLab. `LandslideProbability` does not ingest `water_table__depth` at all. It builds relative wetness from recharge × specific contributing area / (T·sinβ) (unmerged audit followup, `soil-twin-audit-followup-2026-09-10.md:62-67`). Yet `docs/twin/07-hazard-integration.qmd` says it takes `water_table__depth`. The recharge it should receive is total drainage into the soil layer. The twin exports drainage net of interflow, which is 37–51% of drainage on failure-prone slopes (probe 4).

If #133 adds downslope convergence inside the twin while LandLab also multiplies by contributing area, convergence is counted twice.

**For deep-seated failures, an anomaly of roughly the right seasonal magnitude** (calibrated amplitude 1.02 m vs 1.06 m observed, `water_budget.py:61`), with three problems:
- It is damped by S_y = 0.30.
- It responds without any lag (#131).
- It drifts by tens of metres over multi-year runs (probe 1).

The absolute head at 15 m depth on a Cascade hillslope is unconstrained. The pooled DTW RMSE is 18.5 m, rainier3d wells are 97% lowland, and `fractured_upland` is report-only while `volcanic_deep` is masked (`src/evaluation/domain_gates.py:34-36`).

### After the water-budget issues (#131, #137, #172–#175, plus #130/#133)

- A lagged vadose store (#131/#172) and an interflow store with memory (#174) make storm lags and a perched head representable.
- A spatially consistent anchor with nonlinear recession (#175) can remove the drift, but only if the anchor becomes per-cell. As written, #175 does not quantify the drift.

Even then, the shallow state is a parameterised bucket at 90 m, never compared with any pore-pressure measurement. No issue names the hillslope piezometer and soil-moisture records that would test it, such as the USGS Puget Sound landslide monitoring sites near Mukilteo, which fall inside the twin grid at EPSG:5070 (−1955287, 3044946).

rainier3d's 1-D Richards runs over 350 sites for the Dec 2025 atmospheric river (`rainier/docs/critical_zone.md:210`) are a ready physical benchmark for #131's lag. #223–#228 predate that module.

### Specific issue problems

- **#224's caveat compares two different populations.** The 14.6 m median depth belongs to the lidar-protocol deposits. The 351 Jan 2009 landslides are in the compilation layer, are identifiable only by date, and have no recorded depths (`rainier3d_paper.md:1030,1051`). The paper itself gives failure depth for "247 events" (`:1029`) against 453 deposits (`:1037`).
- **The Dec 2025 atmospheric river lies inside the twin's calibration window**, so it is not an independent test of volume.
- **#127 is stale.** It still lists #126 and describes the old `landlab_export:265` call, which `:260-266` now documents as fixed.

---

## 2. Liquefaction (#139–#149)

### What the hazard model needs

- **State variable:** seasonal-high depth to water in Holocene alluvium, artificial fill, tideflats and lowland lahar deposits. It matters most in the 0–3 m range, where it sets the saturated thickness of the 1–10 m critical layer and σ′v.
- **Horizontal scale:** facies at 10–100 m, which 90 m cells cannot resolve (#147).
- **Time scale:** seasonal. A scenario earthquake arrives at a random time, so the product needs the DTW distribution by season tied to a return period (#138 m2, #149 m2). A nowcast matters only for post-event loss estimates.
- **Accuracy:** about ±0.5 m when DTW is under 3 m, and correct shallow (<3 m) vs deep (>6 m) classification. The gate is 0.75 m target and 1.5 m threshold (`domain_gates.py:31`).

### What the twin delivers now

**The statistical route has never been tested where it matters.** The only reported spatial skill is the pooled 18.5 m RMSE on about 121 test wells, with no valley-fill metric (#47). That is roughly 12–37× worse than the valley-fill gate, and the gate is unvalidated.

**The water-budget route fails in the same cells.** Valley cells with HAND ≤ d0 have no groundwater sink. The probe shows they saturate to the surface with zero amplitude, so every fill cell would read as DTW = 0 at maximum hazard. #177 files this as a "minor … verify" item.

**The claimed value-add of the twin may be negligible.** In the published Zhu et al. (2017) non-coastal GLM (from my recall of the coefficients; to verify, bib key `zhu2017geospatial`), DTW enters at −0.0333 per metre of logit. In the probe, DTW of 0.5 → 3 m changed P from 0.590 to 0.570, while a Vs30 change of 200 → 180 m/s changed the logit by 0.20. This is about six times the effect of a 2.5 m DTW change.

So #141's acceptance ("dynamic DTW changes the map vs static") would show a near-null effect under Zhu-type coefficients. The repo's actual target, Sanger & Maurer (2025, arXiv:2509.10965), is a geospatial-AI model whose DTW sensitivity must be measured before anyone claims value-add. The roadmap review already asked #141 to pin a model.

**After the water-budget issues:** #175 might restore a valley sink, but sub-metre accuracy in fill comes from the wells, not the bucket. That needs:
- shallow-screened wells inside fill and alluvium (#46, #9);
- tidal and stream boundaries (#10);
- per-domain CV (#3, #47).

None of that is code an agent can finish. The one modern test event is the Feb 28, 2001 Nisqually earthquake: liquefaction in Duwamish and Olympia fill near the seasonal high. It is not mentioned in any issue.

---

## 3. Flood (#199–#202, discharge part of #224, #59)

### What the hazard model needs

- **State variables:** the quickflow vs baseflow partition and antecedent storage, which together set the runoff ratio; plus snow and rain-on-snow input.
- **Routing:** a conservative routing operator from cells to reaches.
- **Time scale:** hourly to 6-hourly. Peak timing in 10–1,000 km² Cascade basins needs to be within ±3–6 h, volumes within ±10–20%. Daily resolution is adequate only for volume and day-scale timing in basins of a few hundred km² or more.

### What the twin delivers now

- A daily step, with runoff and interflow leaving each cell in the same step, so there is no hillslope or channel travel time.
- No routing. `accumulate_runoff` is a non-conservative in-place scaling: in the probe it gained 1.6% of mass with a lognormal accumulation field and up to 2× in the limit. It is used only by a test.
- No snow in the export path (`landlab_export.py:304`). Elsewhere snow is degree-day only, with no rain-on-snow (#177 m1). Rain-on-snow is the defining mechanism of Jan 2009-type floods.
- Calibration to 10-month domain-wide sums, with no event timing ever scored.
- Neither model reproduces the Dec 2025 storm runoff mechanism. rainier3d's Richards runs produced **no runoff** in that event because POLARIS Ksat exceeds MRMS hourly rates (`critical_zone.md:210`), yet the gauges show strong hydrographs. That points to saturation excess and subsurface stormflow, not Hortonian runoff. #132's Hortonian premise is therefore secondary outside burn scars.

**After the water-budget issues:** #174 interflow memory and #175 nonlinear recession give realistic recession limbs and multi-day lags. A peak-flow product still requires #201 routing and sub-daily forcing (MRMS).

---

## 4. Best first consumer for testing the twin's physics

**Discharge hindcasts on gauged basins, not a flood-hazard product.**

- NWIS gauges observe the integrated flux at native support, at 15-minute resolution, every year.
- They directly test the partition being rebuilt in #172–#175: S_y, Ka, R_ref, lag and snow.
- They allow genuinely held-out tests: basins excluded from calibration, the Jan 2009 rain-on-snow storm, and earlier water years.
- They need no mechanics and no ensemble contract. A deterministic daily lumped-basin run (sum of cell Q over the basin plus a unit hydrograph) is enough to falsify the budget.

The other two consumers are weaker tests:
- **Landslides second.** Inventories are binary and dominated by slope. The slope-only control already separates events (27.9° vs 18.5°, `rainier3d_paper.md:338`), the dates are coarse, and shallow pore pressure has no observations in the issue plan.
- **Liquefaction last.** It needs sub-metre absolute DTW in fill, has essentially no event data, and its GLM may barely respond to DTW.

**The queue has this upside down.** `scripts/gaia_group_issues.py:99-101` holds #200→#201→#202 behind #187 and #191 (the ensemble DA chain), so the most informative validation runs last. Meanwhile #128, #129, #141 and #224 are queued with no encoded blockers, because BLOCKED_BY (`:86-102`) has no entries for any landslide, liquefaction or Rainier issue. #224 states "Blocked by #223, #128" only in prose.

---

## 5. Which issues are premature for autonomous agents

Note that GAIA auto-merges with "Closes #N" (`docs/gaia-automation.md:114,189`). An agent PR that adds a function can close a physics issue.

### Hold or relabel `needs-human-decision`

- **#129:** needs LandLab as a dependency, a recharge-semantics adapter, and inventory curation.
- **#130 and #133:** design choices that overlap #172 and #174, which run in batch 7 (collision risk), plus the double-counting of convergence with LandLab.
- **#132:** scope it to post-fire and merge with #134/#122.
- **#134:** parameter choices from literature.
- **#136:** a GPU/cluster run, not agent-executable.
- **#224, landslide part:** depends on #128 and a spun-up, drift-free budget.
- **#141:** model not pinned; the acceptance criterion is mis-specified.
- **#142:** a research and data problem; an agent cannot meet its sub-1.5 m acceptance.
- **#146:** self-labelled "Future/later", but it is in queue batch 25.
- **#12:** its acceptance requires agreement from the human reviewer.

### Good agent tasks now

- **#128**, but narrowed to: pure FS algebra; a named pore-pressure closure taken from `hydro_state.py` (per the August comment on #128); no product or corridor claims; colluvium thickness and c_r passed in as inputs. A prior GAIA attempt aborted after 123 s (`docs/gaia-runs/issue-128/20260818T062313Z`).
- **#140, #145, #147, #148, #149:** documentation and guards.
- **#143 and #144:** ShakeMap ingestion and a σ field.
- **#47:** compute the achieved per-domain valley-fill metrics.
- **#177 m5:** promote it to a real bug fix with a test that valley cells do not saturate.
- **A new deterministic discharge-hindcast issue**, decoupled from #187/#191.

### Missing issues

- Multi-year drift of the R_ref anchor, with a spin-up test.
- Valley-cell saturation, as a P1 bug.
- A recharge-semantics adapter for LandLab (pass drainage, not recharge net of interflow), plus a correction to `07-hazard-integration.qmd`.
- Hillslope piezometer and soil-moisture validation, starting with USGS Puget Sound landslide monitoring.
- rainier3d Richards (S34) as the benchmark for the #131 lag.
- Measuring the DTW sensitivity of the pinned liquefaction model before building #141.
- 2001 Nisqually as the liquefaction test event.

### Uncertainty

- The probes use synthetic forcing and uniform soil (θ_wp/fc/sat = 0.10/0.30/0.45), so the drift magnitudes scale with the real precipitation and ET. The mechanism (a uniform R_ref against slope-dependent recharge) and the valley saturation follow directly from the code.
- The Zhu GLM coefficients come from memory and should be checked against the paper.
- The claim about LandLab's interface rests on the unmerged audit's pinned-source excerpt.


## Claims (with adversarial verdict)

- **hazard-demands-1** [major] [confirmed] Shallow-landslide FS needs perched pore pressure at 0.5-3 m to about +/-0.3 m: in infinite-slope FS (phi'=33 deg, beta=30-35 deg, z=1.5 m, c=4 kPa) a dFS of 0.1 corresponds to dh_w of 0.26-0.31 m. For the 14.6 m deep-seated case it corresponds to 2.5-3.0 m.
  - evidence: wf/hazard_probe.py FS block; rainier3d_paper.md:1037 (median depth 14.6 m, n=453)
  - issues: Add a quantitative accuracy requirement on h_w (shallow) and on the head anomaly (deep) to #128/#129/#130 acceptance, instead of 'monotone response'.
  - verifier: I re-derived it. In infinite-slope FS, dFS/dh_w = gamma_w*tan(phi')/(gamma_s*z*tan(beta)). It does not depend on c. With phi'=33 deg, gamma_s=19, z=1.5 m this gives 0.387/m at 30 deg, so dFS=0.1 needs dh_w=0.26 m (0.31 m at 35 deg). At z=14.6 m it needs 2.5-3.05 m. hazard_probe.py reproduces all four numbers. rainier3d_paper.md:1037 does say 453 deposits, median 14.6 m. Caveats: (a) infinite-slope FS is a poor model for 14.6 m deep-seated failures, so the deep number is only an order of magnitude. (b) The result assumes h_w is a vertical saturated thickness. The prior GAIA #128 run found that reading h_w as piezometric head over-predicts u by 1/cos^2(beta) (docs/gaia-runs/issue-128/20260818T062313Z/dashboard.html), so the accuracy requirement has to name its convention (#128 Aug comment on hydrostatic vs slope-parallel closure).
- **hazard-demands-2** [critical] [confirmed] The twin cannot produce positive pore pressure in the root zone under a large storm. A 120+80 mm two-day atmospheric river on a 30 deg, 1 m soil gives peak theta 0.39 against theta_sat 0.45, and the 15 m water table rises only about 0.2 m, starting the same day.
  - evidence: wf/hazard_probe.py hillslope cell; water_budget.py:236-266 (2-day drainage, f_lat interflow sink, R/Sy head update with no lag)
  - issues: #128 FS driven by twin hydrology will be insensitive to storms until #130/#174/#131 land. State this in #127/#129 and hold #129 until then.
  - verifier: Reproduced: theta max 0.390. Hillslope table 15.47->15.28 m by day 102, and it already moves on the storm day (day 100: 15.40). The limit is actually structural, which is stronger than the claim. theta is written after drainage (water_budget.py:247-253), so on a daily step recorded theta can never exceed fc+(sat-fc)*exp(-dt/tau)=0.391 whatever the storm. My probe with 2x200 mm and 2x500 mm gives exactly 0.3910, and the extra water leaves as runoff (:236). No perched or positive-pressure state exists anywhere in the budget. Head rises by R/Sy in the same step (:266), which is #131's point. Nuance: valley cells do reach saturation (see claim 4), so 'cannot' holds for hillslope and hollow cells, not the whole domain.
- **hazard-demands-3** [critical] [confirmed] A domain-constant R_ref=3 mm/d makes the static baseline d0 a steady state only where recharge equals 3 mm/d. On slopes, where f_lat removes 50-60% of drainage, multi-year runs drift deep: in a 20-yr probe at 1650 mm/yr, the 30 deg hillslope went from 15 to 33.5 m and the 35 deg hollow from 3 to 12.8 m (e-folding about 12 yr), invisible to the 10-month calibration.
  - evidence: wf/drift_probe.py; water_budget.py:88,188-197,266-273; notebooks/calibrate_fluxes.py:44 (prism_daily_2025-09_2026-06 only)
  - issues: Expand #175 (or add a new issue) to require a per-cell anchor plus a multi-year spin-up/drift test. Block #224 (Jan 2009 hindcast) and any reanalysis on it.
  - verifier: Reproduced exactly: hillslope 15->33.48 m, hollow 3->12.76 m, gentle 4.67->7.86 m. From the code (:193-196, :266-272), equilibrium is HAND-d = (R/R_ref)*head0 and the e-folding time is Sy*head0/R_ref. That is 12.3 yr for the hillslope (head0=45 m) but about 4.7 yr for the hollow (head0=17 m), so 'about 12 yr' applies only to the hillslope case. Calibration uses only prism_daily_2025-09_2026-06 (calibrate_fluxes.py:44), so it cannot see this drift. #175 already states the concept ('only self-consistent where cells get 3 mm/day'); the new parts are the quantification and the spin-up test. The forcing is synthetic (1650 mm/yr, single soil), so real drift magnitudes depend on the actual per-cell recharge.
- **hazard-demands-4** [critical] [confirmed] Valley cells with HAND <= d0 have no groundwater sink. In the probe the table rises to the ground surface (DTW -0.01 to -0.03 m) and stays there with zero seasonal amplitude. #177 m5 understates this as 'frozen ... verify'; the cells actually saturate, which is the opposite of frozen at d0.
  - evidence: water_budget.py:193-196 (gw_recess=0 where head0<=1e-3), :264 comment contradicts; wf/hazard_probe.py and wf/drift_probe.py valley cells; issue #177 m5
  - issues: Promote #177 m5 to a P1 bug with a test (valley cells must keep a bounded, non-surface table). It blocks #141/#142 use of any budget-derived DTW.
  - verifier: head0=clip(HAND-d0,0) means gw_recess=0 wherever HAND<=d0 (:193-196), and nothing else lowers h (:266-273). My 400-day probe ends at wt=-0.035 m (above the ground) with zero baseflow. There is no clamp on wt_depth<0. The comment at :264 ('Valley floors (HAND ~ 0) cannot rise at all') is the opposite of what the code does. #177 m5 calls these cells 'frozen ... verify', which misdescribes them: they saturate. I could not quantify how many real cells have HAND<=d0 because no rasters are in the checkout. Note also that export fills missing d0 with 5 m (landlab_export.py:291), which would put every cell with HAND<5 m in this state.
- **hazard-demands-5** [major] [partially] The exported 'recharge' is drainage net of interflow, i.e. 1-f_lat = 0.49 of root-zone drainage at 27.9 deg (S24 event median slope) and 0.42 at 35 deg. LandLab LandslideProbability's recharge is the water feeding lateral flow in the soil layer, so the exported field underestimates wetness on failure-prone slopes by about 2x.
  - evidence: water_budget.py:199-206,247-249; landlab_export.py:304-320; wf/hazard_probe.py f_lat table; soil-twin-audit-followup-2026-09-10.md:62-67
  - issues: New issue or #64/#138 item: define the recharge-semantics adapter (export drainage = recharge+interflow for LandLab), and add a test.
  - verifier: The semantics hold: the export takes wb.recharge_mm (landlab_export.py:304-316), which is drain*(1-f_lat) (:247-249). The f_lat table reproduces (0.49 at 27.9 deg, 0.42 at 35 deg). But 'underestimates wetness on failure-prone slopes by about 2x' is not supported. Slope and HAND are bilinearly sampled onto the ~4 km forcing grid (:284-290), so the f_lat actually applied belongs to a sampled point, not to the failure cell. At 4 km that slope is not systematically 28-35 deg. LandLab wetness is also capped at 1. The direction of the bias is real, but its size is unquantified.
- **hazard-demands-6** [major] [confirmed] LandLab LandslideProbability does not ingest water_table__depth or saturation fraction. It derives relative wetness from recharge, transmissivity, contributing area and slope. docs/twin/07-hazard-integration.qmd still says it takes water_table__depth.
  - evidence: soil-twin-audit-followup-2026-09-10.md:62-67 (pinned landlab source line 250); 07-hazard-integration.qmd 'The export contract is unchanged - LandLab's LandslideProbability takes water_table__depth'
  - issues: Fix the doc claim. Make #129 depend on an explicit adapter issue. Warn #133 that in-twin convergence plus LandLab's contributing area would double-count.
  - verifier: 07-hazard-integration.qmd:59 reads 'The export contract is unchanged — LandLab's LandslideProbability takes water_table__depth'. The pinned input list in soil-twin-audit-followup-2026-09-10.md:55-67 has neither water_table__depth nor saturation_fraction. That audit lives only on an unmerged branch (reviews copy), so the doc error is undetected on main. The double-counting warning for #133 is reasonable: LandLab already applies contributing area a/sin(beta).
- **hazard-demands-7** [major] [confirmed] The LandLab export carries no storm-scale information: saturation fraction is a time mean, recharge is a time mean/max on the coarse forcing grid with default monthly TerraClimate, precipitation has no snow partition, and the seasonal-high DTW needs a DTW series that does not exist.
  - evidence: landlab_export.py:238,246 (.mean('time')), :315-316, :341 (terraclimate_monthly default), :304 (precip as liquid input), :333-336
  - issues: Update #64/#138 scope. Reword #127 epic text, which is stale about #126 and landlab_export:265.
  - verifier: Every cited line checks out: .mean('time') at :238/:246; mean/max at :315-316; terraclimate_monthly default at :341, which triggers the 'not calibrated' warning at :300-302; raw precip with no liquid_input at :304; dtw-series unset at :333-336. The export is inconsistent with the calibration, which does run liquid_input with snow on (calibrate_fluxes.py:63-66). #127 is stale: it cites landlab_export.py:265 calling the budget without slope/HAND (now fixed at :304-307) and lists #126 as open, but #126 is closed.
- **hazard-demands-8** [major] [confirmed] #224's caveat compares different populations. The 14.6 m median failure depth belongs to the 453 lidar-protocol deposits (mostly deep-seated landforms). The 351 Jan 2009 storm landslides are in the compilation layer, identifiable only by date, with no depth. The paper also gives depth for 247 events versus 453 deposits.
  - evidence: rainier3d_paper.md:1029,1030,1037,1051
  - issues: Rewrite the #224 caveat: score Jan 2009 (likely shallow) against a shallow-store FS, and score lidar deposits against the deep seasonal head. Do not use the 2 m SOLUS cap argument for the 2009 set.
  - verifier: rainier3d_paper.md:1037 gives a depth for 'every lidar-protocol deposit (453 deposits, median 14.6 m)'. :1029 gives depth_m for 247 events. :1030 and :1051 say the 351 Jan 2009 landslides are in the compilation and identifiable only by date. #224's caveat ('S24 median failure depth 14.6 m (n=453), below the 2 m SOLUS cap') applies one population's depth to the other population's events. 'Mostly deep-seated landforms' and 'likely shallow' are reasonable inferences but are not stated in the paper. The 247-vs-453 count inconsistency is a real paper defect.
- **hazard-demands-9** [minor] [not-checked (minor)] The Dec 2025 atmospheric river proposed in #224 lies inside the twin's flux-calibration window (Sep 2025 to Jun 2026), so it is not an independent test of runoff volume. Only event timing is unconstrained by the calibration.
  - evidence: notebooks/calibrate_fluxes.py:44; issue #224
  - issues: #224 should label Dec 2025 as an in-sample timing check and use Jan 2009 or another held-out water year as the independent test.
- **hazard-demands-10** [minor] [not-checked (minor)] The Rainier box is the twin's weakest hydrologic regime: rainier3d wells are 97% lowland, the fractured_upland gate is report-only, and volcanic_deep/confined_basalt are masked. About 83% of the Rainier box lies inside the twin 90 m grid.
  - evidence: domain_gates.py:34-36; context/rainier3d_map.md (97% wells lowland); pyproj overlap computation (0.83)
  - issues: #224 landslide AUC should be framed as testing terrain plus forcing, not twin hydrology. Add a slope-only and time-shifted negative control as mandatory acceptance (already partly listed).
- **hazard-demands-11** [critical] [confirmed] Liquefaction needs seasonal-high DTW to about +/-0.5 m where DTW is under 3 m (gate 0.75/1.5 m in valley fill), but the only reported skill is the pooled block-CV RMSE of 18.49 m, bias +3.54 m, R2 0.089, on about 24 test wells per fold, with no per-domain result. Folds 0 and 4 are numerically identical.
  - evidence: data/processed/block_cv_metrics.json; domain_gates.py:31; issue #47
  - issues: Run #47 (compute achieved valley-fill metrics) before any #141/#142 work. Add fixing the duplicate-fold CV to #3.
  - verifier: block_cv_metrics.json has only a pooled block: RMSE 18.49 m, bias +3.54 m, R2 0.089. n_test is 23-26 per fold, about 121 wells in total. Folds 0 and 4 match to the last digit (17.40433266520234x), which points to a fold-assignment bug. domain_gates.py:31 sets valley fill to 0.75/1.5 m. The ordering is worse than stated: in queue_sim, #141 sits in batch 24 (0-indexed) while #47 is in batch 30 and #46 in batch 29, so the liquefaction MVP runs before skill is measured. The +/-0.5 m requirement is the lens's own choice, but a defensible one.
- **hazard-demands-12** [major] [partially] In the Zhu et al. 2017 non-coastal GLM form, as recalled (wtd coefficient -0.0333/m, to verify), DTW 0.5 to 3 m moves P only from 0.590 to 0.570, while a 10% Vs30 change moves the logit by 0.20, about 6x more. The 'dynamic DTW' value-add claimed in #139/#141 may be near-null unless the pinned model (Sanger and Maurer 2025 geospatial AI) is shown to be more DTW-sensitive.
  - evidence: wf/hazard_probe.py GLM block; docs/references.bib sanger2025liquefaction (arXiv 2509.10965, an AI model, not fixed-coefficient GLM); roadmap-review.md:89
  - issues: Before #141, add a task to pin the model and measure dP/dDTW. Rewrite #141 acceptance (the dynamic vs static sensitivity is expected to be small under Zhu-type models).
  - verifier: The coefficients match my recollection of Zhu et al. 2017 non-coastal (8.801, 0.334 lnPGV, -1.918 lnVs30, 5.408e-4 precip, -0.2054 dw, -0.0333 wtd), and P 0.590->0.570 reproduces. The '6x' is wrong as written. DTW 0.5->3 m shifts the logit by 0.083, and a 10% Vs30 change shifts it by 0.20, so the ratio is about 2.4x. 6x is only the per-metre comparison. Zhu also maps P to an areal extent (LSE) rather than using P directly. The pinned Sanger & Maurer 2025 is an arXiv geospatial-AI model (references.bib:338-345), so its DTW sensitivity is unknown. The recommendation to measure dP/dDTW first stands.
- **hazard-demands-13** [major] [confirmed] #142 (sub-1.5 m DTW in liquefiable units) is a data and research problem: shallow-screened wells in fill, tidal/stream boundaries, aquifer screening. An autonomous code PR cannot meet it, yet the queue batches it (batch 23) under an auto-merge pipeline that closes issues.
  - evidence: queue_sim.jsonl batch 23 [145,144,143,142]; docs/gaia-automation.md:114,189 (merge + Closes #N); issues #9, #10, #46
  - issues: Label #142 needs-human-decision or hold it in BLOCKED_BY behind #47, #46, #9, #10.
  - verifier: queue_sim batch 23 (0-indexed) is [145,144,143,142]. gaia-automation.md:114-118 and :189 show merge followed by 'Closes #N'. There is a HOLD/needs-human-decision path, but it fires on review or auditor failure, not because a task is a field-data problem. The #142 body asks to 'calibrate DTW against shallow-screened wells INSIDE young alluvium/fill, show sub-metre accuracy' and replace TOPMODEL in coastal fill. That depends on data and aquifer screening (#46, #9, #10) that an agent cannot produce.
- **hazard-demands-14** [minor] [not-checked (minor)] #146 is self-described as 'Future ... (later)' depth-resolved triggering, yet it is scheduled in GAIA batch 25.
  - evidence: issue #146 body; queue_sim.jsonl batch 25 [149,148,147,146]
  - issues: Remove #146 from the queue (milestone 'Future' or a hold label).
- **hazard-demands-15** [major] [confirmed] Flood needs conservative routed discharge at hourly to 6-hourly resolution. The twin has a daily step, same-step cell-local runoff and interflow loss, no routing, and an accumulate_runoff that only rescales in place (mass gain 1.6% in probe, up to 2x) and is used only by a test that locks in the behaviour.
  - evidence: water_budget.py:247-249,300-311; tests/test_water_budget.py:73-76; wf/hazard_probe.py accumulate_runoff ratio 1.0165
  - issues: Deprecate accumulate_runoff or replace it with a conservative D8 accumulation. Change the test. #201 must not reuse it.
  - verifier: water_budget.py:308-311 returns runoff*(1+fa/max), so total mass is multiplied by 1+mean(norm), anywhere from 1x to 2x (probe 1.0165). There is no routing at all. Its only caller is tests/test_water_budget.py:73-76, which locks in the behaviour. Daily step and same-step interflow loss confirmed (:247-249).
- **hazard-demands-16** [minor] [not-checked (minor)] Neither model reproduces the observed Dec 2025 storm runoff mechanism: rainier3d's Richards runs produced no runoff because POLARIS Ksat exceeds MRMS hourly rain, and the twin docstring states daily rain never exceeds Ksat (15-55 mm/hr). The dominant PNW mechanisms are saturation excess and subsurface stormflow, so #132's Hortonian premise is secondary outside burn scars.
  - evidence: rainier/docs/critical_zone.md:210; water_budget.py:41-44; issue #132
  - issues: Rescope #132 to post-fire and impervious surfaces and merge it with #134/#122. Do not let it displace #174 interflow-store work.
- **hazard-demands-17** [major] [confirmed] Rain-on-snow is absent (degree-day only), and the LandLab recharge export has no snow at all. Jan 2009-type Cascade floods and landslides are rain-on-snow atmospheric rivers.
  - evidence: forecast.py:105-131 (degree-day); landlab_export.py:304; issue #177 m1
  - issues: #224 Jan 2009 hindcast needs a rain-on-snow treatment or must state this limitation. Elevate #177 m1 from minor.
  - verifier: forecast.py:105-131 is degree-day on tmean only, with no rain heat advection or turbulent fluxes. landlab_export.py:304 passes raw precip, so it has no snow at all, while calibration does use liquid_input. #177 m1 says the same thing but is labelled minor. The Jan 2009 western WA event as a rain-on-snow atmospheric river is well established in the literature, though no source in the repos verifies it.
- **hazard-demands-18** [major] [partially] Discharge hindcasting on gauged basins is the best first consumer for testing the twin physically. It observes the integrated partition at native support (NWIS 15-min), allows held-out basins and events, needs no mechanics or ensemble contract, and directly exercises #172-#175.
  - evidence: calibrate_fluxes.py:35,71 (domain-mean seasonal targets only); issues #199-#202, #59, #224 discharge part
  - issues: Create a deterministic discharge-hindcast issue, or split #201/#202 into a deterministic pilot without #187/#191 blockers, and run it immediately after the water-budget batches.
  - verifier: The calibration targets are domain-mean BFI, Q/P and amplitude (calibrate_fluxes.py:35, :68-75), so it has no basin- or event-level test; that part holds. But the discharge hindcast is already scoped and unheld: #224's discharge part (Dec 2025 AR, 15 NWIS gauges, MRMS) 'can start after #223' and is queued in batch 20, and #59 covers an AR event. A new issue would partly duplicate them. 'Native support NWIS 15-min' also clashes with the twin's daily step and lack of routing (claim 15), so a discharge test needs at least a unit-hydrograph or routing step. 'Best first consumer' is a judgement, not a verified fact.
- **hazard-demands-19** [critical] [partially] The GAIA blocker table chains all flood issues behind the ensemble DA chain (#200<-#187,#191; #201<-#200; #202<-#201), but has no entries for any landslide, liquefaction or Rainier dependency. So #128, #129, #141 and #224 are queued despite prose blockers, and the best physical validation runs last.
  - evidence: scripts/gaia_group_issues.py:86-102; queue_held.txt; issue #224 'Blocked by: #223 ... #128'
  - issues: Add BLOCKED_BY entries: 224:[223,128], 129:[128,137,131], 141:[47,142,143], 130/133:[172,174]. Relax 200/201 for a deterministic pilot.
  - verifier: Confirmed that BLOCKED_BY (gaia_group_issues.py:86-102) has no landslide, liquefaction or Rainier entries, and that #200-#202 are held (queue_held.txt). But in the simulated order, #128 (batch 3) already precedes #223 (15), #224 (20) and #129 (22), and #131/#137 (8) precede #129, so the claimed inversion for #128/#129/#224 is not in run order. It is only unenforced if a prior PR fails or stalls. The real inversion is #141 (24) before #47 (30) and #46 (29). 'Best validation runs last' applies to #202 only; #224's discharge part runs mid-queue.
- **hazard-demands-20** [major] [partially] #128 is a reasonable first agent task only if narrowed to pure FS algebra with an explicitly named pore-pressure closure (hydro_state.py functions) and inputs passed in. As written it asks for a pilot-corridor FS field, a colluvium-depth model, root-cohesion lookup and perched head, none of which exist. A prior GAIA run on #128 aborted after 123 s.
  - evidence: issue #128 body and Aug comment; src/models/hydro_state.py pore_pressure_* functions; docs/gaia-runs/issue-128/20260818T062313Z/dashboard.html
  - issues: Edit #128 acceptance: unit-tested FS(c,c_r,z,beta,phi,u, closure) plus closure metadata. Move corridor and data items to #129/#134.
  - verifier: Confirmed: the #128 body asks for a corridor FS field, root-cohesion lookup and colluvium-depth model. soil_mechanics.py:64 still raises NotImplementedError. The Aug comment proposes naming the closure, and hydro_state.py:209,229 provide the named functions. 'Aborted after 123 s' is not supported. The dashboard shows 123.0 s wall clock alongside 193 turns, $10.06 and 7 agents, and a final result with substantive findings (cos^2 beta trap; LandLab soil__thickness is slope-normal and hardcodes gamma_w/gamma_s=0.5). The orchestrator stalled with nothing committed. That is a stall, not an abort.
- **hazard-demands-21** [major] [confirmed] #130 and #133 are design decisions that overlap #172/#174 (interflow/vadose storage), which GAIA runs in batch 7. Running them in batch 21 risks conflicting state designs.
  - evidence: queue_sim.jsonl batches 7 [175,174,173,172] and 21 [134,133,132,130]; issue bodies #130, #133, #172, #174
  - issues: Hold #130/#133 behind #172/#174 and label them needs-human-decision. Fold #133's convergence into the LandLab adapter decision.
  - verifier: queue_sim batch 7 (0-indexed) is [175,174,173,172] and batch 21 is [134,133,132,130]. #174 adds 'a transient interflow store with hillslope memory'. #130 adds 'a transient shallow interflow/perched store'. #133 routes interflow to convergent cells. These are the same state variable designed three times, and the first design lands 14 batches before the hazard-driven ones.
- **hazard-demands-22** [minor] [not-checked (minor)] #136 (run FuXi on GPU cluster and bias-correct it) and #12 (acceptance requires a contract agreed with the human LandLab/geotech reviewer) cannot be completed by an autonomous code agent.
  - evidence: issue #136 body ('execute FuXi on the cluster'); issue #12 acceptance
  - issues: Exclude #136 and #12 from the queue or label them needs-human-decision.
- **hazard-demands-23** [major] [partially] No issue plans validation of shallow pore pressure or soil moisture against hillslope monitoring, even though USGS Puget Sound landslide monitoring sites (e.g. Mukilteo, about 47.95N, -122.30) fall inside the twin grid. rainier3d's S34 1-D Richards runs (350 sites, Dec 2025 atmospheric river) are an unused physical benchmark for the #131 vadose lag.
  - evidence: pyproj: Mukilteo -> EPSG:5070 (-1955287, 3044946) inside bounds in src/config/domain.py:16; rainier/docs/critical_zone.md:210; grep finds no piezometer-validation issue
  - issues: New issues: (a) hillslope piezometer/VWC validation for #130/#131; (b) compare twin storm lag with rainier3d S34 Richards columns.
  - verifier: Projection confirmed: -122.30, 47.95 maps to (-1955287, 3044946), inside the domain.py:16 bounds. No issue mentions piezometers or Mukilteo (grep of issues.md). The S34 row (critical_zone.md:210) is the Rainier 350-site 1-D Richards run. But it is synthetic, has 'no lateral drainage yet' and no runoff, and sits on Rainier, not on the Puget hillslopes. It is therefore a structural lag comparison, not a physical benchmark. Treating it as validation would compare two unvalidated models.
- **hazard-demands-24** [minor] [not-checked (minor)] Slope, HAND and TWI are average-resampled from 10 m to 90 m, which smooths the steep facets and road cuts where shallow slides start. The recharge export further bilinearly resamples slope and HAND to the forcing grid, so the HAND sink is evaluated on km-scale averaged HAND.
  - evidence: src/features/compute_terrain_domain.py:172-175; landlab_export.py:284-291
  - issues: #135 is valid but needs the hydrology/terrain support mismatch stated. Run the recharge export on the 90 m grid, not the forcing grid.
- **hazard-demands-25** [minor] [not-checked (minor)] The 2001 Nisqually M6.8 earthquake (Feb 28, near seasonal-high water table, with liquefaction in Duwamish and Olympia fill) is the natural liquefaction test event for a dynamic-DTW screen, and no open issue mentions it.
  - evidence: grep of issues.md (no Nisqually 2001 liquefaction validation); issue #141 benchmark only vs WA DNR/Palmer maps
  - issues: Add the 2001 Nisqually liquefaction observations as an event benchmark in #141/#147.

## Verifier: missed problems

- Structural cap on recorded soil moisture: theta is written after drainage, so on a daily step it can never exceed fc+(sat-fc)*exp(-dt/drain_tau). That is 0.391 for fc 0.30/sat 0.45 under any storm (water_budget.py:247-253; verified with 2x500 mm). Any saturation-fraction-driven FS or LandLab wetness built on twin theta is capped below saturation by construction.
- Water table can rise above the ground: wt_depth has no lower clamp (min -0.035 m in a valley probe), and sat-area runoff only stops infiltration. DTW<0 would pass into liquefaction or FS inputs.
- landlab_export.load_recharge_field runs the budget on the coarse forcing grid with bilinearly sampled slope, HAND and d0 (landlab_export.py:284-291). f_lat and the HAND anchor are therefore evaluated at sampled points that are not the failure cells. Missing d0 is filled with 5 m, which forces every cell with HAND<5 m into the no-sink saturating state.
- Export and calibration disagree: calibration uses liquid_input with snow (calibrate_fluxes.py:63-66), but the export passes raw precip (landlab_export.py:304). The 'v0.4-calibrated' banner on the recharge field is therefore not the calibrated configuration even with daily forcing.
- FS conventions the prior GAIA #128 run found but the lens dropped: h_w as vertical saturated thickness vs piezometric head (1/cos^2 beta error, 33% at 30 deg). LandLab soil__thickness is slope-normal, so vertical z under-counts cohesion by cos(beta). LandLab also hardcodes gamma_w/gamma_s=0.5. All three should be in #128/#138 acceptance (docs/gaia-runs/issue-128/20260818T062313Z/dashboard.html).
- Block CV uses only about 121 test wells across 5 folds, with two folds identical, so the 18.5 m RMSE has very wide uncertainty. Its standard deviation of 2.4 m is understated because folds 0 and 4 are duplicates.
- Queue ordering puts #141 (batch 24) before #46 (29) and #47 (30), so the liquefaction MVP runs before skill is measured. BLOCKED_BY should list 141:[47,46], not just 142/143.
- #224 also depends on #128 producing soil_mechanics_fs_90m.tif / _pfail_90m.tif, which #224 itself says have no producer. #128's acceptance does not require writing those products, so the #224 landslide part has no defined input contract.
