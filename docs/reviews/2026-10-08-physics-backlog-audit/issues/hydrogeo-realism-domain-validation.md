# Issue family: hydrogeo-realism-domain-validation

I audited 20 open issues in this family, the v0.2 hydrogeologist-review spine plus the soil-moisture and satellite validation items. Most of the original v0.2 code has already merged, but only on the LEGACY Puget pilot path, and it has never been run on real data. The production v0.4 western-Cascades Stage-1 (src/models/baseline_wt_domain.py:94-119) screens no wells, uses no hydrogeologic domains and has fixed 10 km CV blocks. The domain wells it reads come from download_nwis_domain.py:66-121, which fetches no site metadata (no depth, screen or aquifer code) and drops every DTW<0 reading (:104). The per-domain gates exist (src/evaluation/domain_gates.py) and are wired into baseline_regression.py:345-366 only when --domain is passed. pixi `baseline` (pixi.toml:95) never passes it, and Makefile `baseline` (:156-170) never passes --max-well-depth-m. So the only committed skill artifact is still the pooled 200 km fallback: data/processed/block_cv_metrics.json gives RMSE 18.49 m and R2 0.089, and its folds 0 and 4 are bit-identical. docs/twin/05-state-evaluation.qmd:454 and the reconciliation callout below the table say so themselves. The domain raster cannot be built on the real grid until lithology exists: #14 waits on gaia-data-downloaders#10 (still OPEN), and #21 needs the DNR file plus a geologist review. Yet the queue dispatches #3/#6/#7/#8/#9/#10/#14 (batches 12-13) long before #21 (batch 37). One geology rule is physically dangerous in this domain: the starter crosswalk's refine rule GEOLOGIC_AGE contains 'miocene' -> CRBG would turn Miocene western-Cascades andesites into confined_basalt, a masked domain, even though CRBG barely occurs in this box. The soil-moisture and satellite half (#28/#29/#31/#49/#72/#197) is partly done or stale, and it repeatedly risks using calibration targets as validation (Sept-10 audit S2): #29 asks to bias-correct against SMAP, the very product it calls the independent check; #31 asks to score downscalers at native scale, which by construction cannot tell mean-preserving downscalers apart; #28's comments claim gains that the committed JSONs contradict. Two scope facts reshape #49 and #29. First, there are ZERO USCRN stations inside the DOMAIN bbox (I checked NCEI stations.tsv: Darrington is at 48.54N -121.44W, Quinault at -123.81W). Second, one GRACE mascon (~300 km) is larger than the whole 141x170 km domain.

**Queue ordering:** How the simulation orders this family (queue_sim.jsonl): #1 is held as an epic. Batch 12 is [14, 12, 10, 9] and batch 13 is [8, 7, 6, 3], both under v0.2. Batch 17 is [99] under v0.5. Then come topic batches: 30 [46], 31 [109, 49, 47, 25], 34 solo [197], 37 [89, 87, 21], 38 [72, 65, 31, 29] and 39 [28, 24, 22, 20]. BLOCKED_BY (gaia_group_issues.py:86-102) has no entry for any issue in this family. Problems: (1) Inverted prerequisite. #21, the only in-repo path to a lithology and domain raster, is unmilestoned and runs in batch 37, after #3/#6/#7/#9/#10 (batches 12-13) that need it. Agents will build against a missing raster or fall back to pooled metrics again. Milestone #21(A) to v0.2 and add BLOCKED_BY 3/6/7/10/47:[21]. (2) #8 runs in batch 13 while its mechanism #23 (TFN) runs in batch 33. Merge it into #23 or add 8:[23]. (3) #99 runs in batch 17 despite its own 'not before v0.4 closes' gate, with #100 open. Add 99:[100]. (4) #7 edits the same kriging code as P0 #186. #186 carries needs-human-decision, but the script does not treat that label as a hold for issues (it only skips epics and BLOCKED_BY), so #186 is dispatched in batch 3 and #7 later builds on a contested base. Add 7:[186], and either teach the script to hold needs-human-decision issues or remove the label. (5) #14 (external gaia-data-downloaders#10) and #22 (DataHub coordination) are not agent-actionable but are queued (batches 12 and 39). Close or exclude them. (6) Duplicates are split across batches: #9 (12) and #46 (30); #29 (38) and #197 (34, solo) both take NISAR. (7) Label-only grouping puts unrelated items together: batch 39 joins #22 (format question) with #28 (close-done); batch 12 joins #12 (LandLab contract, another family) with the hydrogeology items. (8) #47 and #49 sit in topic:validation batch 31 with no milestone. #47 should move to v0.2 behind 47:[21, 9, 186]. #49 is a quick doc fix that can go anywhere. After these edits the family would run: #21(A) -> v0.4 domain-raster gap plus recorder-ingest gap plus #9 (merged with #46) -> #3 (port and run) and #186 -> #7, #47 -> #6 -> #10. #8 moves into #23. #99 waits on #100. The soil-moisture items (#29 split, #197, #31, #72) follow independently, with #31 behind #197.

## #1 EPIC: Hydrogeologist review — stratified, data-anchored validation, domain masking & calibrated uncertainty
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [21, 186]
- physics: The principle is sound: score per flow system, mask where the shallow-unconfined assumption fails, and calibrate σ. The epic acceptance ('retired' global gates) is not met in practice. cross_validate.py:20 still defaults to 200 km, the only committed metric is that pooled fallback, and #186 shows the #5 coverage claim used variance in the wrong units.
- problems:
  - Checklist is stale: #2, #4, #5 and #11 are closed, while #12, #186, #228, #46, #47, #14 and #21 are missing or mis-linked.
  - The acceptance does not say the v0.4 production path (baseline_wt_domain.py) must adopt the domains. Only the legacy pilot does today.
  - The epic label holds it out of the queue (gaia_group_issues.py:177-178), which is fine, but its children carry no BLOCKED_BY edges.
- proposed edit: Refresh the checklist: closed #2/#4/#5/#11; open #3/#6/#7/#8/#9(+#46)/#10/#12/#14/#21/#47/#186/#228. Add an acceptance line: 'per-domain gates and coverage computed on western-cascades-v0.4 from a real lithology raster, committed as block_cv_metrics.json/coverage_metrics.json; cross_validate.DEFAULT_SPACING_M removed; the pooled fallback fails loudly.'

## #3 Per-domain validation gates + variogram-sized CV blocks (retire <8 m / 200 km)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [21]
- physics: The code landed: domain_gates.py:27-34 has the gates table and :93-139 runs per_domain_cv with variogram blocks. Two physics flaws remain. (a) estimate_variogram_range is fit to raw DTW y (:116). Raw-DTW variance is dominated by topography (prior_calibration.py:8-14 says so explicitly), so the block size should come from the variogram of held-out residuals (Roberts et al. 2017). (b) The MIN_BLOCK_M=2 km clamp contradicts the body's 'sub-km in fractured rock'. The thresholds are reasonable targets. A 0.75 m RMSE on long-term median DTW is still coarser than the 0.1-0.2 m liquefaction sensitivity cited in #47.
- problems:
  - Mostly implemented; the remaining work is running it and porting it, which the body does not describe.
  - Never run on real data: the committed block_cv_metrics.json is the pooled 200 km fallback.
  - Not ported to v0.4 baseline_wt_domain.py (:112-114 uses fixed 10 km GroupKFold).
  - pixi `baseline` omits --domain (pixi.toml:95), so the gate is silently skipped.
  - The committed folds 0 and 4 are identical (BlockShuffleSplit repeats with few blocks), so the 5-fold mean is effectively 4-fold.
  - No n-dependent confidence interval on per-domain RMSE; with MIN_WELLS_FOR_CV=20 a pass/fail call is statistically weak.
  - Cannot run until the lithology raster exists (#14/#21).
- proposed edit: Retitle to 'Run + port per-domain gates to v0.4'. Tasks: (1) residual-variogram block sizing, reusing prior_calibration's OOF residuals; (2) per_domain_cv in baseline_wt_domain.py; (3) delete the 200 km default and make the --domain-absent path exit non-zero; (4) GroupKFold over unique blocks, plus a bootstrap CI on RMSE/bias; (5) align the pixi and Makefile tasks. Acceptance: committed per-domain JSON on the v0.4 grid with CIs. Add BLOCKED_BY 3:[21].

## #6 Temporal validation at continuous recorders (phase, recession, aliasing)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [21]
- physics: Correct and important: separate spatial from temporal skill, and compare synoptic wells in like seasons. Three problems. Phase '±1 month' at monthly cadence is too coarse for the storm-timing landslide claim; it needs daily recorder data. The seasonal amplitude 1.06 m and the April peak are already CALIBRATION targets (notebooks/calibrate_fluxes.py:36 AMP_OBS; #100), so scoring them again on the same well population is circular (audit S2). Recession should be scored with a master-recession or episodic recession fit on well hydrographs.
- problems:
  - No continuous-recorder data path exists: download_nwis*.py pull only the OGC field-measurements collection (download_nwis_domain.py:35) and qc_nwis.py has no recorder flag.
  - Unknown how many continuous recorders fall inside the v0.4 domain; the first task should count them.
  - Overlaps #100 (April peak), #131 (storm delay validated against a continuous well) and #189 (holdouts).
  - Needs the domain raster for per-domain tables.
- proposed edit: Add a prerequisite issue for continuous-recorder ingestion (gap below). Require recorders held out from calibrate_fluxes/#137 fitting, with a frozen partition list. Score daily data: phase in days, KGE on anomaly, recession constant. Score synoptic wells like-season with an aliasing term. State explicitly that the amplitude/April-peak targets are calibration diagnostics. Add BLOCKED_BY 6:[recorder-ingest gap, 21].

## #7 Stage 3 nugget = representativeness variance (stay-close-to-data knob)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [186, 21]
- physics: The concept is right: the nugget equals measurement plus representativeness variance. It is incomplete: aliasing a synoptic read into a monthly median, and screen/vertical mismatch, also belong in it. The stated premise is wrong: interpolate_residuals.py:85-91 lets PyKrige auto-fit an exponential variogram, nugget included, but in NORMAL-SCORE space (:77-83). The nugget is therefore dimensionless and cannot simply be 'set to 0.3-1 m²'. This is the same unit defect as P0 #186. A per-domain, per-month fit is infeasible with MIN_SITES_PER_MONTH=30 (:36); use a time-pooled variogram.
- problems:
  - Premise 'default/zero nugget' is stale or incorrect.
  - Must land after #186 (same function; #186 is P0 and needs-human-decision but is NOT held by the queue script).
  - prior_calibration.py already implements a REML Matérn plus nugget on OOF residuals in physical units; the body does not mention reusing it.
  - Which Stage-3 is operational is ambiguous: gwl_dynamic.py (kriged anomalies) or legacy interpolate_residuals.py.
  - 'No spurious bullseyes' is not testable as written.
- proposed edit: Rewrite: estimate τ² per domain with prior_calibration (REML, OOF residuals, physical m²) on time-pooled anomalies. Apply it in whichever Stage-3 is canonical (name it) after the #186 back-transform. Acceptance: held-out well standardized residual sd within [0.9, 1.1] per domain, and nugget CI reported. Add BLOCKED_BY 7:[186, 21].

## #8 Stage 2 response time tau conditioned on aquifer type
- verdict: **merge** (verifier upheld); agent_ready: False; missing blockers: [23, 21]
- physics: Directionally right: τ spans days in fractured shallow flow to years in basalt storage. But τ is set as much by drainage geometry (τ ~ Sy·L²/T) as by lithology. The code has three different τs: climate_response.py is memoryless OLS (:4-10, no TFN); the water budget uses a HAND-scaled Dupuit recession (water_budget.py:185-196); the OU prior uses TEMPORAL_TAU_DAYS gwl=120 d (observability.py:769). Brutsaert–Nieber is a streamflow recession method, not a well-hydrograph method. 'volcanic_deep: years' is moot because that domain is masked.
- problems:
  - Depends on #23 (TFN not implemented), yet it is queued in batch 13 while #23 sits in batch 33.
  - Does not say which τ to condition.
  - Validation method is mis-specified (Brutsaert–Nieber).
  - The Sept-10 roadmap review (roadmap-review.md:103) lists #8/#23 for consolidation.
- proposed edit: Merge into #23 as its acceptance item: TFN τ and gains fitted within domain strata with per-domain priors, validated on held-out continuous recorders (from #6) using master-recession fits. Alternatively keep #8 with BLOCKED_BY 8:[23, 21] and add an explicit task to make the water_budget Sy/τ domain-dependent.

## #9 Aquifer-aware deep/confined well screening (shallow-only target)
- verdict: **rewrite** (verifier upheld); agent_ready: True; missing blockers: []
- physics: Correct and high-value. The classifier exists: well_hydrostratigraphy.measurement_target (:129-197) uses flowing, aqfr_type_cd, screen and depth evidence, and qc_nwis.py:309 attaches it. But no training set uses it. baseline_regression.py:140-144 applies the depth-only watertable_wells, which keeps unknown-depth wells (:83-96). The v0.4 baseline_wt_domain.py:94-95 applies no screen at all, and its wells (download_nwis_domain) carry no metadata. Dropping DTW<=0 everywhere (baseline_regression.py:136, baseline_wt_domain.py:95, download_nwis_domain.py:104) biases valley fill deep and removes artesian evidence. 'Cross with confined_basalt' is nearly moot in western-Cascades-v0.4. The physically relevant confining units here are Qva below Vashon till and the Osceola/Electron lahar cap (rainier3d leverage R6c).
- problems:
  - Duplicate of #46 (and overlaps #189); the roadmap review recommends consolidating #9/#46/#189.
  - Stale premise: it says 'screen is depth-based', but a richer classifier now exists and is simply unused.
  - The domain path has no site metadata to screen on.
- proposed edit: Make #9 the single owner (close #46 into it). Tasks: (1) fetch site metadata (well depth, screen top/bottom, aqfr_type_cd, nat_aqfr_cd) for domain wells via the OGC monitoring-locations collection; (2) require measurement_target=='water_table' for the Stage-1/2/3 targets in both pipelines; (3) keep DTW<=0 and flowing wells as censored/flagged rows, not drops; (4) report counts and median DTW per target and per domain; (5) make lahar-capped areas a screening flag. Leave the operational DA records to #189.

## #10 Coastal & stream boundary conditions (sea level, stream stage)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [21, 175]
- physics: Partly wrong physics. The water table equals mean sea level only AT the shoreline. Inland it rises (Dupuit/Ghyben-Herzberg; tidal forcing also raises the mean inland head, cf. Nielsen 1990). A 2 km / HAND<=10 m 'coastal' cell therefore should NOT 'converge to sea level ± tidal range'. Puget Sound's ~3-4.5 m tidal range also makes that band nearly untestable. HAND already references the nearest drainage, so a HAND-based prior implicitly carries a stream-stage boundary, and sparse gauge stage adds little. The real defect is in the water budget: valley cells (HAND<=d0) have no groundwater sink (water_budget.py:193-196). No coastal or stage code exists anywhere in src/.
- problems:
  - The acceptance 'coastal cells converge to sea level ± tidal range' is physically and quantitatively wrong.
  - Targets only legacy Stage-1/3 files, not the water budget that drives the twin.
  - Depends on the domain raster (#21) and the dist_coast raster (DataHub fetch_gaia dist_coast).
  - 'DTW<0 only in floodplain/tidal (<0.1%)' conflicts with real valley-floor wetlands and artesian wells, which upstream QC currently deletes.
- proposed edit: Rewrite as: impose head=MSL (NAVD88 offset, VDatum) on shoreline cells only, with a Dupuit/Ghyben-Herzberg inland profile as a soft prior; add a valley/riparian groundwater sink in water_budget (coordinate with #175); acceptance on held-out near-coast wells (bias and RMSE versus distance from shore), plus fraction of DTW<0 cells outside NWI wetlands/floodplain. Add BLOCKED_BY 10:[21].

## #14 Lithology data gap over Puget Sound blocks #2 acceptance (depends on downloader #10)
- verdict: **close-superseded** (verifier upheld); agent_ready: False; missing blockers: [21]
- physics: A data-availability tracker with no physics content. The fix lives in another repo: gaia-data-downloaders#10 is still OPEN. The local rasterizer path (#21, src/data/rasterize_geology.py) is the in-repo workaround.
- problems:
  - Not actionable by an agent in this repo, yet queued in batch 12 under v0.2.
  - Refers to #2, which is closed.
  - An external dependency cannot be expressed in BLOCKED_BY.
- proposed edit: Close as superseded by #21, linking gaia-data-downloaders#10, or remove the v0.2 milestone and add an exclusion label the queue honors. #21 becomes the in-repo unblocker for #3/#6/#7/#10/#47.

## #21 Complete DNR lithology crosswalk + adopt local rasterizer (unblocks #14 / #2)
- verdict: **split** (verifier upheld); agent_ready: False; missing blockers: []
- physics: This is the critical unblocker. data/processed/lithology_crosswalk.json is a STARTER (56 LITHOLOGY values). Its refine rule (GEOLOGIC_AGE contains 'miocene' -> class 3 CRBG) is wrong for this domain: the western Cascades are full of Miocene andesite and intrusive units, and CRBG is essentially absent from the v0.4 box. Those cells would be masked as confined_basalt. The crosswalk also lacks a lahar class: Osceola covers 79.7 km² and Electron 18.8 km², and both cap valley-fill aquifers (rainier3d leverage README :61-63, R6c). The body says lithology 'never affects GWL prediction', but it does gate validation and masking, so errors silently remove domains.
- problems:
  - Mixes agent work (download the public DNR 1:100k data, list units, map, rasterize, count) with a human geologist sign-off.
  - Makefile `domains` targets the legacy terrain_hand_90m.tif grid (Makefile:145-153), not DOMAIN western-cascades-v0.4.
  - Unmilestoned, so it runs in batch 37, after the v0.2 items it unblocks (batches 12-13).
- proposed edit: Split. (A) Agent, milestone v0.2, runs first: fetch DNR 100k geology for DOMAIN.bbox_4326; complete the crosswalk on the formation/unit-name field; drop the Miocene->CRBG age rule (key CRBG on Grande Ronde/Wanapum/Saddle Mountains names); add a lahar class; rasterize and build the domain raster on the v0.4 grid; commit per-domain cell and well counts. (B) needs-human-decision: geologist review of the crosswalk before any hazard run. Add BLOCKED_BY edges from #3/#6/#7/#10/#47 to (A).

## #22 DataHub: confirm raw geology archive format (GeoParquet vector vs Zarr)
- verdict: **hold-human** (verifier upheld); agent_ready: False; missing blockers: []
- physics: No physics content. The proposed division (vector GeoParquet for raw data, categorical COG/Zarr for derived layers) is correct, because polygons cannot go into Zarr losslessly.
- problems:
  - Purely a coordination question with another team; an agent cannot 'confirm with DataHub'.
  - Queued in batch 39 next to unrelated #28/#24/#20 purely by label.
- proposed edit: Label it so the queue excludes it (needs-human-decision is currently ignored for issues), or close it once the decision is recorded in docs/intermediate-staging-plan.md.

## #46 P1: HAND is unconfined-only; screen wells by aquifer; add confined-glacial-drift / perched domain
- verdict: **merge** (verifier upheld); agent_ready: False; missing blockers: []
- physics: The diagnosis is correct and the 2026-07-07 comment's reasoning is sound: confinement is a vertical unit, not a surface domain, and median DTW is ~6 m for shallow wells versus ~36 m for deep-confined ones. Implementation is partial: the depth-only screen sits on one pixi task, the v0.4 path is untouched, and measurement_target (#189 work) is unused for training.
- problems:
  - Duplicate of #9.
  - No milestone, so it runs in batch 30, separately from #9 (batch 12).
  - Perched tables under till and lahar are unaddressed.
- proposed edit: Close as merged into #9 (rewritten above), carrying over the perched/lahar-cap flag and the 'separate potentiometric product for aquifer_head wells' idea as an explicit non-goal or a future issue.

## #47 P1: Report achieved per-domain valley-fill RMSE / bias / coverage (not just pooled 18.5 m)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [21, 9, 186]
- physics: Exactly the right demand: the liquefaction-readiness claim rests on an unreported number. Note that the 0.75/1.5 m gate applies to the long-term median DTW. Liquefaction needs the time-varying DTW at event time, where seasonal amplitude is ~1-3 m, so the report should also cover anomaly-included error from held-out recorders (#6). Coverage must use #186-corrected variances.
- problems:
  - Blocked by the domain raster (#21) and screening (#9); otherwise it reproduces the same pooled number.
  - Coverage is meaningless until #186 lands.
  - No acceptance on sample size or CI.
  - No milestone; batch 31.
- proposed edit: Milestone v0.2. Acceptance: committed per-domain table on the v0.4 grid (n wells, RMSE, bias and 90% coverage, each with a bootstrap CI), screened water_table wells only, plus a separate row for monthly-anomaly-included error. Preserve a negative result. Add BLOCKED_BY 47:[21, 9, 186].

## #49 P1: Demote MERRA-2 to inter-model consistency; report a lowland USCRN/ISMN result
- verdict: **rewrite** (verifier upheld); agent_ready: True; missing blockers: []
- physics: The demotion is DONE: 05-state-evaluation.qmd:419-460 labels MERRA-2 a 'MODEL cross-check', and 02-evaluation-data.qmd:40 likewise. The 'lowland USCRN result' is infeasible: NCEI stations.tsv has no USCRN site inside DOMAIN (lon -122.91..-121.60, lat 47.07..48.13); the nearest are Darrington (48.54, -121.44) and Quinault (-123.81). Despite that, 01-input-data.qmd:49 lists USCRN for 'soil-moisture assimilation (valley/lowland)', observability.py:884 marks USCRN employed=True, and README.md:344 claims USCRN anchors.
- problems:
  - Half stale.
  - The remaining half is physically impossible as stated.
  - ISMN needs manual registration and download (soil_moisture_stations.py:8).
- proposed edit: Retitle: 'Drop the lowland USCRN assimilation claim (no in-domain stations)'. Tasks: correct 01-input-data.qmd:49, README.md:344 and STREAMS USCRN employed->False (or keep it with a 'no in-domain stations' note); move the SMAP result to #29. Close after.

## #99 S1: Stehekin — scope the eastern-Cascades extension (rain shadow + snowmelt regime)
- verdict: **defer** (verifier upheld); agent_ready: False; missing blockers: [100]
- physics: The physics framing is right: a 0.25° FuXi grid cannot resolve the crest rain shadow, and a snowmelt-dominated regime makes the degree-day module first-order. Partly stale: a SNOTEL SWE fetcher and SWE calibration now exist (src/data/fetch_snotel_swe.py, notebooks/calibrate_snow_swe.py). rainier3d S29 offers a PRISM-versus-MRMS orographic check (MRMS 169 mm below 500 m versus 547 mm above 3000 m; leverage README:39). Hydrogeologically the Stehekin basin is crystalline bedrock plus valley fill with very few wells, so the GWL side has nothing to validate against.
- problems:
  - Its own gate says not before v0.4 closes; #100 is still open (roadmap-review.md:61-63), yet the queue dispatches #99 in batch 17.
  - It is a scoping placeholder with no testable acceptance.
- proposed edit: Add BLOCKED_BY 99:[100]. Update the body to reflect the existing SWE fetcher and calibration, and add the MRMS/PRISM orographic test. Rewrite acceptance as a scoping memo before any code.

## #109 Surface-water extent (Sentinel-2 optical) as a distributed flux / variable-source-area constraint
- verdict: **defer** → verifier: **split** (The substance is right, but the verdict label is inconsistent with the proposed edit, which is a split: an agent-ready static HAND channel mask vs JRC GSW, plus a deferred dynamic VSA. 'Defer' would also defer the defensible static half. The title says Sentinel-2 optical while the body prefers SAR. Optical and C-band SAR cannot see saturation under the closed conifer canopy that dominates the domain, which supports deferring the dynamic part.); agent_ready: False; missing blockers: []
- physics: Physically overstated. Optical and SAR water masks detect OPEN water. Saturated variable-source-area soils under a closed conifer canopy are not open water and are largely invisible to S2 and to C-band S1. Storm-time inundation in channels and floodplains is dominated by routed streamflow and overbank flow, not groundwater outcrop. The score 'water table within S_y·d of surface' is dimensionally muddled: Sy·d is a storage deficit, not a depth. Binary inundation needs a classification likelihood, not a footprint average (science-review.md:59). The title says Sentinel-2 while the body prefers SAR, and the wet-season cloud cover makes the S2 premise weak.
- problems:
  - Dynamic VSA scoring is not defensible physics for this domain.
  - The static HAND channel-mask check against JRC GSW is defensible and small.
  - No milestone.
- proposed edit: Split: (a) agent-ready static task, validating the HAND-derived channel/perennial-water mask against JRC GSW occurrence, with precision and recall by stream order; (b) defer the dynamic VSA work to the flood milestone (#199-#202), with a classification-likelihood operator. Fix the title.

## #72 ERA5-Land as an independent gridded cross-validation product (upscale-then-compare)
- verdict: **keep**; agent_ready: False; missing blockers: []
- physics: Correctly framed as inter-model consistency, not ground truth. ERA5-Land HTESSEL layers (0-7/7-28/28-100/100-289 cm) must be depth-weighted to the model's z_r (SOLUS 0.1-2 m). At 9 km the domain holds roughly 15x19 cells, and complex-terrain SWE biases are large. The 2026-07-15 comment expands the scope to runoff and SWE, absorbing #114.
- problems:
  - No fetcher exists in src/data (only fetch_earth2studio).
  - CDS API account and licence acceptance are a human credential step.
  - The body still describes the pre-comment narrower scope.
- proposed edit: Fold the comment's multi-variable scope into the body; require depth-matched layer weighting and an explicit 'MODEL cross-check' role label in every table; note the CDS credential prerequisite (agent writes the fetcher plus mocked tests; a human supplies the key).

## #29 Native-scale calibration/validation vs SMAP, NISAR, NLDAS-v3, GRACE (upscale-then-compare)
- verdict: **split** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Upscale-then-compare is correct. Four physics defects. (1) Task 2 'calibrate/bias-correct θ against SMAP' turns the one independent check into a calibration target (audit S2); SMAP must be held out, or split by time. (2) SMAP is 0-5 cm against the model's root zone, and dense western-Cascades forest (VWC > ~5 kg/m²) degrades L-band retrievals; the quality flag must be applied. (3) GRACE senses total water storage, not groundwater (science-review S11), and one mascon (~300 km) exceeds the whole 141x170 km domain, so it carries essentially no spatial information here. (4) NISAR duplicates #197. The SMAP fetcher and validate_smap.py exist, but no smap_validation.json is committed.
- problems:
  - Omnibus issue spanning four products with different readiness.
  - Its acceptance uses a product as both calibration and validation.
  - GRACE is effectively out of scope at this domain size.
  - It absorbed #110, but the roadmap review warns that the closure does not establish a delivered SMAP evaluation.
- proposed edit: Split into: (a) run validate_smap.py on the v0.4 domain with quality and VWC masking and a depth caveat, then commit the JSON, as validation only; (b) NLDAS-v3 as an inter-model check; (c) GRACE: either drop it or require TWS compartment accounting at mascon scale over a larger region; (d) NISAR goes to #197. Remove 'calibrate against SMAP', or require a frozen time split.

## #28 SNOTEL soil-moisture observation anchors + assimilation (obs-anchor SM like GWL)
- verdict: **close-done** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Ingest, QC, independent validation and the snow module are done (fetch_snotel.py, validate_snotel.py, soil_moisture.py:199-228). The committed artifacts contradict the comments. snow_calibration.json gives loso_mean_r_calibrated 0.439, BELOW the default 0.493, so the tuning does not generalize (also stated in 05-state-evaluation.qmd); the defaults in soil_moisture.py:200-202 were never changed, despite the comment saying 'adopted'. snotel_anchor.json shows anchoring makes held-out RMSE WORSE (0.092 -> 0.118). That is physically expected: 5 heterogeneous upland stations with a 30 km length scale, and 0 stations in the lowland pilot.
- problems:
  - Original tasks complete; the remaining items (depth-matched comparison, anchoring) are either negative results or belong in #189.
  - Comment numbers are stale against the committed JSON.
- proposed edit: Close with a summary comment recording the negative results (anchoring degrades LOSO; snow calibration does not generalize) and correcting the 2026-07-03 numbers. Open the depth-matched sensor-depth comparison as a small follow-up under #189.

## #197 Ingest NISAR Beta Soil Moisture (V1, 200 m) as a soil-moisture validation/assimilation stream
- verdict: **keep**; agent_ready: False; missing blockers: []
- physics: Sound framing: native-support comparison with the Beta caveat carried forward. Part is done: STREAMS already lists 'NISAR Beta SM v1 (retrieval)' with employed=False (observability.py:887-888). The physics caveats are missing. The L-band SAR retrieval is 0-5 cm against the model's root zone. Dense conifer canopy over most of the domain will flag or degrade retrievals. The ~6-day revisit cannot resolve storm-scale wetting. The 'July 2026 calibrated release' date has passed, so the agent must check the product's current status rather than copy the caveat.
- problems:
  - No milestone or labels, so it runs as a solo batch (34), separate from #29 (38): risk of duplicated NISAR work.
  - Needs Earthdata .netrc (preconditions.require_netrc) for any real run.
- proposed edit: Make #197 the sole NISAR owner and remove NISAR from #29. Add labels validation/soil-reanalysis and a milestone. Acceptance: fetcher plus mocked test; a native 200 m comparison restricted to retrieval-quality-flagged pixels, reported by land cover; the Beta/release status verified at run time.

## #31 Data-informed / model-driven downscaler beyond the bilinear resampling baseline
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [197]
- physics: The implementation is done: twi, regression and ml downscalers are registered (downscale.py:131-243). The acceptance is ill-posed. A mean-preserving downscaler upscaled back to the coarse grid reproduces the coarse field by construction (downscale.py:165-170, :203-210), so 'improvement at native-scale validation (#29)' cannot tell it apart from bilinear. Fine-scale skill must be scored against sub-footprint observations: in-situ probes, NISAR at 200 m, or wells for GWL. The TWI downscaler uses a fixed 0.035 m³/m³ per σ (:155) that is unconstrained. TWI control of θ is state-dependent: strong when wet, weak when dry (Grayson et al. 1997). 'Poroelastic head propagation for GWL' is not a downscaling mechanism.
- problems:
  - The task 'implement ≥1 non-trivial downscaler' is already done.
  - Its acceptance cannot discriminate between methods.
  - The representativeness-σ update is undefined until a fine-scale score exists.
- proposed edit: Rewrite: the downscalers exist. Remaining work: score twi/regression/ml against bilinear on sub-footprint held-out data (NISAR 200 m pixels from #197; SNOTEL point sites), with wet/dry stratification; fit or justify the TWI coefficient; update representativeness_sigma from the measured gain. Drop the poroelastic option.

## Gaps (proposed new issues)

### Build the hydrogeologic domain raster on the v0.4 grid and wire domains into baseline_wt_domain.py
- milestone: v0.2 — Hydrogeologic realism; blocked_by: [21]
- why: Every v0.2 item stratifies on the domain raster, but Makefile `domains` (:145-153) builds it only on the legacy pilot HAND grid, and the production Stage-1 (baseline_wt_domain.py) ignores domains entirely (fixed 10 km blocks at :112-114).

Run src.features.hydrogeologic_domains on DOMAIN (western-cascades-v0.4), using the #21 lithology and dist_coast rasters. Sample domains at the training wells in baseline_wt_domain.py; call per_domain_cv and per_domain_coverage; write block_cv_metrics.json and coverage_metrics.json; commit cell and well counts per domain. Acceptance: committed artifacts on the v0.4 grid; the pooled fallback removed.

### Ingest USGS continuous groundwater recorders (OGC daily/continuous collections, 72019) with a recorder flag
- milestone: v0.2 — Hydrogeologic realism; blocked_by: []
- why: #6, #8, #131 and #100 all need daily or sub-daily well hydrographs; the repo fetches only the field-measurements collection (download_nwis_domain.py:35).

Fetch daily DTW for in-domain sites from the USGS Water Data OGC API; flag recorder sites in qc_nwis; record counts by domain and measurement_target; freeze a held-out recorder list that the calibrate_fluxes/#137 fits must not touch. Acceptance: a parquet of recorder hydrographs plus a committed partition file.

### Domain-well metadata and censoring: stop dropping DTW<=0 / flowing wells; attach screen and aquifer codes
- milestone: v0.2 — Hydrogeologic realism; blocked_by: []
- why: download_nwis_domain.py fetches no site metadata and drops DTW<0 (:104); both baselines drop median DTW<=0. This deletes artesian and valley-floor evidence and makes measurement_target impossible on the v0.4 path.

Fetch monitoring-location metadata (well depth, screen interval, aqfr_type_cd, nat_aqfr_cd) for domain wells; keep DTW<=0 and flowing readings as flagged or censored rows; feed measurement_target into training. Acceptance: counts of water_table/aquifer_head/unknown wells, and Stage-1 refit with versus without them reported. Could instead be folded into rewritten #9.

### Fix CV mechanics: no duplicate folds, residual-variogram block size, CIs on per-domain gates
- milestone: v0.2 — Hydrogeologic realism; blocked_by: []
- why: The committed block_cv_metrics.json has identical folds 0 and 4; block size comes from the raw-DTW variogram (domain_gates.py:116), which is topography-dominated; and gates with n>=20 carry no uncertainty.

Replace BlockShuffleSplit with GroupKFold over unique blocks; size blocks from the OOF residual variogram (prior_calibration); add a bootstrap CI to RMSE and bias, and decide pass/fail on the CI; remove DEFAULT_SPACING_M=200 km. Acceptance: unit tests showing distinct folds, plus CI fields in the JSON. Could be folded into rewritten #3.

### Validation-role registry for hydrogeologic and soil-moisture evaluation data
- milestone: v0.2 — Hydrogeologic realism; blocked_by: []
- why: Calibration targets keep resurfacing as validation: AMP_OBS 1.06 m and the April peak in calibrate_fluxes.py are reused in #6/#100; #29 proposes calibrating to SMAP; #28 anchors to the same SNOTEL stations it validates on (audit S2).

One committed file listing, for each well, recorder, station and product-time window, whether it is used for calibration, assimilation or held-out validation. Fitting scripts must assert they do not touch held-out rows. Coordinate with #189, which owns operational DA records.

## Verifier extra problems

- KEEP #197 is stale and under-specified. Its caveat says NASA's calibrated release was 'scheduled for July 2026'; today is 2026-10-08, so before writing any caveat text the agent must check whether that release happened. The title says 'validation/assimilation' but there is no frozen split. NISAR SM is about 0-5 cm L-band against a 0-1 m bucket, and dense-forest VWC in the Cascades needs explicit masking. It also needs Earthdata credentials in the agent environment. The keep is acceptable only with these edits.
- KEEP #72 needs a CDS API key, a credential an autonomous agent may not have, so it should be credential-gated or held. Its layer depths (0-7/7-28/28-100 cm) need depth weighting to compare with the 0-1 m bucket. It sits in batch 38 together with #29 and #31, which the audit wants split or rewritten, so it risks building on the old #29 scope. The physics is otherwise sound, so keep is upheld.
- Two inconsistent degree-day snow modules: soil_moisture.py:199-202 (ddf 3.0, T_SNOW_HI 3.0, T_MELT 0.0, nominal) vs forecast.py:14-17 (ddf 3.0, T_SNOW_HI 4.0, T_MELT 1.0, SWE-calibrated). Agents working #28/#29/#99/#100 will get different snow partitions depending on which path they call. No audited issue owns reconciling them.
- rasterize_geology refine rules apply to any already-classified polygon (rasterize_geology.py:120-122). The starter GEOLOGIC_AGE contains 'miocene' rule (lithology_crosswalk.json refine) would relabel Miocene plutons and andesites in the v0.4 domain as CRBG, and confidence_mask.py:31,70 then hard-masks them. The product-affecting risk contradicts #21's 'low risk' text.
- Per-domain gate and coverage failures are warn-only (baseline_regression.py:357-360, 368-370) and the pooled fallback is warn-only (:371-378). Acceptance in #1/#3/#5 ('fail the gate per domain') is therefore not met on origin/main, even though #5 is closed.
- The 200 km CV default is duplicated: cross_validate.DEFAULT_SPACING_M (cross_validate.py:20) and the --cv-block-km default of 200 (baseline_regression.py:302). Retiring only one leaves the pooled 200 km path alive.
- Neither model pipeline trains on measurement_target=='water_table'. Legacy uses the depth-only watertable_wells with keep_unknown_depth=True (well_hydrostratigraphy.py:83-96), and v0.4 baseline_wt_domain.py:97-98 does no screening. The unknown-depth promotion directly contradicts the #189 classifier's stated contract.
- #186 (P0, needs-human-decision) will be dispatched alone in batch 3 because gaia_group_issues.py never reads that label on issues. Batch 13 (#3/#6/#7/#8) and #47 would then build on whatever an agent decided unilaterally about the back-transform.
- v0.2 batch 12 (#14, #12, #10, #9) and batch 13 (#8, #7, #6, #3) all depend on a domain raster that cannot exist until #21 (batch 37) lands. Without BLOCKED_BY edges, 8 issues will be attempted with no lithology data, producing mocks or pooled fallbacks.
- Lahar deposits map to class 0 unconsolidated (lithology_crosswalk.json mapping 'lahar': 0), so low-HAND lahar surfaces such as the Osceola/Electron flows in the Puyallup/White valleys get classified as unconsolidated_valley_fill. They would then be held to the 0.75 m gate, although they are a low-permeability cap with perched or confined water beneath. This needs coordination with #228 before any per-domain gate result is trusted.
