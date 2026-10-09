# Issue family: landslide-flood

The landslide-flood family has 15 issues: 2 epics (#127, #199), 10 landslide work items (#128-#136, #138), the old LandLab bridge #12, and the flood chain #200-#202. The two most important problems are in the physics.

(1) The landslide epic #127 and #128 apply the infinite-slope FS to both "fall shallow" and "spring deep-seated" failures. Infinite slope is only valid where z/L << 1 (soil depth much smaller than slope length). Deep-seated slides (10^2-10^3 m per #135; S24 median failure depth 14.6 m per #224) need limit-equilibrium/3-D methods such as Scoops3D, or an explicit non-claim. The 2026-09-10 roadmap review R7 says the same: separate the shallow pilot from deep-seated claims.

(2) The LandLab component is mis-described. LandslideProbability does not ingest water_table__depth. It builds its own steady-state wetness from recharge, T, specific contributing area and slope (followup review 2026-09-10 lines 60-67, science review S9). Yet docs/twin/07-hazard-integration.qmd:59 still says it "takes water_table__depth". The recharge that landlab_export.py:311 ships is also the wrong flux for LandLab's R. It is wb.recharge_mm, which is drainage minus interflow (water_budget.py:248-249). LandLab's R is lateral recharge to the perched layer, so it should be closer to the total drainage leaving the root zone. With K_ANISO=2 and tanB=0.5, f_lat=0.5, so the shipped R is about 2x too low.

State on origin/main (435445f):
- soil_mechanics.estimate_mechanics still raises NotImplementedError (src/models/soil_mechanics.py:56-71). Its contract there is Vs30/dv/v stiffness for liquefaction, not FS.
- No FS code exists anywhere. landlab is not a pixi dependency (pixi.toml has only the landlab-export task at :209-210).
- No landslide-inventory or MTBS fetcher exists.
- Pore-pressure closures exist as separate named functions (src/models/hydro_state.py:209, :229).
- #126 is closed: landlab_export now calls the calibrated slope/HAND budget (src/io/landlab_export.py:260-307). The #127 body text citing :265 is stale.

Flood chain:
- The physics framing is sound: the twin exports source terms, not inundation.
- #201's candidate list is wrong. FlowAccumulator is steady accumulation with no travel time. HAND/SRC is an inundation-mapping step, not routing. OverlandFlow is 2-D shallow-water and too costly at basin scale. A channel-routing component (Muskingum-Cunge / t-route / RAPID / mizuRoute on NHDPlus HR) is missing.
- #202 leans on D7 calibration numbers (BFI 0.52/0.47, Q/P 0.71) that were fitted on the same gauges.

Overlaps flagged by the Sept 10 roadmap review and still not consolidated:
- #130/#133/#174/#173/#131: the perched/interflow store, split across two milestones.
- #71/#136: the FuXi run plus bias correction.
- #134 vs #121/#122: post-fire perturbation. The bodies of #121-#124 are shifted, so #134's "coordinate with #122" points at the wrong body.

None of this family carries needs-human-decision, but #12, #129, #135 and #136 need human or compute decisions (corridor, inventory, lidar, GPU allocation).

**Queue ordering:** The simulation (queue_sim.jsonl) orders this family as follows:
- Batch 3: [128] alone, because P0 runs first globally. That puts it ahead of the water-budget foundations (batches 6-8) and of #187.
- Batch 11: #12, grouped with the v0.2 hydrogeology issues (#14, #10, #9).
- Batch 20: [224, 138, 136, 135].
- Batch 21: [134, 133, 132, 130].
- Batch 22: [129].
- Held: #200-#202, via BLOCKED_BY 200:[187,191], 201:[200], 202:[201] (queue_held.txt). The epics #127/#199 are excluded (gaia_group_issues.py:178).

What is wrong:
1. Hold-back only looks at BLOCKED_BY and open issues at grouping time. #129 (needs #128 and #135) and #224 (needs #223 and #128, per its own body) carry no BLOCKED_BY entries, so they are dispatched in the same run as their prerequisites, before any of those PRs merge. Agents would build inventory scoring on an FS that does not exist. Add {129:[128,135], 224:[223,128], 133:[130], 134:[128]}.
2. Batch 21 sends four agents into the same function, coupled_water_budget (#130, #133, #132 directly; #134's Ks multiplier through it), in parallel. Merge conflicts are near-certain, and #130/#133 compete with #174/#173/#131 from batches 6-8 for the same perched/interflow store. Move #130/#133/#132 to the Water budget milestone and chain them after #174, or consolidate them as the 2026-09-10 roadmap review recommends (#130/#133/#174; #87/#131/#172).
3. Batch 20 is incoherent: a GPU forecast run (#136), a terrain/lidar job (#135), Rainier event hindcasts (#224), and a grab-bag (#138). #136 cannot run autonomously (GPU on Hyak), and it duplicates #71, which lives in v0.7.
4. The grouper has no needs-human-decision or epic-blocker logic beyond skipping 'epic'. #12 (cross-team agreement), #129 (corridor and inventory choice), #135 (corridor and lidar) and #136 (compute) need a hold label that the script honors. The script does not check needs-human-decision at all: #186 is dispatched in batch 2 despite carrying that label.
5. The flood chain is correctly held, but its encoding is off. 200:[187,191] omits #193, which the epic claims; and per the dependency review, the #200 schema needs only #187. Split #200 so the schema can proceed.
6. P0 on #128 is acceptable only if #128 is narrowed to the FS kernel and closure tests. As written, it asks for a corridor FS field with invented c_r/z/h_w inputs, ahead of the #137 specific-yield fix that sets h_w.

## #127 [epic] LandLab landslide handoff — from hydrology to a factor-of-safety
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: []
- physics: The FS expression is the standard infinite-slope form with slope-parallel seepage when z and h_w are vertical heights: [c'+c_r+(gamma_sat z - gamma_w h_w)cos^2B tanphi']/(gamma_sat z sinB cosB). Using gamma_sat for the whole column overweights the unsaturated part (moist unit weight is about 10-15% lower). This is a minor, conservative-ish approximation; it should be stated. The serious error is applying infinite slope to SPRING DEEP-SEATED failures driven by a seasonal-high table. Infinite slope needs z/L << 1. Deep-seated slides (S24 median depth 14.6 m, #224; 10^2-10^3 m per #135) need limit-equilibrium/3-D analysis or an explicit exclusion. The claim that it 'needs no new field data' is false: inventory scoring (#129) needs an inventory, and c_r/z need literature priors.
- problems:
  - Body is stale: it says landlab_export.py:265 calls coupled_water_budget without slope_tan/hand_m/dt_days, but #126 is closed and src/io/landlab_export.py:260-307 now runs the calibrated configuration.
  - Sub-issue list still includes closed #126 and the moved #131/#137, and omits #224 (the S24 Rainier ROC/AUC that is the most concrete validation available).
  - The MVP covers deep-seated failures with an infinite-slope model, which the 2026-09-10 roadmap review R7 explicitly says to separate.
  - It conflates its own FS (#128) with LandLab LandslideProbability (#129). LandLab derives wetness from recharge/T/a/sinB (followup review lines 60-67), so the twin's h_w cannot drive it without an adapter or bypass decision.
  - Pore-pressure-closure comment (2026-08-20) is not yet folded into the body/children.
- proposed edit: Rewrite the body:
- Drop the stale #126 sentence.
- Scope the MVP to SHALLOW (z <= ~2-3 m colluvium) infinite-slope failures only, with an explicit non-claim for deep-seated failures (or a new child issue; see gaps).
- State the adapter decision as an explicit fork: twin-computed FS from twin h_w (#128), versus LandLab LandslideProbability fed R = total root-zone drainage (rech+interflow) with its own TOPMODEL wetness. Mark this needs-human-decision.
- Update the child list: remove #126/#131/#137, add #224 and the new gap issues.
- Fold in the closure comment.

## #128 Implement soil_mechanics: infinite-slope factor-of-safety + pore pressure (the MVP mechanics)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: []
- physics: The algebra is textbook and correct for shallow translational failures. The pore-pressure closure matters: slope-parallel u = gamma_w h_w cos^2B is 25% below hydrostatic at 30 degrees, and hydro_state.py:209/229 already gives both closures as named functions. Several things are physically underspecified. (a) 'Saturation -> h_w' for fall failures has no physical conversion: root-zone theta/theta_s says nothing about positive pressure head. The budget has no perched head until #130/#133, so the MVP can only use h_w = max(z - DTW, 0) from the regional table, and that is near zero on most hillslopes (median DTW metres to tens of metres). The FS 'response to wetting' will therefore be weak, and the run must report that as a result, not hide it. (b) The z-vs-h convention must be pinned: LandLab uses slope-normal thickness h = z cosB. A unit test should show agreement with LandLab's dimensionless form FS = [C/(h rho_s g) + cosB(1 - r R_w)tanphi]/sinB.
- problems:
  - The target function is wrong: estimate_mechanics (soil_mechanics.py:56-71) is a Vs30/dv/v stiffness contract for liquefaction twins. Implementing FS inside it breaks or overloads that contract. FS belongs in a new function or module.
  - Parameter ownership duplicates #134: both ask for a c_r land-cover lookup and a soil-depth model.
  - 'FS field on the pilot corridor' has no corridor named, no h_w source, and no data; agents will invent them.
  - The 'per-cell uncertainty companion' is undefined (first-order delta method? MC from which input sigmas?). #193 will later replace it with member evaluation.
  - The 2026-08-20 closure-metadata acceptance comment is not in the body (roadmap review R7 flags this).
  - P0 puts it alone in batch 3, ahead of the water-budget foundations. That is fine only if scope is algebra plus closures.
- proposed edit: Retitle it 'Infinite-slope FS kernel + named pore-pressure closures (shallow only)'.

Scope:
- New function infinite_slope_fs(slope, z_or_h, c_eff, phi, gamma_moist, gamma_sat, h_w, closure={'hydrostatic','slope_parallel'}) in a new src/models/slope_stability.py.
- Leave estimate_mechanics untouched.
- Parameters are injected; #134 owns the fields.

Acceptance:
- Unit tests: dry FS = c/(gamma z sinB cosB) + tanphi/tanB; flat-slope limit; saturated limit; monotone decrease in h_w.
- The two closures differ by a factor cos^2B in u, tested at 30 degrees.
- Numeric agreement with LandLab's normal-thickness form to 1e-6.
- The closure is recorded in output metadata.
- Analytic first-order sigma_FS from input sigmas.

Move the corridor run to #129.

## #129 Run LandLab LandslideProbability end-to-end on a pilot corridor and score vs a landslide inventory
- verdict: **hold-human** (verifier upheld); agent_ready: False; missing blockers: [128, 135, 134]
- physics: Scoring against an inventory is the right validation, and POD/FAR/AUC is appropriate. LandslideProbability is a steady-state, recharge-driven Monte Carlo model; it does not ingest the twin's transient head (followup review lines 60-67). Feeding it the exported recharge_mm is physically inconsistent: that flux excludes interflow (water_budget.py:248-249), while LandLab's R is recharge to the perched layer, so R is underestimated by about (1 - f_lat), roughly 2x at tanB=0.5. 'Timing AND location for both fall shallow and spring deep-seated' is not achievable: most WA DNR inventory polygons are undated, and deep-seated features are outside infinite-slope validity. A slope-only baseline is mandatory, because event slides sit at median 27.9 degrees vs 18.5 degrees for the box (#224), so slope alone gives a high AUC.
- problems:
  - No BLOCKED_BY on #128 (roadmap review: '#129's end-to-end landslide score needs #128 and suitable terrain/head inputs'), so it is dispatched in the same run as #128.
  - landlab is not in pixi.toml; no inventory fetcher exists; no corridor is chosen.
  - It duplicates #224's landslide part (S24, 351 dated Jan-2009 slides in the Rainier box), which is the one dated inventory available.
  - It has no negative control or baseline (slope-only, rainfall-threshold such as the USGS Seattle cumulative-precip threshold), so AUC alone is uninformative.
  - It runs on the 90 m grid unless #135 lands first. The review says #135's fine-slope contract must precede shallow-failure validation.
- proposed edit: Hold for human decisions: pilot corridor, inventory (S24 Rainier vs WA DNR lidar inventory), and the LandLab-vs-own-FS adapter path.

Then rewrite:
- Shallow-only event hindcast (Jan 2009 S24, merging #224's landslide part into this issue or making #224 the vehicle).
- Report AUC/POD/FAR against two baselines (slope-only; rainfall threshold), plus a time-shifted-forcing control.
- If LandLab is used, R = rech + interflow (the adapter documented).
- Add landlab pinned to an exact version.
- Encode BLOCKED_BY {129: [128, 135]}.

## #130 Two subsurface stores (shallow perched + deep GWL) for fall-shallow vs spring-deep regimes
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [174, 137]
- physics: Correct and important. water_budget.py carries one head with HAND recession (:266-279) and drains interflow instantaneously (:248-249), so it has no perched water body. The 2026-08-20 comment correctly calls for three distinct water bodies (perched/transient, regional phreatic, confined head) with different observation semantics. The perched store is essentially unobserved by NWIS wells, so its parameters are prior-dominated, and the acceptance test can only be synthetic behavioral plus mass balance. Any added store changes Q/P and BFI, so it forces re-calibration against #98/#137.
- problems:
  - It overlaps #174 (interflow store), #173 (fillable deficit) and #131 (vadose lag), all in the Water budget milestone (batches 6-8). This issue sits in the landslide milestone (batch 21), so two agents will build competing perched/interflow stores in coupled_water_budget.
  - Batch 21 = [134,133,132,130] puts four agents in the same function, coupled_water_budget, at once, which guarantees conflicts.
  - It changes the state vector while the #187 canonical contract is still held; the contract should name the store.
  - Acceptance does not require mass-balance closure, Q/P/BFI re-closure, or a statement of which observation constrains the shallow store.
- proposed edit: Move it to milestone 'Water budget: vadose-zone physics & calibration' and make it THE shared perched/interflow store, absorbing #174's store task.

Acceptance:
- Ledger closes to 1e-6 mm.
- Synthetic fall storm: perched head peaks within days while the regional table lags by weeks.
- Q/P and BFI re-closed on held-out basins (#137).
- The issue records that the perched store is unconstrained by NWIS.
- Name the store in the #187 contract.

Encode BLOCKED_BY {130: [174]} or merge #174 into it.

## #132 Sub-daily rainfall intensity for Hortonian / post-fire triggering
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [89]
- physics: The motivating arithmetic is right: 68 mm/day = 2.8 mm/h. But the requested remedy is physically insufficient on three counts. (1) The budget has no infiltration-capacity term at all. Runoff is only saturation-area and root-zone excess (water_budget.py:229-237), and Ksat is computed but unused (#177 m3). Sub-daily forcing alone cannot produce Hortonian runoff; a Green-Ampt/Philip capacity is needed. (2) In unburned PNW forest soils Ksat (roughly 10-100+ mm/h) exceeds even hourly AR intensities (about 5-20 mm/h). The rainier3d 1-D Richards run with MRMS 1 h QPE produced no runoff for the Dec 2025 AR (rainier3d_map.md:5). Hortonian triggering is relevant mainly on burned, compacted or road surfaces. (3) Post-fire debris-flow thresholds use 15-30 min peak intensity (I15/I30). FuXi 6-hourly accumulations smooth those peaks by about 24x in time, so '>=6-hourly' does not reach the regime the issue names.
- problems:
  - It duplicates #57 (daily/hourly bucket re-derivation; notes FuXi 6-hourly is discarded).
  - It is mis-milestoned: this is water-budget/forcing physics, not landslide handoff.
  - The acceptance test is satisfiable trivially by any intensity-dependent runoff rule and says nothing about PNW realism.
  - It does not specify a sub-daily hindcast source: MRMS 1 h exists in rainier3d S29 (#224), while FuXi sub-daily is forecast-only and unrun (#136).
- proposed edit: Merge into #57 or rewrite.

Scope:
- Add a Green-Ampt infiltration capacity using the existing Ksat (and the post-fire Ks multiplier from #134/#122).
- Run dt_days <= 1/24 on the triggering path, with MRMS hourly for hindcast.

Acceptance:
(a) Unburned forest cells produce no infiltration excess for the Dec 2025 AR (consistent with the rainier3d Richards result).
(b) A burned cell with Ks x 0.1-0.3 does produce it.
(c) The ledger closes.

State explicitly that I15 is out of reach of the forcing products.

## #133 Downslope-convergent interflow delivered as positive pore pressure, not a stream sink
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [130, 174]
- physics: The physics diagnosis is correct and is the central shallow-landslide mechanism (Montgomery & Dietrich 1994; Iverson 2000). water_budget.py:248-249 removes interflow from the column, and it never loads a downslope cell. However, convergent hollows are 10-50 m wide (07b-resolution-requirements.qmd:33), so 90 m D8 accumulation largely smooths them out. The perched head that matters lives at <=10 m and needs a downscaling step such as TOPMODEL/SHALSTAB wetness from 10 m specific contributing area. The column model is also vectorized per cell with no lateral graph, so this is an architectural change: a topologically ordered cell loop or a steady-state wetness approximation.
- problems:
  - It depends on #130's perched store (it converts convergence into 'a perched head') but is batched simultaneously with #130 (batch 21).
  - Double-counting risk: once interflow is delivered downslope, the exported Q/interflow source term (#200) and the Q/P 0.71 calibration both change (roadmap review R7: 'the same transferred water is not also counted as outlet discharge').
  - Acceptance has no conservation check, no resolution statement, and no observational check (it is synthetic only).
  - Overlap with #174 and with #138 m3 (hillslope source areas).
- proposed edit: Keep it as phase 2 of the #130 store with BLOCKED_BY {133: [130]}.

Specify: a steady-state or kinematic lateral delivery on the 90 m D8 graph, plus a 10 m TOPMODEL wetness downscaler for FS on #135 corridors.

Acceptance:
- Basin ledger closes (interflow delivered + exfiltrated = interflow generated).
- Q/P re-closed.
- Synthetic convergent hollow shows higher h_w/z than the planar slope for the same storm.
- The 90 m vs 10 m limitation is documented.

Fold in #138 m3.

## #134 Root cohesion, colluvium thickness, and post-fire (Ks/cohesion) states for landslides
- verdict: **split** (verifier upheld); agent_ready: False; missing blockers: [128, 121]
- physics: c_r and colluvium thickness H are necessary FS inputs. Literature priors exist: c_r about 2-25 kPa in PNW conifer forests and about 1-7 kPa in clearcuts (Schmidt et al. 2001); H from soil-production/slope models, or SOLUS depth. Note that SOLUS is capped at 2 m (#224 caveat), which matters for anything deeper. The post-fire acceptance is physically wrong on timing and mechanism. (1) Root reinforcement does not drop at the fire and recover over 3 yr. Roots of killed trees decay over years while regrowth lags, so c_r reaches its MINIMUM about 3-10+ years after stand death (Sidle 1992 decay/regrowth model). (2) The 1-3 yr post-fire debris-flow hazard is dominantly RUNOFF-generated (reduced infiltration, sediment bulking; USGS Staley et al. 2017 M1 model with I15, dNBR and soil erodibility), not infinite-slope shallow failure. Reduced Ks actually lowers infiltration and pore pressure, which can RAISE FS in year 1. So 'a burn perimeter lowers FS and recovers over ~3 yr' tests the wrong hazard model.
- problems:
  - The c_r/H lookup duplicates #128's 'root cohesion c_r (land-cover lookup) ... colluvium thickness z (slope-dependent soil-depth model)'.
  - The post-fire part duplicates #121/#122. Their bodies are shifted (2026-09-10 roadmap review: #121 holds the disturbance body, #124/#125 duplicate), so 'coordinate with #122' points at the wrong body.
  - No MTBS/burn-perimeter fetcher exists in src.
  - The acceptance encodes wrong recovery physics.
- proposed edit: Split it in two.

(A) 'FS strength/geometry parameter fields', agent-ready:
- c_r from NLCD/LANDFIRE with literature ranges and a sigma.
- H from a published slope-dependent soil-depth model, cross-checked against SOLUS, with the 2 m cap flagged.
- Acceptance: fields on grid with priors cited and sigma; values within literature ranges.

(B) 'Post-fire hazard pathway', after #121's body is fixed:
- Ks multiplier with 2-4 yr recovery feeding #132's infiltration capacity.
- c_r decay/regrowth curve with its minimum around 5-10 yr.
- The post-fire debris-flow probability via the Staley 2017 M1 logistic, not FS.
- Acceptance: year-1 runoff increase inside the perimeter; c_r minimum timing matches the decay/regrowth model.

## #135 <=10 m slope + explicit cut-slope layer for shallow failures
- verdict: **hold-human** (verifier upheld); agent_ready: False; missing blockers: []
- physics: The diagnosis is correct. compute_terrain_domain.py:170-176 average-resamples 10 m slope/HAND/TWI to 90 m. Shallow failures need 1-10 m (07b-resolution-requirements.qmd:33). Two corrections. (1) A road cut is typically 3-15 m high and 5-20 m wide in plan, so a 10 m DEM still smooths it; cut faces need 1-3 m lidar (WA DNR lidar / 3DEP 1 m). (2) Cut slopes are height-limited, steep (often >45 degrees) faces where infinite-slope FS is not valid; Culmann/planar-wedge or rock-slope methods apply. So 'FS resolves cut-slope facets' asks infinite slope to do something it physically cannot. Cost: the roughly 100,000 km2 domain at 10 m is about 1e9 cells per layer, so restricting to corridors is necessary, and the corridors are a human choice.
- problems:
  - Corridor definition, road-cut source (WSDOT inventory vs lidar-derived) and lidar acquisition are human/data decisions.
  - The acceptance is qualitative and untestable as written.
  - It mixes a 90 m pore-pressure state with 10 m geometry without a downscaling rule (this ties to #133).
  - Easy partial step not mentioned: slope is already computed at 10 m (compute_terrain_domain.py:151) and could be written out before coarsening, or summarized as sub-grid p90 slope per 90 m cell.
- proposed edit: Human decides the corridors (e.g. I-90 Snoqualmie, US-2, SR-410 for the Rainier box) and the lidar source.

Agent-ready part:
- Write native 10 m slope/curvature/TWI rasters for named corridors.
- Add sub-grid slope quantiles (p50/p90/max) to the 90 m outputs.
- Acceptance: on the S24 inventory, the slope distribution at initiation points from 10 m vs 90 m is shifted by a reported amount (e.g. median delta in degrees).

Move cut-slope stability to a separate issue that uses a planar/wedge method on 1-3 m lidar.

## #136 Run the FuXi forecast engine and orographically bias-correct it
- verdict: **hold-human** (verifier upheld); agent_ready: False; missing blockers: []
- physics: FuXi at 0.25 degrees (about 25 km) cannot resolve Cascade ridge-scale orographic enhancement (ROADMAP:126; 07b:23). Bias-correcting TOTALS against PRISM climatology (quantile mapping by elevation band) fixes the mean-climate bias but cannot recover event-scale spatial structure, which requires the orographic downscaler task in #71. PRISM is itself an interpolated product (gauge-anchored, climatology-aided), and it serves as the bias target, so it cannot also be the independent validation. Deterministic AI precipitation skill beyond about 7-10 days is near climatology for event totals, so '+1..15 d' needs probabilistic lead-time scoring (#195), not just 'a run'.
- problems:
  - It needs a GPU (9.4 GB weights; Hyak Tillicum H200 via deploy/tillicum-fuxi.yaml per ROADMAP:209-210), which an autonomous agent cannot obtain.
  - It duplicates #71 (bias-correct AI QPF against PRISM; orographic downscaler) and #32. Roadmap review recommends unifying #71/#136/#32.
  - Mis-milestoned: it is forcing/forecast (v0.7) work, not landslide handoff. In the queue it is batched with #224/#138/#135, an incoherent batch.
  - The acceptance 'a real forecast run feeding the twin' is not a skill test, and fetch_earth2studio.py:155 aggregates FuXi to daily, discarding the 6-hourly steps #132 wants.
- proposed edit: Merge into #71, move to the v0.7 milestone, and add a needs-compute/needs-human-decision label.

Acceptance:
- Hindcast of at least 10 AR events.
- Elevation-band quantile-mapped totals vs held-out SNOTEL/COOP gauges (not PRISM).
- CRPS/skill vs climatology by lead day.
- Keep the 6-hourly accumulations in the forcing object.

## #138 Minor fixes (LandLab / landslide review)
- verdict: **split** (verifier upheld); agent_ready: False; missing blockers: [30, 64]
- physics: m1 (dv/v -> FS operator): physically weak as stated. Ambient-noise dv/v at 1-10 Hz samples effective stress over a coda footprint of hundreds of metres laterally and tens to hundreds of metres in depth. It cannot resolve failure-plane pore pressure at 1-3 m in a 10-50 m hollow. At best it is a regional wetness covariate, and measured dv/v is not ingested yet (#30). m2: P10 of a monthly DTW series is exceeded in about 10% of months (about 1.2 months/yr). That is a sub-annual typical wet-season state, not a return-period event. Tying it to a return period needs annual-minimum DTW and an extreme-value fit (GEV/Gumbel). m3 is correct and duplicates #133. m4 is a true statement by construction (forecast.py:26-29; root zone d/30 of the Vs30 averaging depth), not a task, and Vs30 is paused (ROADMAP:129-132).
- problems:
  - The roadmap review lists #138 as containing substantive operator requirements under a 'minor/P2' label.
  - Mixed-scope bullets, so no single PR is possible.
  - m4 touches the paused Vs30 lane.
- proposed edit: Close #138 after redistributing its items:
- m1: defer into #19/#30 as a research question, with a footprint-mismatch caveat.
- m2: fold into #64 as 'seasonal-high = annual-minimum DTW with a GEV return level (e.g. 2-yr, 10-yr), requires a >=10 yr daily/monthly DTW series'.
- m3: fold into #133.
- m4: close as documentation-already-present.

## #12 LandLab / geotech bridge: hillslope water table for landslide & road hazard
- verdict: **close-superseded** (verifier upheld); agent_ready: False; missing blockers: []
- physics: The intent (seasonal-high/storm water table plus sigma plus mask to LandLab) was reasonable in July. The premise that LandLab ingests water-table depth is false (science review S9). Most of the contract is implemented: water_table__depth mean and seasonal-high (landlab_export.py:58-67, 196-218), confidence mask (:78-84), sigma sidecars (:120-160), and the paper section #sec-landlab. What remains is cross-team agreement and storm-event validation, which #64/#65/#127/#128/#129 now own.
- problems:
  - Scheduled by the queue in batch 11 (v0.2 milestone with #14/#10/#9). An agent cannot 'agree a contract with the LandLab/geotech reviewer'.
  - Its acceptance encodes the incorrect LandLab input assumption.
  - It overlaps #64/#65 (children of the same PR #63) and the #127 epic.
- proposed edit: Close as superseded by #127 (epic), #64/#65 (export operationalization) and #129 (validation), with a comment listing what was delivered (file:line above).

Move the one open human item, the masked-upland-cell policy agreed with landslide-data-prep, into #127 under needs-human-decision. This also removes it from the agent queue.

## #199 [epic] Flood/inundation handoff — from soil-state source terms to routed discharge
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: []
- physics: The framing is correct: the twin exports antecedent source terms, and routing/inundation is a separate model on a reach network (consistent with the closed #55/#39 and 07b-resolution-requirements.qmd:17-23). Three problems. (1) The candidate list is physically wrong: FlowAccumulator has no travel time or attenuation, and HAND is an inundation-mapping step (it needs reach discharge plus synthetic rating curves), not routing. (2) A daily source term cannot resolve peaks in basins whose time of concentration is under a day; most Cascade headwater basins under about 200 km2 respond within hours. (3) Snowmelt and rain-on-snow (#177 m1) dominate PNW flood antecedents and are missing from the scope.
- problems:
  - It says it is a #193 consumer, but #193 tasks cover only landslide and liquefaction, and BLOCKED_BY[200] omits #193 (roadmap review R7).
  - The probabilistic roadmap's hazard phase omits flood (docs/probabilistic-nowcast-forecast-roadmap.md:303 lists landslides/liquefaction only).
  - There is no channel-routing candidate and no volume-conservation requirement.
- proposed edit: Rewrite the scope:
- Candidates: Muskingum-Cunge / t-route (NWM) / RAPID / mizuRoute on NHDPlus HR for routing; HAND+SRC (OWP FIM) as an optional inundation step.
- Add a cell-to-reach volume-conservation gate.
- Require sub-daily source terms for basins with Tc < 1 d, or restrict claims to daily-mean discharge.
- Add a #193 flood task or decouple explicitly.
- Add flood to the probabilistic roadmap hazard phase.

## #200 Flood: soil-state source-term export contract (runoff/interflow/baseflow + uncertainty, member-preserving)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [193]
- physics: Preserving member identity is correct: independent marginal sampling destroys spatial correlation, which controls basin-integrated tails. The variance of a sum of N correlated cells scales roughly as N^2 rho sigma^2 vs N sigma^2. That regression test is true by construction, so it checks code, not physics. Missing physics: (a) flux ownership. Once #133/#174 deliver interflow downslope, only the interflow that reaches a channel cell may be exported, or water is double-counted (roadmap review R7). (b) Interval integration: the budget is per-step mm (water_budget.py:283), so the export must state the accumulation period and convert to m3/s per cell (mm x 8100 m2 / dt). (c) Baseflow from the HAND recession (:271-281) is groundwater discharge to the nearest drainage; it must map to the reach that drains that cell, not to the cell itself.
- problems:
  - BLOCKED_BY {200: [187, 191]} omits #193, which the epic says it consumes. The dependency review says the schema could start after #187 alone. So the encoding is neither faithful nor minimal.
  - No conservation acceptance (sum of exported volumes = basin budget outflow).
  - Per-cell sigma is redundant once members are carried, and invites the marginal misuse the issue warns against.
- proposed edit: Split it: (A) schema after #187 only; (B) member export after #191/#193.

Acceptance additions:
- Basin ledger: sum of exported runoff+interflow+baseflow volume equals the budget's outlet flux to 1e-6.
- Explicit accumulation interval and units (m3 s-1 per cell or mm per interval).
- Interflow export is defined post-#133.
- Cell-to-reach mapping via the D8 drainage graph is recorded in metadata.

Update BLOCKED_BY accordingly.

## #201 Flood: select and pilot a routing component (LandLab OverlandFlow/FlowAccumulator vs external HAND inundation)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: []
- physics: The candidate set is physically mismatched. FlowAccumulator is a steady flow-accumulation operator (no storage, celerity or attenuation), so it gives no hydrograph timing. OverlandFlow is a 2-D local-inertial shallow-water solver (de Almeida 2012) meant for hillslope/floodplain sheet flow at metre-to-decametre grids, too costly and inappropriate for a basin channel network. HAND-based inundation converts reach discharge to stage and extent via synthetic rating curves; it does not route. A channel-routing scheme (Muskingum-Cunge, kinematic/diffusive wave via t-route or RAPID, mizuRoute) on NHDPlus HR reaches is what produces 'a routed hydrograph'. The 'no downscaling that manufactures information' rule is correct.
- problems:
  - 'Select' is a design decision presented as an agent task.
  - The pilot basin size and time of concentration are not stated, though daily source terms vs basin Tc decide whether peaks are meaningful.
  - No NHDPlus HR fetcher exists; the repo routes only on its own D8 grid (compute_terrain_domain.py:154-161).
- proposed edit: Replace the candidates with: Muskingum-Cunge or t-route/RAPID on NHDPlus HR for routing; OWP HAND-FIM as an optional downstream inundation step.

Agent deliverable: a comparison memo plus a pilot on one #98 gauged basin with Tc > 1 d (state its area).

Acceptance:
- Routed outlet volume equals the source-term volume within 1%.
- Hydrograph timing lag reported against the gauge.
- The routing network is labelled distinct from the 90 m grid in metadata.

A human signs off on the component choice.

## #202 Flood: validate routed discharge against USGS gauge hydrographs (reuse D7 BFI/Q–P calibration, #98)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [137, 191]
- physics: Scoring in observation space by lead time with CRPS/reliability is right. But the 'reuse' numbers (BFI 0.52 vs 0.47, Q/P 0.71, amplitude 1.02 vs 1.06 m) are CALIBRATION fits from #98 on these same gauges. #137 notes the closure is an exactly-determined 3-knob fit, so they carry no validation information, and quoting them in a validation issue invites calibration-as-validation (science review S2). Peak-flow skill is controlled by sub-daily forcing and routing, so daily-mean NSE/KGE should be reported separately from peak timing/magnitude. Inundation-extent observations in this domain are sparse (Sentinel-1 flood maps under forest canopy are unreliable), so the 'document absence' clause will likely be the outcome.
- problems:
  - It cites calibration targets as if they were validation context.
  - It is held out by BLOCKED_BY on #201, but it also needs #191 ensemble members for CRPS and #137's held-out basin protocol.
  - 'Withheld gauge periods' is not defined (which years? frozen before tuning?).
- proposed edit: Remove the D7 numbers from the framing, or label them 'calibration, not evidence'.

Acceptance:
- Score only on held-out basins AND held-out years frozen before any tuning (#137 protocol).
- Report KGE on daily mean, peak-timing error, and annual-peak magnitude bias separately.
- Report CRPS/reliability by lead from #191 members.
- Compare against a persistence/climatology baseline and against NWM retrospective discharge.

## Gaps (proposed new issues)

### Deep-seated landslide stability: explicit non-claim or limit-equilibrium/3-D pathway (Scoops3D) separate from infinite slope
- milestone: Hazard: LandLab landslide handoff; blocked_by: [128, 130]
- why: #127/#128 apply infinite-slope FS to spring deep-seated failures, outside its validity (z/L << 1). S24 median failure depth is 14.6 m (#224). Roadmap review R7 asks to separate the shallow pilot from deep-seated claims.

Either (a) document that the twin's FS covers shallow (<= ~3 m) translational failures only, and remove deep-seated wording from #127, docs/twin/07-hazard-integration.qmd and the ROADMAP; or (b) pilot Scoops3D or 2-D Spencer/Morgenstern-Price on one deep-seated feature, with the seasonal-high phreatic surface (#130's regional store) as the piezometric input. Acceptance: docs carry the scope statement; if (b), FS is compared against an infinite-slope result on the same feature, showing the discrepancy.

### Landslide inventory ingest + frozen holdout protocol (S24 Rainier dated slides, WA DNR lidar inventory)
- milestone: Hazard: LandLab landslide handoff; blocked_by: [223]
- why: #129 and #224 need an inventory, but no fetcher exists in src and no event-dated holdout is defined. Without frozen holdouts, AUC tuning becomes calibration.

Add src/data/fetch_landslide_inventory.py: S24 points/polygons via the #223 adapter, plus the WA DNR landslide inventory (polygons, initiation points where present, dates where present). Assign an event-date confidence and a failure type (shallow/deep/debris flow) per record. Freeze train/holdout splits by event and by watershed before any FS tuning. Acceptance: on-grid layers pass assert_on_grid; the holdout manifest is committed with a hash; the counts per type and per dated event are reported.

### LandLab adapter decision + pin landlab dependency + fix the false API claim in 07-hazard-integration.qmd:59
- milestone: Hazard: LandLab landslide handoff; blocked_by: []
- why: Science review S9 and the followup show LandslideProbability takes recharge, T, contributing area and slope, not water_table__depth. The doc still claims otherwise (07-hazard-integration.qmd:59). The exported recharge excludes interflow (landlab_export.py:311 uses wb.recharge_mm), so it underestimates LandLab's R by about (1 - f_lat).

Human decision (needs-human-decision): which drives FS, the twin's transient h_w (own kernel, #128) or LandLab's steady-state wetness from twin R. If LandLab: export R = rech + interflow (root-zone drainage) per step, add landlab pinned to an exact version in pixi.toml, and add a test that runs LandslideProbability on a 10x10 synthetic grid. Correct 07-hazard-integration.qmd:59-61. Acceptance: the doc matches the component source at a pinned commit; the synthetic run executes in CI.

### Post-fire debris-flow probability via USGS Staley et al. (2017) M1 model (runoff-generated pathway)
- milestone: Hazard: LandLab landslide handoff; blocked_by: [134]
- why: #134's post-fire acceptance tests the wrong mechanism: post-fire debris flows in years 1-3 are mostly runoff-generated and driven by I15. Root-cohesion minimum timing is about 5-10 yr. No MTBS/dNBR ingest exists.

Ingest MTBS perimeters and dNBR. Implement the Staley 2017 M1 logistic likelihood (I15, burned-steep fraction, dNBR, soil KF) per basin, with the twin supplying antecedent soil moisture as a documented covariate extension, not as a recalibration. Acceptance: reproduces published M1 likelihoods for a test basin within the tolerance given in the paper; the twin-antecedent variant is reported separately as exploratory.

### Rainfall-threshold and slope-only baselines for landslide skill (USGS Seattle cumulative threshold, Caine)
- milestone: Hazard: LandLab landslide handoff; blocked_by: []
- why: Slope alone separates event slides (median 27.9 degrees vs box 18.5 degrees, #224). Without baselines, any FS AUC is uninterpretable.

Implement slope-only susceptibility, the USGS Seattle-area cumulative 3-day/15-day precipitation threshold (Chleborad 2006 / Godt 2006), and a time-shifted-forcing control. Acceptance: all are scored on the frozen holdout from the inventory issue, using the same metrics that #129 reports.

### Channel-routing operator on NHDPlus HR (Muskingum-Cunge / t-route) with cell-to-reach volume conservation
- milestone: Hazard: flood / inundation handoff; blocked_by: [200]
- why: None of the #201 candidates route flow: FlowAccumulator has no dynamics and HAND is inundation mapping. Science review S5 says gauges have no state-to-flux operator. Roadmap review R7 requires cell-to-reach volume conservation.

Fetch NHDPlus HR flowlines and catchments for one #98 basin. Map 90 m cells to catchments via the D8 graph. Implement or wrap Muskingum-Cunge. Acceptance: a mass-conservation test (inflow volume = outlet volume + channel storage change, to 1%); an analytic test (a linear reservoir cascade reproduces a known unit hydrograph); a gauge comparison is reported but not used for tuning.

### Extend #193 (joint hazard ensemble) and the probabilistic roadmap to the flood consumer
- milestone: v0.7 — Probabilistic nowcast and ensemble forecast; blocked_by: [191]
- why: #199 claims to be a #193 consumer, but #193's tasks and docs/probabilistic-nowcast-forecast-roadmap.md:303 list only landslide and liquefaction (roadmap review R7).

Add a flood task to #193 (member-wise source terms to routed discharge, P(Q > Q_T)). Add flood to the roadmap hazard phase. Add 193 to BLOCKED_BY[200] or record the decoupling explicitly.

## Verifier extra problems

- S24 inventory depth vs shallow-only scope: rainier3d_paper.md:1037 gives a median failure depth of 14.6 m for the 453 lidar-protocol deposits, and #224 carries the same caveat. The audit makes #127/#129 shallow-only (z <= 2-3 m) and also names S24 as the scoring inventory, without checking that the 351 dated Jan-2009 slides are shallow. Their depth is not documented, and deep deposits must not be used as positives for an infinite-slope colluvium model.
- #128's proposed kernel ignores the existing src/models/hydro_state.py:209-247 named pore-pressure closures (hydrostatic and slope-parallel cos^2 beta), which the 2026-08-20 comment says exist so callers choose a closure explicitly. The agent should reuse them, not reimplement them.
- The LandLab 1e-6 agreement test in #128 is only valid under LandLab's single soil density and relative-wetness formulation. As specified with gamma_moist and gamma_sat it would fail, or tempt an agent to loosen the tolerance, which the gate-integrity check would flag.
- #132's proposed hourly dt inside coupled_water_budget conflicts with the #89 timestep-dependence finding (daily and monthly drain 4.7x differently; the calibration is daily-mode). Specify a separate event-scale infiltration operator, or require recalibration.
- Within-batch execution is sequential on one branch (docs/gaia-automation.md:69), so batch 22 runs [134,133,132,130] with #133 before #130. The ordering, not parallel-agent conflict, is the defect. Cross-batch parallel PRs (gaia-automation.md:299-301) are the real collision channel, for example #174 (batch 8) against #130 (batch 22).
- Several batch numbers in the audit are off by one: #128 is batch 4 (not 3), #130/#132/#133/#134 are batch 22 (not 21), and #12 is batch 12 (not 11).
- landlab_export.load_recharge_field (src/io/landlab_export.py:256-320) is now calibrated, but the field is still on the driver/forcing grid (~4 km), not 90 m, and its sigma is 0.1*|mean| by convention. Any LandLab-R adapter or FS uncertainty claim built on it inherits this, and #127/#129 should state it.
- #200's proposed ledger gate (runoff+interflow+baseflow = outlet flux) is an identity by construction (water_budget.py:33). It should be a water-balance closure: P - AET - dStorage = exported volume.
- #129's proposed BLOCKED_BY omits #134, which its own missing_blockers list includes. #135 is itself hold-human, so blocking #129 on #135 parks it indefinitely, and this should be stated.
