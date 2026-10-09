# Issue family: rainier-slices

The six Rainier slices (#223-#228) all come from the 2026-09-28 rainier3d leverage review. That review exists only on the unmerged branch docs/rainier3d-leverage-2026-09-28 (2c5a0e9, which also adds the ROADMAP order table). An agent working from main cannot read the doc every issue cites. The review was written at rainier3d d827cc3, before rainier3d added its critical-zone columns, Richards solver and unconsolidated_thickness (S33-S35, 6ad0fe7, 2026-10-03).

Four factual premises are wrong or out of date. Each was checked:
(1) 'Its box sits inside the twin domain' (review README:19-24) is false. Projecting the rainier3d UTM box (configs/domain.yaml:9, 553000-623000 E, 5149000-5224000 N) into EPSG:5070 puts 16.5% of it (about 864 km2) south of the twin's y0=2892000 (src/config/domain.py:121). The twin's southern edge runs from 46.53N at -122.19 to 46.65N at -121.56, so Packwood and the Goat Rocks lie outside it. The cone is inside (summit 25 km north of the edge).
(2) products-v1.0.0 does not contain S19 canopy (LAI/GEDI), S30 terrain_geometry or S29 dec2025_ar. The products are model, grids, strain_3d, edifice_load, alteration, mass_movements and gnss (rainier/src/rainier3d/products.json). The gnss zip leaves out daily.parquet (rainier/scripts/20_publish_products.py:158-171). From the next release on, rainier3d drops any third-party field it only resamples (rainier/configs/products.yaml:1-5).
(3) The twin crosswalk does have a lahar entry. data/processed/lithology_crosswalk.json:25 maps "lahar": 0, so lahar is collapsed into 'unconsolidated'. The class is not missing.
(4) The 'S1a/S1b storage work' that #225 waits on is on a branch (work/storage-conservation-2026-09-10) that exists neither on origin nor locally. docs/storage-conservation-contract.md and tests/test_water_budget_conservation.py do not exist on main. The real open blockers are #171/#172.

The physics is mostly well chosen, but several asks would produce numbers that look plausible and are wrong:
- Ice melt fed into the soil bucket, with no lapse-rate temperature downscaling (no lapse correction anywhere in src/).
- GNSS loading computed from a domain-truncated load, with far-field, atmospheric and ocean loads ignored.
- An interception store that does not take its evaporation out of the same PET budget.
- Landslide ROC scored against deep-seated deposits (median depth 14.6 m) with a 2 m soil, infinite-slope model.
- An edifice permeability split (R6a) in a domain the twin masks as out of domain (src/features/hydrogeologic_domains.py:22-24), where no well can constrain it.

Several acceptance checks are calibration targets or conservation-only. Using the August-September discharge at the gauges that DDF_ice gets tuned to is an S2 violation.

**Queue ordering:** How the queue (queue_sim.jsonl, built by gaia_group_issues.py on origin/main) handles this family:
- #227 and #225 are in batch 7 (milestone 'Water budget: vadose-zone physics', bundled into one PR with #176 and #177).
- #226 is in batch 10 ('Applied math', with #170, #169 and #168).
- #223 is in batch 16 (v0.4, with #100).
- #224 is in batch 21 (Hazard, with #138, #136 and #135).
- #228 appears nowhere, because the 'epic' label excludes it (gaia_group_issues.py:177-179). Its R6b/R6c/R6d work, steps 2-3 of the stated Rainier order, therefore never runs.
- None of #223-#228 is in BLOCKED_BY (gaia_group_issues.py:86-102), so the 'Blocked by' lines in the issue bodies are not enforced.

What goes wrong as a result:
- (a) Three consumers of the #223 adapter (#225, #227, #226) run 6-9 batches before it.
- (b) #225 runs one batch before its real blocker #172 (batch 8). Its stated blocker 'S1a/S1b' does not exist as a branch on origin.
- (c) #226 runs while #187 and #189 are held.
- (d) The landslide half of #224 runs after #128 (batch 4) but before #134 (colluvium thickness) and #130 (two stores) in batch 22.
- (e) Every body says 'none ahead of the P0 contracts #187/#198 or the hydrology pilot #189 → #188'. #187 is held behind six issues, so read literally this freezes the whole family for most of the drain, and an agent reading it may stall or refuse. For the adapter and the discharge test this global gate is unnecessary. Replace it with per-issue blockers and remove the sentence from the bodies.
- (f) Two milestone choices place budget-physics work (#227, #225) in the earliest non-P0 milestone, ahead of the domain adapter they depend on. #227 belongs in v0.4 with #100.
- (g) Within a batch, issues come in gh's newest-first order, so moving #227 into the v0.4 batch alone would still put it ahead of #223. A BLOCKED_BY entry is required.
- (h) The grouper never reads 'needs-human-decision'. The R6a hold works only because #228 also carries 'epic'.

Recommended order:
1. #223, rewritten.
2. Lapse-rate downscaling and the basin flux operator (new gaps).
3. R2a discharge.
4. #227, after #172.
5. #225 together with or before the #137 recalibration.
6. R6c, after #46, #21 and #14.
7. R2b, after #128 and #134.
8. #226, after #187, #189 and #172.
9. R6a, human-held.
R6b and R6d move to the rainier3d repo.

## #223 R1: rainier3d sub-domain adapter (release assets → 90 m EPSG:5070)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Sound as a data adapter, but three of its five layer groups are not in products-v1.0.0.
- Available: ice_thickness, alteration, apparent_magnetization, ndvi (model/surface, rainier/configs/products.yaml:12-36) and mass_movements.
- Not available: S19 LAI/GEDI, S30 terrain_geometry. Getting them means running rainier3d's pixi stages s19/s30 with raw inputs, some obtained by hand.

The 'within 2% of 5.50 km3' check is a regridding-conservation test, not a physical one. Because EPSG:5070 is equal-area, area-weighted 'average' resampling should conserve to well under 1%. Bilinear will not conserve it at glacier margins.

The 2% target is also probably wrong as stated:
- 0.18 km3 of the 5.50 is off-cone (rainier/docs/paper/rainier3d_paper.md:240).
- Some of those glaciers (Goat Rocks, about 46.5N) lie south of the twin grid edge (46.65N at -121.56).
- If more than about 0.11 km3 falls outside, a correct adapter fails the check.
- problems:
  - assert_on_grid() requires the FULL domain shape and bounds (src/config/domain.py:150-158, 162-175). A box-only 'sub-domain' raster can never pass. The issue must say: write full-domain rasters, NaN outside the box, plus a coverage mask.
  - Layer list includes S19 LAI/GEDI and S30 terrain geometry, which are not release assets (rainier/src/rainier3d/products.json lists only model, grids, strain_3d, edifice_load, alteration, mass_movements, gnss).
  - Ice-volume target ignores the 16.5% of the rainier3d box that is outside the twin grid. It should compare against the native-grid volume of glacier cells inside the twin footprint, at 1% or better, using area-weighted resampling.
  - S30 slope/relief duplicates the twin's own 90 m terrain stack and would create two inconsistent slope fields. Only bedrock elevation under ice adds information.
  - No resampling rules per variable type are given: categorical uses nearest/mode, alteration intensity uses average, rho_a should be averaged in log10, points/polygons stay vector plus rasterized fraction.
  - Licences: IceBoost v2, RGI and GlaThiDa are still 'to verify' (rainier/docs/data_policy.md:25). The twin re-publishing derived rasters needs a licence check.
  - Next rainier3d release drops resampled third-party fields (rainier/configs/products.yaml:1-5). The adapter must pin products-v1.0.0 by SHA256 and must not follow 'latest'.
  - Acceptance needs an offline fixture-based test; CI cannot download 110 MB of release assets.
  - Cites a review doc that exists only on an unmerged branch.
- proposed edit: Rewrite the layer list to match what products-v1.0.0 actually contains:
- model/surface: ice_thickness, ice_thickness_error (resampled, so v1.0.0 only), alt_a_*, alt_log10_rho_*, alt_doi_*, apparent_magnetization, unconsolidated_thickness, surface_unit.
- mass_movements: events.gpkg, flows.gpkg.
- Move S19, S30 and S29 to a separate 'rebuild-from-rainier3d-stages' follow-up, or drop them.

Require:
- full-domain outputs on DOMAIN.template() with a rainier3d_coverage mask;
- area-weighted average resampling for thickness;
- a SHA256 pin to products-v1.0.0, with source_commit and source_release attributes.

Acceptance:
- (a) pytest on a synthetic 100 m UTM fixture: assert_on_grid passes and volume is conserved to 0.5%;
- (b) a real run reports ice volume inside the twin footprint against the same quantity computed natively, agreeing to 1%, and reports the clipped volume outside the grid;
- (c) a licence note per layer.

Also: add a 'Blocks: 224, 227, 228' line to BLOCKED_BY in scripts/gaia_group_issues.py, and merge the leverage review doc into main.

## #224 R2: event hindcasts on the Rainier box (Dec 2025 AR, Jan 2009 storm + S24 landslides)
- verdict: **split** (verifier upheld); agent_ready: False; missing blockers: [128, 134, 70]
- physics: These are two different deliverables in one issue: an event-scale runoff test, and a landslide-inventory skill test. Both are valuable. Neither can be built honestly with what is on main today.

Discharge part:
- The twin has no state-to-flux or routing operator. Interflow and runoff leave each cell, and accumulate_runoff is not mass-conserving (src/models/water_budget.py:300-311). This is audit S5, which #224 claims to address but does not build.
- The budget runs daily at best, so hourly MRMS timing cannot be scored. At most, event volume, runoff ratio and daily-mean hydrographs can be scored on NLDI basin integrals.
- The 'seismic virtual gauges' are regressions calibrated on NWIS gauges, so they are model products with error, not independent truth.
- PRISM vs MRMS above 3000 m is a comparison between products, and MRMS suffers beam blockage on the cone. Neither is ground truth.
- dec2025_ar.zarr is not a release asset; it needs 'pixi run s29' in rainier3d with network access to MRMS and NWIS.
- rainier3d's own Richards run for this storm produced no runoff, because POLARIS ksat exceeds the rain rate (prior map). That is a useful contrast.

Landslide part:
- Infinite-slope FS from #128 with SOLUS soil capped at 2 m is a shallow-landslide model.
- The S24 lidar-protocol deposits with depth_m have a median depth of 14.6 m, i.e. deep-seated. 1,267 of the 1,650 events are 'complex or unknown' type.
- Only the 351 Jan 2009 events are dated, and only by date; there is no trigger field (rainier/docs/paper/rainier3d_paper.md:1027-1030, 1051).
- Some of the box (south of 46.53-46.65N) is outside the twin grid.
- An infinite-slope FS AUC will be dominated by tan(beta), so beating the slope-only baseline is the only meaningful result. The issue correctly names it as the control.
- problems:
  - Mixed scope: discharge (milestone 'Water budget' or v0.4) and landslide (Hazard) in one issue, in the Hazard milestone. The queue puts it in batch 21 with unrelated #138/#136/#135, BEFORE #134 (colluvium thickness) and #130 (two stores) in batch 22.
  - Not in BLOCKED_BY: the landslide part runs once #128 merges, whatever the state of colluvium thickness (#134) or 2009 hindcast forcing (#70).
  - No gauge flux operator exists, so 'score discharge and runoff-partition timing' is not implementable as written.
  - S29 data is not a rainier3d release asset, so #223 does not supply it. The stated 'Blocked by #223' is the wrong dependency for the discharge part.
  - Duplicates or overlaps #59 (one PNW AR hindcast, wells/theta) and #129 (inventory-scored landslide run). Relationship not stated.
  - Landslide target set not curated: it mixes deep-seated deposits, rock avalanches (median 39.8 deg) and debris-flow runout with shallow slides. Negative-sampling design, spatial blocking and the in-grid restriction are unspecified.
  - Inventory internal inconsistency to resolve: rainier3d paper :1029 says depth_m on 247 events, :1037 says 453 deposits.
  - 'Caveat: median failure depth 14.6 m, below the 2 m SOLUS cap' is ambiguous wording. It means deeper than the modeled soil column, which invalidates infinite-slope FS for those events.
  - Calibration/validation separation (audit S2) not stated: the Dec 2025 gauges must not have been used in #137/#175 calibration.
- proposed edit: Split into two issues.

R2a, discharge (move to milestone 'Water budget' or v0.4):
- Build a basin-integral flux operator: sum of runoff + interflow + baseflow over the NLDI polygons, in m3/s at daily resolution, no routing. This can be its own small issue.
- Score event volume, runoff ratio and daily-mean NSE at the 15 gauges against controls: time-shifted forcing and a climatological runoff-ratio baseline.
- Report PRISM vs MRMS by elevation band as an inter-product difference, not as validation.
- State that the gauges are held out from calibration.
- Link #59 and close it into R2a, or make R2a its Rainier instance.

R2b, landslide (Hazard milestone):
- BLOCKED_BY [128, 134, 223].
- Target set: dated 2009 events, class slide/debris slide, crowns inside the twin grid, excluding depth_m > 3 m.
- Negatives: random non-failure cells within the same slope range and land cover, with spatial block CV.
- Report AUC with a bootstrap CI against the slope-only baseline and a time-shifted-forcing control.
- Pass criterion: the CI lower bound exceeds the slope-only AUC.
- Coordinate with #129 so there is a single landslide-scoring harness.

Add both to BLOCKED_BY.

## #225 R3: canopy interception store from rainier3d LAI/GEDI
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [172, 223]
- physics: Interception is a real, first-order omission for western Washington conifer forest. Literature for Douglas-fir and western hemlock stands, e.g. Link et al. 2004 at Wind River (to verify via the bib registry), puts it at roughly 20-25% of gross rainfall. Adding it will shift the calibrated Ka/R_ref/S_y substantially.

As specified, the issue is physically incomplete:
- Interception evaporation must draw from the same PET as AET. The current AET = min(PET, S - S_wp) would double-count evaporation if E_i is added on top.
- Gash needs storm statistics (mean rain rate, wet-canopy evaporation rate). At the budget's default MONTHLY step (water_budget.py:161, dt_days None) it needs rain-day counts; Rutter needs sub-daily steps.
- PNW conifer snow interception and sublimation is large and is ignored. The store must sit before the rain/snow partition (forecast.py:105-131), or rain-only must be stated explicitly.
- Sentinel-2 LAI saturates around 5-6 in dense conifer.

The data source is wrong for a domain-wide parameter:
- The rainier3d box covers about 22% of the 141 x 170 km twin domain.
- S19 is not a products-v1.0.0 asset.
- Using it would create a parameter discontinuity at the box edge.
- A domain-wide LAI or canopy-cover source is needed (MODIS/VIIRS LAI, or NLCD tree canopy, which the static stack already uses per src/io/landlab_export.py:4). rainier3d LAI/GEDI then serves only as an in-box check.
- problems:
  - Depends on an S1a/S1b branch that does not exist on origin or locally. The referenced docs/storage-conservation-contract.md and tests/test_water_budget_conservation.py are not on main. The real blockers are #172 (and epic #171).
  - Queue places it in batch 7, before #172 (batch 8) and before #223 (batch 16). Both stated dependencies are violated because BLOCKED_BY lacks #225.
  - Bundled into one PR with #227, #176 and #177: two independent budget-physics changes plus hysteresis routing in one diff.
  - Acceptance 'pass with store on and off' tests conservation only, not physical plausibility or effect on calibration.
  - No specification of PET partitioning, timestep or snow interception.
  - A rainier3d-only capacity field is spatially inconsistent across the domain.
  - Adding a 20-25% loss term after calibration (#137/#175) invalidates that calibration. Ordering should put it before or alongside the recalibration, not after.
- proposed edit: Retitle to 'Canopy interception store (domain-wide LAI; rainier3d as in-box check)'. Set BLOCKED_BY [172], and add 223 only if rainier3d LAI is kept.

Spec:
- Daily Gash form with capacity S = f(LAI) (cite the formula), and E_i taken from PET before AET.
- Rain-only, with snow interception stated explicitly as out of scope; or a simple snow-interception term.
- Refuse to run at the monthly step, or use rain-day statistics there.

Acceptance:
- (a) The extended conservation test closes to 1e-9 mm with the store on and off, including E_i as an explicit flux.
- (b) Domain-mean interception loss over forested cells falls in the literature range, which is a plausibility band, not a fit.
- (c) Re-run the #137 calibration and report the change in Ka/R_ref/S_y and in held-out Q/P.

Milestone stays 'Water budget'. Order it before #137.

## #226 R4: GNSS elastic-loading observation operator for total water storage
- verdict: **defer** (verifier upheld); agent_ready: False; missing blockers: [187, 189, 172]
- physics: The right observable for audit S11 (GRACE senses total water storage, not groundwater), and the right confounder to model for dv/v. The truncated-load approach needs four corrections.

(1) Domain truncation. For a uniform load q on an elastic half-space disk, the centre displacement is w0 = 2(1-nu^2) q a / E. With E of about 83 GPa and nu = 0.25, 100 mm of water over a = 87 km (the twin's equivalent radius) gives about 1.9 mm. The Cascades seasonal TWS swing, dominated by SWE, can make the in-domain signal several mm, but loads outside the domain also contribute (load Green's functions decay slowly). Without a far-field complement (GRACE mascons or an LSM outside the domain, on a spherical Earth with Farrell 1972 Green's functions) the amplitude comparison is biased low, so the station-to-station spatial pattern must be compared instead of absolute amplitude.

(2) Atmospheric pressure loading and non-tidal ocean loading (Puget Sound coastal sites), plus GNSS draconitic and thermal artifacts at about 1 mm, must be removed or modeled.

(3) The twin's TWS is not available as a state:
- SWE lives inside forecast.liquid_input, which returns only liquid input and never exposes swe (src/models/forecast.py:116-131).
- The groundwater term S_y*dh uses S_y = 0.30, which is known to be too high (#137).
- Storage is not conserved (#172, audit S1).
A GNSS misfit would therefore be uninterpretable.

(4) Poroelastic aquifer deformation can have the opposite sign to loading in confined units (#50).

Data: rainier3d's gnss product does not include daily.parquet (rainier/scripts/20_publish_products.py:158-171). Vertical series must be fetched directly from UNR tenv3 or PANGA. Excluding the 22 MIDAS-flagged sites is correct, and in addition winter data at snow-affected antennas should be masked.
- problems:
  - Body says 'Blocked by #187 and #189', but BLOCKED_BY lacks 226. The queue dispatches it in batch 10 while #187 and #189 are both held.
  - Also needs #172 (a conserved storage account) and an exposed SWE state. Neither is stated.
  - 'Register in STREAMS' (src/models/observability.py:881) is a design-catalog entry with states limited to gwl/soil_moisture. It is not an operator registration and could be satisfied trivially.
  - Acceptance compares annual amplitude and phase with no tolerance, and ignores far-field, atmospheric and ocean loading, so it is untestable or biased by construction.
  - Data source (rainier3d gnss/daily.parquet) is not in any release asset.
  - 'Coordinate with dvv-coupling-framework analysis/poroelastic_framework.py' points to an external repo the agent cannot see.
  - Milestone 'Applied math: DA estimator correctness' runs early (rank 3 in MILESTONE_ORDER), well before its prerequisites.
- proposed edit: Add 226: [187, 189, 172] to BLOCKED_BY.

Rewrite the scope:
- (a) A pure forward operator with no twin dependence: a load grid gives vertical displacement, using half-space disk and point-load (Farrell) Green's functions.
- (b) Unit tests against the analytic disk-load centre and edge solutions, to 1%.
- (c) A separate validation step that expose SWE plus theta*z_r plus S_y*h as a TWS state, adds a far-field complement and ATML/NTOL corrections, and compares station-pair differential seasonal amplitudes within the domain against UNR/PANGA vertical series. Exclude flagged and snow-affected site-winters; acceptance is a stated tolerance with CI, against a null of a domain-uniform load.

Drop the STREAMS bullet in favour of the #189 record schema. Inline the relevant poroelastic preset rather than pointing at an external repo.

## #227 R5: glacier mask and degree-day ice melt (IceBoost v2)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [223, 172]
- physics: The gap is real: Nisqually, Carbon, White and Puyallup late-summer flow carries glacier melt, plus the storage loss of a negative mass balance. The implementation as specified is physically wrong in five ways.

(1) Degree-day factor. The only DDF in code (3.0 mm/degC/d, forecast.py:58) was fitted to SNOTEL snow at 881-1414 m. Ice DDFs are roughly 2x snow (Hock 2003 range about 6-20 mm/degC/d; to verify). Ice must melt only after the seasonal snowpack on that cell is gone.

(2) Temperature. The forcing is PRISM at 4 km with no lapse-rate downscaling anywhere in src/ (grep 'lapse' gives no forcing hits). A 4 km cell on the cone can sit 1000+ m from the 90 m cell elevation, a 6-7 degC error that dominates any DDF.

(3) Routing. Glacier melt drains supra-, en- and subglacially to the outlet. It should go to runoff, not to liquid_input feeding a SOLUS soil bucket on ice cells (and edifice cells are masked volcanic_deep in the twin's GWL product, src/features/hydrogeologic_domains.py:22-24).

(4) Mass accounting. Ice must be an explicit store (dS_ice < 0) under the storage account (#172), or an external inflow. Otherwise closure is broken.

(5) Debris cover. Debris-covered tongues (Carbon, Emmons, Winthrop) melt less under thick debris (the Ostrem curve).

Validation: August-September discharge at 12082500 and 12092000 is the natural target for tuning DDF_ice, so using it as the check is S2 calibration-as-validation. It is also confounded by the twin's baseflow (BFI) problems. NPS long-term mass balance on Nisqually and Emmons glaciers is an independent melt-rate check (verify availability). The IceBoost-vs-GlaThiDa thickness caveat barely matters for melt over a season; it matters for multi-decadal ice depletion.
- problems:
  - Queue batch 7, before #223 (batch 16), which supplies the mask. Body says 'Blocked by #223'; BLOCKED_BY lacks 227.
  - Milestone 'Water budget: vadose-zone physics' is the wrong home. It bundles the work into one PR with #225, #176 and #177. The natural home is v0.4 next to #100 (snow is the water-table clock).
  - No temperature downscaling is specified, and none exists on main.
  - No ice DDF, snow-on-ice precedence, routing destination or ice store is specified.
  - Acceptance uses calibration gauges as validation, with no tolerance.
  - No basin-integral flux operator exists to compare with gauges (the same gap as #224 discharge).
  - 16.5% of the rainier3d box, including some off-cone glaciers (Goat Rocks), is outside the twin grid. The 219-glacier count does not apply in-domain.
- proposed edit: Set BLOCKED_BY [223, 172]. Move to milestone v0.4.

Spec:
- Lapse-rate downscaling of PRISM tmean to the 90 m DEM (a new prerequisite issue).
- A separate DDF_ice greater than DDF_snow, with melt only where SWE == 0 and ice_thickness > 0.
- Melt routed to the runoff flux, not to infiltration.
- An explicit ice store, debited, under the conservation test.
- A debris-cover reduction flag, or the omission stated explicitly.

Acceptance:
- (a) The conservation test with the ice store closes.
- (b) DDF_ice is calibrated on one set of years and validated on held-out years against NPS glacier mass balance, plus August-September flow at 12082500/12092000 via the basin-integral operator, with a stated tolerance.
- (c) Glacier-melt fraction of August-September flow is reported, alongside literature values (e.g. Frans et al. 2018, to verify).

## #228 R6: hydrothermal alteration as a control on water pathways (edifice and lowland lahar cap)
- verdict: **split** (verifier upheld); agent_ready: False; missing blockers: [223, 46, 21, 14]
- physics: R6c (lahar cap) is the only sub-slice that is both twin-relevant and testable. The Osceola Mudflow is a clay-rich cohesive lahar covering the Enumclaw plateau and the White/Puyallup valley floors inside the twin domain, and a confining-cap hypothesis is plausible (Vallance & Scott 1997; USGS Puget lowland framework; to verify). Testing it needs:
- aquifer-screened wells (#46): wells on the plateau are mostly screened below the cap, so without screening, a residual on the cap measures confined head and not the cap effect;
- a complete DNR crosswalk (#21). The crosswalk already maps 'lahar' to class 0 (data/processed/lithology_crosswalk.json:25), so this is a class split, not a new term;
- the lithology raster without the Puget lowland coverage gap (#14).

R6b (clay vs water from rho_a plus magnetization):
- Depth supports are mismatched. Skin depth is delta = 503*sqrt(rho/f), about 28 m at 100 ohm-m and 88 m at 1000 ohm-m for 33 kHz, while apparent magnetization integrates hundreds of metres or more.
- Thick unconsolidated valley fill reads low-mag and so classifies as 'altered'.
- The verification ('wet-unaltered concentrates on moraine/valley fill') restates the expectation.

R6d (failure density in altered vs fresh cells):
- Power is limited: 126 km2 of surveyed edifice, few S24 events inside it.
- Matching on slope and relief alone leaves elevation, distance-to-ice and debuttressing as confounders.
- The a >= 0.5 thresholds are m1_placeholder.
- A north-south-flipped grid keeps autocorrelation (reasonable), but a toroidal or random-shift ensemble gives a proper null.

R6a (edifice K split):
- The twin masks volcanic_deep as out of domain (hydrogeologic_domains.py:22-24) and has no wells there, so log10 K = log10 K_fresh - delta*a is unidentifiable.
- It can only show up in gauge runoff partition, which needs the #224 operator.
- The hold for a hydrogeologist is correct.

R6b and R6d use no twin state; they are rainier3d science questions.
- problems:
  - Labelled 'epic', so gaia_group_issues.py:177-179 excludes it entirely. R6b/R6c/R6d, steps 2-3 of the stated Rainier order, have no child issues and will never be dispatched.
  - The 'needs-human-decision' label has no effect in the grouper (the script never reads it). The hold works here only because 'epic' excludes the issue. If the epic label were removed to make it dispatchable, R6a would be dispatched despite the human gate.
  - Premise 'The twin crosswalk has no lahar class today' is inaccurate. 'lahar' maps to class 0 (lithology_crosswalk.json:25) and is lumped with alluvium and till.
  - R6c depends on #46, #21 and #14 (Enumclaw plateau lies in the Puget lowland coverage gap of #14). Only 'links #46, #50' is stated.
  - R6b/R6d belong in the rainier3d repo. They produce no twin state and cost the twin queue nothing only because the epic is excluded.
  - R6c acceptance lacks a decision rule: what difference in residuals, with what CI and sample size, promotes the cap to a hydrogeologic domain?
  - Hydrothermal discharge (R6e) is a deep inflow probably below budget resolution. Deferral is correct.
  - Milestone v0.2 plus labels stage-1/stage-2/geotech/P1 mixes tracker and work semantics.
- proposed edit: Keep #228 as an epic tracker, but rewrite its first line to reflect that 'lahar' is currently lumped into unconsolidated.

Create child issues:
- R6c (twin repo, milestone v0.2, BLOCKED_BY [223, 46, 21, 14]): split 'lahar' out of class 0 in the crosswalk, with a cap mask from DNR Qvl plus rainier3d flows.gpkg. Compare Stage-1 residuals and Stage-2 amplitudes on vs off the cap, using aquifer-screened wells only and matching on HAND, slope and screen depth. Report the effect with a bootstrap CI against a random-shift polygon ensemble (at least 200 shifts). Pre-state the promote-to-domain threshold.
- R6b and R6d: file them in Denolle-Lab/mt-rainier-digital-model, using random-shift nulls and adding elevation and distance-to-ice to the R6d matching.
- R6a: hold-human (needs-human-decision). Only open it after the R6b/R6d outcomes AND the R2a gauge operator, because gauge partition is its only observable.

Separately, make gaia_group_issues.py skip 'needs-human-decision' issues explicitly.

## Gaps (proposed new issues)

### Encode the Rainier-slice dependencies in BLOCKED_BY
- milestone: Software: CI, tests, reproducibility, scale; blocked_by: []
- why: None of #223-#228 is in BLOCKED_BY (scripts/gaia_group_issues.py:86-102). In queue_sim.jsonl, #227 and #225 run in batch 7 and #226 in batch 10. All three come before their prerequisite #223 (batch 16). #225 also runs before #172 (batch 8), and #226 runs while #187 and #189 are held (queue_held.txt).

Add to BLOCKED_BY:
- 224: [128, 134, 223], or the split R2a [] / R2b [128, 134, 223];
- 225: [172];
- 226: [187, 189, 172];
- 227: [223, 172];
- new R6c: [223, 46, 21, 14].
Also make the grouper skip issues labelled needs-human-decision and log them, the same way it logs held-back issues.

Acceptance:
- the grouper's stderr lists #224-#227 as held while their blockers are open;
- a unit test feeds a fixture issue labelled needs-human-decision and checks it is excluded.

### Merge the rainier3d leverage review and its ROADMAP order table into main
- milestone: v0.4 — Domain extension: western Cascades (gauged-basin coverage); blocked_by: []
- why: Every issue in this family cites docs/reviews/2026-09-28-rainier3d-leverage/README.md 'on branch docs/rainier3d-leverage-2026-09-28 (2c5a0e9)', which is not on main. GAIA agents work from main and will not see it. The review also needs four factual corrections first.

Merge 2c5a0e9, with these corrections to the review:
- (1) The rainier3d box is not fully inside the twin grid: 16.5%, about 864 km2, lies south of the twin's y0=2892000 (46.53-46.65N).
- (2) S19, S30 and S29 are not products-v1.0.0 assets, and gnss daily.parquet is not packaged.
- (3) The crosswalk maps lahar to unconsolidated (lithology_crosswalk.json:25).
- (4) The S1a/S1b storage branch does not exist on origin; point to #171/#172 instead.
- (5) Add a note that rainier3d S33-S35 (CZ columns, unconsolidated_thickness, Richards) postdate the review and bear on #134 and #224.

### Basin-integral gauge flux operator (no routing) for event and seasonal discharge scoring
- milestone: Applied math: DA estimator correctness; blocked_by: []
- why: Audit S5. #224 (discharge), #227 (August-September melt) and the gauge parts of the calibration all compare cell fluxes to USGS discharge. The twin has no state-to-flux operator, and accumulate_runoff is not mass-conserving (src/models/water_budget.py:300-311). The routing pilot #201 is held behind #200, #187 and #191.

Write H_Q: sum the runoff + interflow + baseflow fluxes over each NLDI basin polygon on the 90 m equal-area grid and return m3/s at daily or longer resolution. Carry the representation error (no routing lag) in R.

Acceptance:
- a synthetic uniform-flux basin returns flux x area exactly;
- a mass-balance test confirms basin sum = domain sum restricted to the basin;
- documented use limits: there is no timing skill below the basin response time.

This is distinct from #201, which adds channel routing.

### Lapse-rate downscaling of PRISM temperature to the 90 m DEM
- milestone: v0.4 — Domain extension: western Cascades (gauged-basin coverage); blocked_by: []
- why: There is no lapse-rate correction anywhere in src/. The degree-day snow model (forecast.py:105-131) and any glacier melt (#227) use 4 km PRISM tmean, which on the Rainier cone can be off by more than 1000 m of elevation, i.e. 6-7 degC. Over the extended v0.4 domain this also biases snow partition and melt-out timing (#100).

Downscale tmean from the PRISM cell-mean elevation to the 90 m DEM with a lapse rate. Fit the rate monthly from PRISM itself, or use about -6.5 K/km with a sensitivity range. Apply it in liquid_input and soil_moisture.snowmelt_liquid_input.

Acceptance:
- SNOTEL SWE melt-out timing error at held-out stations does not get worse;
- report melt-out timing at stations above 1400 m, outside the 881-1414 m calibration range of forecast.py:53;
- a unit test shows a uniform-elevation case is unchanged.

### R6c: lahar-cap hydrogeologic class (Osceola/Electron) with an aquifer-screened residual test
- milestone: v0.2 — Hydrogeologic realism; blocked_by: [223, 46, 21, 14]
- why: #228 is an epic, so R6c is never dispatched. It is the only alteration sub-slice that affects twin outputs, since the Enumclaw plateau and the White/Puyallup valley floors are in the domain and the area is well-dense.

Split 'lahar' out of class 0 in data/processed/lithology_crosswalk.json into a cohesive-lahar class, using DNR Qvl plus rainier3d flows.gpkg (Osceola 79.7 km2, Electron 18.8 km2).

Compare Stage-1 residuals and Stage-2 seasonal amplitudes on vs off the cap:
- aquifer-screened wells only (#46);
- matched on HAND, slope and screen depth;
- bootstrap CI;
- null: an ensemble of at least 200 random polygon shifts.

Pre-register the effect size that would promote the cap to a hydrogeologic domain. Report the well count on the cap. If it is under about 30, stop and say so.

### Domain-wide canopy storage-capacity layer (LAI/canopy cover) on the 90 m grid
- milestone: Water budget: vadose-zone physics & calibration; blocked_by: []
- why: #225 takes capacity from rainier3d S19, which covers about 22% of the twin domain and is not a release asset. A parameter field that exists only inside the Rainier box makes a discontinuity at the box edge.

Stage a domain-wide LAI climatology on DOMAIN.template(), from MODIS/VIIRS LAI or NLCD tree canopy cover with a documented LAI conversion, plus a seasonal cycle for deciduous cells. Validate it against rainier3d S19 LAI/GEDI PAI inside the box: report bias and saturation above LAI 5.

Acceptance:
- assert_on_grid passes;
- in-box comparison statistics are committed.

### Curated shallow-landslide target set from rainier3d S24 for FS/AUC scoring
- milestone: Hazard: LandLab landslide handoff; blocked_by: [223]
- why: S24 mixes deep-seated deposits (median depth 14.6 m), rock and ice avalanches, debris-flow runout and 1,267 'complex/unknown' events. Only 351 are dated, and those only to the January 2009 storm, with no trigger field. Scoring the 2 m infinite-slope FS (#128) against the whole catalogue measures the wrong process.

Build the target set from S24 events: class slide or debris slide, dated January 2009, crown inside the twin grid, depth_m missing or under 3 m, crown on 1 m or 3 m lidar.

Also build:
- a negative-sample protocol: same slope range, excluding deposit and runout polygons;
- spatial block folds.

Resolve the paper's 247-vs-453 depth_m count discrepancy with rainier3d. Shared by #224 R2b and #129.

## Verifier extra problems

- All six issues cite the source as Denolle-Lab/mt-rainier-virtual-3d-model; the repo is now Denolle-Lab/mt-rainier-digital-model (products.json URLs). They also pin commit d827cc3 (2026-09-26), although products.yaml changed afterwards (bb308b4, 2026-10-02). Agents should be told to pin the products-v1.0.0 SHA256SUMS, not a main-branch commit.
- The Rainier ordering table (issue bodies and ROADMAP.md:175-185) lives only on unmerged branch docs/rainier3d-leverage-2026-09-28. GAIA agents working from main will not see it, and the grouper ignores it.
- #224: the 3 seismic virtual gauges (NSE log Q 0.75-0.95) come from seis-hydro-2-sed fitted against NWIS discharge. They are not independent observations, so the issue must not count them as extra validation targets alongside the 15 NWIS gauges.
- #224: the 351 Jan-2009 landslides are identifiable only by date (rainier3d_paper.md:1030 TODO: no trigger field). They are not tied to the lidar-protocol deposits whose depth is recorded, so the 14.6 m median depth (n=453) may not describe the 2009 event set at all. The R2b target set needs a per-event depth/class audit before any ROC.
- #226: the issue calls the 22 flagged GNSS sites 'snow-affected edifice sites'. They are actually horizontal-velocity QC failures (PANGA mismatch >1 mm/yr or neighbour test >2.5 mm/yr, rainier3d_paper.md:773) across 203 regional sites. Excluding them does not remove snow/antenna artefacts from vertical series; that needs separate site-winter screening.
- Queue ordering: in the 'Water budget' milestone, P2 issues #225/#227 (batch 7) are dispatched before P1 #172/#175 (batch 8) and #137 (batch 9). Within-milestone ordering does not put P1 before P2 for these issues, so the Rainier physics add-ons run before the storage-account and calibration foundations they depend on.
- R6c (#228) would add a lahar class to src/data/rasterize_geology.py (classes 0-3). src/features/hydrogeologic_domains.py uses a different crosswalk schema (lithology_crosswalk.json _README), so a new class needs an explicit mapping in both places or it becomes nodata/unclassified.
- #223/#227: IceBoost thickness is only needed for long-term ice-store depletion. Seasonal degree-day ice melt depends on current glacier area and debris cover, so the adapter's priority layer for #227 should be an up-to-date ice extent, not thickness.
