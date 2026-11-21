# Issue family: forecast-interop-software-docs

This family has 25 issues. Five are epics or trackers (#73, #150, #204, #60, #18). The rest cover the forecast-forcing lane (#71, #32, #58, #56, #59), the probabilistic forecast, hazard and validation chain (#191, #193, #195), Earth2Studio interop (#203, #112), software hardening (#152, #153, #155, #156, #157), housekeeping (#40, #25, #24) and the LandLab handoff (#64, #65).

**What origin/main already has**
- A FuXi/earth2studio adapter that refuses all-zero precipitation and declares GraphCastOperational and ACE2 unusable for rain (src/data/fetch_earth2studio.py:54-63, 66). The 15-day FuXi model is preferred (line 59). The adapter has never been run on a GPU (ROADMAP.md:51).
- A deterministic `ForecastForcing`/`SoilStateForecast` with a degree-day snow model (src/models/forecast.py:65-131). Hargreaves-Samani PET is used for PRISM (src/data/fetch_prism_daily.py:42-55; fetch_prism_monthly.py:94).
- A pytest CI gate where dv/v tests skip visibly (.github/workflows/ci.yml; tests/test_dvv.py:95; commit c4e1a01, #151/#152).
- A LandLab export CLI with per-cell sigma, confidence mask, seasonal-high water table, `align_to_grid` and a manifest (src/io/landlab_export.py:49-382; pixi.toml:210-212; commit 13eaf07 'feat(#64)').

**What is stale or wrong**
- **#71** still asks for GraphCast/ACE2. The repo itself shows GraphCastOperational emits zero precipitation. ACE2 is a 1-degree climate emulator, not a 1-15 day QPF model.
- **#58** assumes the AI models supply radiation and humidity. FuXi and GraphCast output no surface radiation, and FuXi has no 2 m humidity.
- **#56** is a pre-water-budget interface table. SPI-3 and PDO have no meaning as 15-day forecast outputs, and dSWE is now produced internally by the snow model.
- **#64** is done but would be re-dispatched (queue batch 28).
- **#152** is done but would be re-dispatched (batch 0).
- **#40** has a single leftover: the published docs/gwl_audit_framework.html still says 'r = 0.98 vs TerraClimate'.

**Gaps nobody owns**
- How meteorological ensemble members are actually built (roadmap-review R8).
- Forecast-mode PET, and a smooth handoff from hindcast to forecast at lead 0.
- PRISM's 12-12 UTC day versus FuXi's lead-day binning from a 00Z start.
- A mass-conserving orographic precipitation downscaler.
- forecast.py:181-182 weights Vs30 by thickness instead of travel time. This underweights the slow root zone by about 2x.

**Dependencies and holds**
- Dependencies stated in the bodies are often not encoded in `BLOCKED_BY`: #191 needs #136 and #155; #193 needs #190, #129 and #141; #203 needs #188 and #191; #32, #71 and #58 need #187 and #136.
- **#24** (repo rename) and the naming decision in **#204** need a human. The grouper would hand #24 to an agent in batch 38.
- **#25** has partial work on an unmerged branch (eight bibliography corrections, 2026-09-10 operational-start). An agent would redo it and conflict.

**Queue ordering:** How the queue simulation (queue_sim.jsonl) orders this family, and what is wrong with it:

1. **Completed work is re-dispatched.** Batch 0 is [#153, #152], but #152 is done (c4e1a01). Batch 28 is [#64, #54], but #64 is done (13eaf07). Batch 4 sends #40 alone as a global P0 although only one HTML line remains.

2. **The forcing order is inverted.**
   - Batch 19 (v0.7) runs [#71, #58, #32] before #136 runs FuXi (batch 20, filed under the 'Hazard: LandLab landslide' milestone, which is the wrong home; it should be v0.7).
   - It also runs before the #187 contract these issues feed (#187 is held behind #186, #52, #89, #137, #171 and #172).
   - The PRISM hindcast #70 runs in the last batch (39), and the AR-event gate #59 runs in batch 31 (topic:atmospheric, together with the superseded #56). The roadmap's 'hindcast before forecast, the event gate before forecast claims' sequence is reversed.

3. **Hold-backs are mostly right but incomplete.** #191, #193, #195 and #203 are held correctly. But:
   - #195 is over-held: only its hazard half needs #193.
   - #191 lacks #136 and #155.
   - #193 lacks #190, #129, #141 and #128.
   - #203 lacks #188 and #191.
   - #32, #71 and #58 lack #187 and #136.
   - #156 lacks #153.
   Missing transitive edges mean #155 (batch 5) happens to run early enough, but by luck.

4. **No human gate exists.** The grouper has no needs-human-decision exclusion: gaia_group_issues.py:17 excludes only 'epic', and there is no label check. So #24 (repo rename, admin-only) is batched with #28, #22 and #20 in batch 38. #25 is batched with validation science (#109, #49, #47) in batch 30, while its first slice sits on an unmerged branch. #65's s3://cresst production write is in batch 37.

5. **Topic batches mix unrelated work.** Batch 37 is [#72, #65, #31, #29] and batch 35 is [#112] alone. A batch of up to 4 should share a code surface; #65 belongs with #64/#200 (export), not with ERA5/SMAP validation.

6. **Epics are invisible to the queue.** #73, #150, #60, #18 and #204 are excluded from scheduling, and their checkbox drift (#60 has 15 mismatches, #150 has 4) misleads agents that read them as context.

7. **The Vs30 pause is not encoded.** #81-#86 still run in batches 13-14 despite the ROADMAP.md:129-133 pause, so #193's liquefaction branch would consume a Vs30 that the team has deliberately frozen.

**Recommended order:**
- First: close #152, #64, #56 and #71; narrow #40.
- Then #153a, #155, #156 and #157, plus the FuXi adapter fix and the 12-12 UTC alignment.
- Next #70, then #59 (after #89/#172), then #136 with the orographic downscaler, the member source and forecast-mode PET.
- Then #191, then #195a and #193 (split), then #195b.
- Last: #112, #203, #58, and #65 (agent part).

## #73 EPIC: Forecast forcing + downstream handoff
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: []
- physics: The principle is sound: PRISM for forcing, ERA5-Land only for validation, forecast the antecedent state not the hydrograph. The roster is stale. It names GraphCast/ACE2 (#71) although the code makes FuXi the only viable precipitation model (src/data/fetch_earth2studio.py:54-63). It omits #136 (actually running FuXi), #191/#195 (ensemble forecast and verification) and #200 (flood source terms).
- problems:
  - Lists closed #55 and #39 as live supporting work.
  - Missing #136, #191, #195, #199/#200 and the meteorological member-source gap (roadmap-review R8).
  - Has a milestone (v0.7) but is excluded from the queue as an epic, so its sequencing claims are never enforced.
  - Roadmap-review R8 explicitly says to update #71/#56/#73 to the FuXi daily path before agents run the old instructions.
- proposed edit: Rewrite the roster.
- Forcing: #70 (PRISM hindcast, first), #136 (FuXi run + bias correction), the new member-source issue, #57 (sub-daily), #58 (optional).
- Verification: #59, #72, #29, #195.
- Propagation: #191.
- Handoff: #65, #200, #193.
- Mark #71 and #56 superseded and #64 done.
- State the order: hindcast before forecast; the AR hindcast (#59) gates any forecast-skill claim.

## #71 Forward forcing: GraphCast/ACE2 QPF via earth2studio -> 90 m downscaler -> antecedent ensemble
- verdict: **close-superseded** → verifier: **rewrite (repurpose #71 in place as the meteorological member-source / FuXi-ensemble issue, BLOCKED_BY 187 and 136)** (Partly wrong premise. The code does not exclude all the prescribed models: GraphCastSmall is still an allowed --model choice (fetch_earth2studio.py:54,185); only GraphCastOperational and ACE2 are excluded (lines 61-63). The ACE2 exclusion rests on a code comment claiming ACE2 emits no precipitation, which is questionable and unverified (ACE2 has a surface precipitation-rate output). No open issue covers the residual scope: an ensemble, by-lead QPF member source and a 90 m orographic downscaler. #136 only bias-corrects totals against PRISM climatology. The audit itself has to invent two new issues to cover it. #187 ('Provides the interface for ... #71'), #191 ('Builds on #71/#73') and #203 all link to #71, so closing it orphans those links. Rewriting #71 as the R8 member-source task (how members are obtained, P/T dependence, the reforecast archive for calibration, ensemble size and compute) is cheaper and keeps the graph intact. Either way it must leave queue batch 19 until #187 and #136 land.); agent_ready: False; missing blockers: [187, 136]
- physics: The model choice is wrong. GraphCastOperational emits tp06 as zeros (fetch_earth2studio.py:9-13, 63). GraphCastSmall runs at 1 degree, which removes orographic enhancement entirely. ACE2 is a climate emulator with no deterministic skill at days 1-15. The repo's own note that ACE2 emits no precipitation (line 61) is itself doubtful, since ACE2-ERA5 predicts a precipitation rate; this should be verified.

Filing the precipitation downscaler under the #31 registry is a category error. That registry (src/models/downscale.py:102-226) downscales state fields using soil/terrain covariates. Precipitation downscaling must conserve the coarse-cell total and use PRISM climatology or orographic physics.

Bias-correcting against PRISM 'climatology' needs a multi-year reforecast archive stratified by lead time. One season of FuXi runs cannot calibrate quantile mapping.
- problems:
  - The prescribed models are already excluded by the code.
  - Its remaining real content duplicates #136 (run plus bias correction) and #191 (ensemble propagation); roadmap-review R9 lists the #71/#136 overlap.
  - The queue dispatches it in batch 19, before #136 (batch 20) and #70 (batch 39), and before the #187 contract it is meant to feed (#187 body: 'Provides the interface for ... #71').
- proposed edit: Close as superseded by #136 (FuXi execution and bias correction), #191 (ensemble propagation) and two new gap issues: the meteorological member source, and a mass-conserving orographic precipitation downscaler. Move the honest-scope sentence (antecedent state, not hydrograph) into #73.

## #32 GWL forcing/method ensemble — forcing-UQ parity
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [187, 186, 23]
- physics: Method spread is legitimate as a measure of structural uncertainty. Adding it as one more quadrature sigma term is not: kriging, beta-map and TFN share the same wells and forcing, so they are neither independent nor a calibrated sample of structural error, and the spread is at best a lower bound. The 'kriging sigma' it would add to is itself wrong until #186 back-transforms Stage-3 variance.

The ensembled quantity is the DTW anomaly (Aug 2026 comment). In a probabilistic twin, method members should be carried as members (#187 contract), not collapsed into a sigma. src/models/gwl_dynamic.py still has a single kriging path (lines 49-118).
- problems:
  - Depends on the TFN prototype #23 (open) and the beta-map path; not stated as blockers.
  - The acceptance criterion ('explicit ensemble-sigma component') is structural, not a test of calibration.
  - Roadmap-review R8 notes it is mis-scoped relative to the meteorological members that #191 needs.
  - Queued in batch 19, ahead of #187 and #186.
- proposed edit: Retitle it 'GWL structural (method) members for the #187 contract'.

Acceptance criteria:
1. Kriged, beta-map and TFN (#23) anomalies are emitted as labelled members on the #187 member dimension.
2. Held-out-well interval coverage (#186-corrected) is reported with and without the method members.
3. Spread is mapped against well density, and the claim that spread is larger in data-sparse uplands is tested.
4. Members are not added in quadrature to an existing sigma.

Add #186, #187 and #23 to BLOCKED_BY.

## #58 P2: Penman-Monteith PET path (AI-model radiation/humidity/wind)
- verdict: **defer** (verifier upheld); agent_ready: False; missing blockers: [136]
- physics: FAO-56 Penman-Monteith reference ET is the right formula, but the plan to source it does not work.
- FuXi (the preferred model) and GraphCast output t2m, u10/v10, msl and tp. They output no surface shortwave or longwave radiation, and FuXi gives humidity only on pressure levels.
- So 'use AI-model radiation/humidity/wind' is not possible for the forecast path. Rn would come from ERA5-Land (ssrd/strd, d2m), which works for hindcasts only, or from a radiation diagnostic.
- Reference ET0 is for a short-grass reference. Forested Cascade cells need a crop or canopy coefficient and a separate interception term, otherwise the result is no more physical than Hargreaves-Samani.
- Switching PET formula invalidates the existing bucket calibration and creates a step change at the hindcast-to-forecast transition (lead 0).
- TerraClimate PET is already Penman-Monteith-type.
- problems:
  - Queued in batch 19 as if ready, although the body calls it a later-stage enhancement and roadmap-review R8 calls it optional.
  - Has no test of lead-0 continuity and no recalibration requirement.
  - The forecast path has no PET at all yet: FuXi supplies only tmean (fetch_earth2studio.py:154-163), so even Hargreaves-Samani (which needs Tmax/Tmin) is undefined in forecast mode.
  - Stale 'PET (Hamon)' text remains in src/models/forecast.py:12 and src/data/stage_mvp_window.py:9.
- proposed edit: Remove it from the v0.7 milestone; label P2/deferred.

Rewrite:
- Hindcast PM from ERA5-Land Rn, u10 (converted to u2 with the FAO-56 log profile, Eq. 47) and d2m.
- Forecast PM only if a radiation source is chosen; otherwise Hargreaves-Samani with daily Tmax/Tmin taken from 6-hourly t2m. Four samples per day bias the diurnal range low, so report that bias.
- A canopy coefficient for forest.
- Mandatory recalibration of the bucket.

Acceptance: a lead-0 continuity test, so that hindcast and forecast PET agree within X% on overlapping days.

## #56 P2: Forcing-interface table (P, PET, SPI-3, dSWE, PDO; downscaling; bias correction)
- verdict: **close-superseded** (verifier upheld); agent_ready: False; missing blockers: []
- physics: This was written for the Stage-2 beta-map predictors, which the daily water-budget forecast no longer uses. SPI-3 is a 3-month accumulation, so a 15-day forecast changes at most about 1/6 of it; it is mostly observed past. PDO is not a weather-forecast output and should simply be persisted. dSWE is now computed internally by the degree-day snow model (forecast.py:105-131). The parts still valid are the temporal aggregation from 6-hourly to daily, spatial downscaling and quantile-mapping bias correction. Those belong in #187's forcing contract and in #136.
- problems:
  - Body is one line with no acceptance criteria.
  - Still mentions Hamon.
  - Unmilestoned; queue batch 31 with #59.
- proposed edit: Close as superseded by #187 (forcing section of the canonical contract), #136 (bias correction) and the new orographic-downscaler and member-source gap issues. Copy the SPI-3/PDO persistence rule into #187.

## #59 P2: Event-based validation — one PNW atmospheric-river hindcast
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [89, 172, 70]
- physics: This is the right gate: monthly correlations say nothing about how fast storms register in wells and probes. But the current model applies recharge to the water table instantly (forecast.py docstring, 'Known limitation'), so modeled well timing is early by design.

Without the daily storage fixes (#89, a 4.7x drainage difference between daily and monthly; #172, capillary-rise conservation), the hindcast would score known bugs. The event must not be inside the D7/daily calibration window, or the result is calibration posing as validation. The Nov 11-15 2021 Skagit/Nooksack AR sequence is a natural candidate if it is outside that window.
- problems:
  - No event is named, no metric (peak-timing error, peak-rise bias, recession time constant) and no pass threshold.
  - No holdout rule.
  - Unmilestoned P2 although it gates forecast claims (roadmap-review R9).
  - Queued in batch 31, after #71/#58 (batch 19), which it is supposed to gate.
  - Should be driven by daily PRISM (#70), which runs in batch 39.
- proposed edit: Milestone v0.7, priority P1.

Specify:
- A named AR event outside the calibration period.
- Daily PRISM forcing.
- Continuous well recorders plus SNOTEL/USCRN probes at their sensor depths.
- Metrics: onset and peak lag (days), peak magnitude bias, and recession tau, against an open-loop baseline.
- Report the instantaneous-recharge timing bias explicitly.

Add #89, #172 and #70 to BLOCKED_BY.

## #191 P1: Make SoilStateForecast ensemble-native and initialize from DA posterior
- verdict: **keep** (verifier upheld); agent_ready: False; missing blockers: [136, 155]
- physics: The physics is sound: member identity, P-T dependence, preserving lead-0 covariance, the one-member limit and spread that evolves with lead time.

What is unspecified: FuXi in earth2studio is deterministic (fetch_earth2studio.py:149 calls `deterministic`). 'Calibrated FuXi ensembles' needs initial-condition perturbation, a lagged ensemble or GEFS initial conditions, plus a reforecast calibration. AI-model perturbation ensembles are typically under-dispersive. Quantile-mapping each member breaks rank and dependence structure unless it is restored with ensemble copula coupling or a Schaake shuffle.

It inherits forecast.py:181-182, which weights Vs30 by thickness (d/30) instead of travel time. For a 200 m/s root zone over 400 m/s, the root-zone weight should be about 0.065, not 0.033.
- problems:
  - Has no source for meteorological members (roadmap-review R8).
  - Body says it uses #155 for member streams but #155 is not encoded; #136 (FuXi actually run) is not encoded either.
  - No minimum ensemble size or compute budget.
  - The Vs30 weighting error would carry into the ensemble diagnostics.
- proposed edit: Add #136, #155 and the new member-source issue to BLOCKED_BY. Add an ECC/Schaake-shuffle requirement after bias correction, and an acceptance check of spread versus skill at lead 1-15 against PRISM. Add a note to fix the Vs30 travel-time weighting first, or file it separately.

## #193 P2: Propagate joint ensembles into hazards
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [190, 129, 141, 128]
- physics: The principle is right: per-member factor of safety and probabilities preserve the tail dependence that marginal sigmas destroy, and the test that correlation changes tail probability is good. Three caveats.
- The geospatial liquefaction GLM (#141) already outputs a probability conditional on PGV. Averaging over members gives the marginal probability, but 'calibrated class probabilities' cannot be validated without an event inventory (#146).
- Vs30 has no ensemble, and Vs30 densification (#81-#86) is paused in ROADMAP.md:129-133.
- The stock LandLab `LandslideProbability` takes a recharge distribution and transmissivity and computes relative wetness itself. It does not take water-table depth, so 'per joint member' needs the custom pressure closure in #128.
- problems:
  - #190, #129 and #141 are stated dependencies but not encoded.
  - Has no flood branch, although #199 calls flood a consumer of #193 (roadmap-review R7).
  - The landslide and liquefaction branches have different readiness and should be separate.
- proposed edit: Split into #193a (shared joint-member hazard input contract, including flood source terms, aligned with #200) and #193b/c (landslide and liquefaction per-member runs). In BLOCKED_BY: #193a depends on #187 only; #193b on #191, #128 and #129; #193c on #191 and #141 (and #190 if mechanical memory is used). State that the Vs30 member dimension stays degenerate while #81-#86 are paused.

## #195 P1: Calibrate and validate probabilistic nowcasts/forecasts by lead and native support
- verdict: **split** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Scoring in observation space with native-support operators is correct and important. Three problems.
- PRISM assimilates COOP and SNOTEL stations, so 'evaluate meteorological forcing against PRISM/stations' is partly circular when bias correction is also trained on PRISM. Use separate years and stations independent of PRISM.
- With about 15 wells, stratifying by lead x domain x season x stream x support leaves strata with only a few cases. Minimum sample sizes and bootstrap confidence intervals are needed.
- FuXi daily bins from a 00Z start (fetch_earth2studio.py:154) do not line up with PRISM's 12-12 UTC day, a 12-hour phase error that inflates apparent day-1 error.
- problems:
  - Over-blocked: the dependency review says #193 gates only the hazard-verification part, yet BLOCKED_BY holds the whole issue on #193.
  - 'Calibrated or explicitly recalibrated' has no numeric threshold.
  - No rule separating calibration data from validation data.
- proposed edit: Split into #195a (hydrologic and meteorological lead-time verification, BLOCKED_BY [191, 194]) and #195b (hazard probability verification, BLOCKED_BY [193]).

Add to #195a:
- Pass thresholds (for example, PIT coverage of the 90% interval within [0.85, 0.95] and CRPSS > 0 against climatology and persistence).
- Minimum n per stratum, with bootstrap confidence intervals.
- A 12-12 UTC alignment requirement.
- Independent stations or years for any PRISM-trained bias correction.

## #203 Earth2Studio model-structure & assimilation compatibility
- verdict: **defer** (verifier upheld); agent_ready: False; missing blockers: [188, 191]
- physics: This is interop only, with no physics content. Earth2Studio Prognostic models expect fixed-step gridded tensors with coordinate dimensions. The twin's state includes parameters, bias states and member covariance, which do not fit cleanly, so this is more than a 'thin wrapper'. I am not sure whether current earth2studio exposes a DA-model interface to align with; the agent must check the installed version.
- problems:
  - Has no labels at all (no priority or topic).
  - Roadmap-review says the wrapper needs the actual #188/#191 interfaces, not just the #187 schema; only #187 is encoded.
  - Its value to the science goals is low compared with the forecast and verification work.
- proposed edit: Label it enhancement and P2. Add #188 and #191 to BLOCKED_BY. Acceptance: earth2studio `run.ensemble`-style tooling drives a 2-member, 3-step toy run of the wrapped #191 forecast, and the output round-trips back to the #187 contract.

## #112 Stream observation/forcing Zarr as earth2studio DataSources
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: []
- physics: This is a semantic error, not a physics one. The FuXi store is a forecast, indexed by initialization time and lead time. Wrapping it as a `DataSource` with `__call__(time, variable)` conflates valid time with lead time and loses initialization identity; earth2studio's forecast-source protocol (`__call__(time, lead_time, variable)`) is the correct fit. Point well and probe observations are not gridded and do not fit `DataSource`. Unit and convention mapping is non-trivial: earth2studio 'tp' is in metres per accumulation interval, while the repo stores mm/day.
- problems:
  - Registers the FuXi store under the wrong protocol.
  - Puts in-situ point streams in scope without a suitable interface.
  - No milestone; queued alone in batch 35.
- proposed edit: Narrow the scope.
- PRISM daily wrapped as a `DataSource`, with tp converted from mm/day to metres over the accumulation interval as declared.
- The FuXi store wrapped as a forecast source keyed by (init time, lead time).
- Drop in-situ observations, or defer them to a dataframe source if one exists.
- Round-trip tests run without earth2studio by duck-typing the protocol; earth2studio import stays lazy.

Acceptance: a slice read through the adapter equals the Zarr slice, and the lead-time coordinates are preserved. Once rewritten, an agent can do it.

## #150 [epic] Software hardening
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: []
- physics: No physics content. The first claim in the body, 'no CI runs the tests', is no longer true: .github/workflows/ci.yml runs `pixi run test` and `check-dois`.
- problems:
  - Checkboxes disagree with issue states: #151, #154, #158 and #159 are closed but unticked (roadmap-review R6 counts 23 such disagreements across trackers).
  - #152 is effectively done.
- proposed edit: Tick #151, #154, #158 and #159, and close #152. Update the opening paragraph to describe the current CI. Remaining children: #153 (split), #155, #156 and #157.

## #152 Real skips, not silent pass: pytest collection + importorskip
- verdict: **close-done** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Not applicable.
- problems:
  - Implemented by c4e1a01 ('Add a pytest CI gate; make dv/v skips visible (#151, #152)'). tests/test_dvv.py:95-164 uses `pytest.skip` with an ImportError-only guard (line 117). `pixi run test` is pytest discovery (pixi.toml:73), and ci.yml runs it.
  - The hand-maintained `__main__` lists remain in about 20 test files but are dead in CI and harmless.
  - Queue batch 0 would re-dispatch it as P0.
- proposed edit: Close as implemented in c4e1a01, after confirming that CI on a runner without codameter reports 'SKIPPED'. Optionally open a small cleanup issue to delete the `__main__` runners.

## #153 Reproducible from a clean checkout: pinned data snapshot + fixtures
- verdict: **split** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Fixtures must carry their measurement support, units, QC flags and holdout labels (operational plan F1). Otherwise a downsampled fixture quietly changes support and the test is scientifically meaningless. Synthetic and observed fixtures must be distinguishable.
- problems:
  - The acceptance target `pixi run twin-gif` depends on `vs30-domain` (pixi.toml:179), which fetches data remotely, so it cannot pass offline as written.
  - Publishing a Zenodo/S3 snapshot needs credentials and a licensing decision (PRISM terms), which is a human task.
  - tests/fixtures does not exist; make_twin_gif.py reads about a dozen gitignored products.
- proposed edit: Split.
- (a) Agent-ready: commit a sub-1 MB fixture set under tests/fixtures with a manifest (source, version, units, support, QC, holdout, sha256), and add a `twin-gif-fixture` task with no remote `depends-on` that renders from fixtures. Acceptance: it passes in CI on a clean runner.
- (b) hold-human: publish the full derived-data snapshot with a DOI and add a `fetch-fixtures` task.

## #155 RNG determinism: single seeded generator + per-frame streams
- verdict: **rewrite** (verifier upheld); agent_ready: True; missing blockers: []
- physics: The prescribed fix does not achieve its own goal. Spawning `len(idx)` children assigns streams by position, so changing CADENCE changes `len(idx)` and frame k gets a different child stream. Streams must be keyed by absolute identity, for example `SeedSequence(seed, spawn_key=(frame_index_or_time, member))`. That keying is also what #191 needs for member streams.
- problems:
  - Mostly done already: src uses seeded generators (attribution.py:42, dvv.py:406/448, domain_gates.py:60, pilot_temporal.py:376), and only old/notebooks/make_digital_twin.py lacks a seed.
  - The real remaining defect is make_twin_gif.py:196-241: one RNG consumed inside `assimilate(k)` in frame order.
  - No acceptance criterion.
- proposed edit: Specify `src.utils.rng.stream(seed, *keys)` built on `SeedSequence` `spawn_key`.

Acceptance: `assimilate(k)` gives identical outputs for any shared frame k under CADENCE=1 and CADENCE=3, and the same helper supports a member key for #191.

## #156 Fetcher + assimilation tests (fixture-backed)
- verdict: **rewrite** (verifier upheld); agent_ready: True; missing blockers: [153]
- physics: The 'upsample mass invariant' is the wrong invariant. `upsample` in make_twin_gif.py:198-202 linearly interpolates a correction and sets edges to zero (`nan_to_num`), and linear interpolation does not conserve mass. Two checks are meaningful: (i) at well cells the upsampled fine analysis reproduces the coarse analysis increment to within interpolation error; (ii) the zero-correction edge band is quantified, since cells outside the coarse hull get no update even next to a well, which may itself be a defect.
- problems:
  - `assimilate` is a closure inside notebooks/make_twin_gif.py:204, so it cannot be tested until it is moved into src.
  - Has no acceptance criterion.
  - `blue_update` already has a synthetic test (tests/test_observability.py:268); what is missing is the end-to-end grid path and fetcher parsers (no tests/test_fetch_*).
- proposed edit: Move the inner `assimilate` into a src function.

Acceptance:
1. A mocked-response parser test for the NWIS or PRISM daily fetcher, covering units and missing-value handling.
2. An end-to-end synthetic-grid test asserting that the well-cell increment is preserved after upsampling (tolerance stated).
3. A test documenting the edge-band behaviour.

Add #153 to BLOCKED_BY (it needs the fixtures).

## #157 pixi: compatible-release bounds on the scientific core
- verdict: **keep**; agent_ready: True; missing blockers: []
- physics: Not applicable. This is still needed: pixi.toml:10-60 is still mostly '*'. The lock currently resolves numpy 2.4.3, pandas 3.0.2, xarray 2026.2.0, scipy 1.17.1 and scikit-learn 1.8.0, so the bounds must include these.
- problems:
  - Has no acceptance criterion.
  - xarray uses CalVer, so `<x+1` bounds do not apply.
- proposed edit: Acceptance:
- Upper bounds on numpy (<3), pandas (<4), scipy (<2), scikit-learn (<2) and zarr (pinned major).
- xarray gets a floor only, or a CalVer year window.
- `pixi lock` reproduces the current pixi.lock with no version changes, and CI passes.

## #204 [epic] Book/twin rewrite — codex editorial framework
- verdict: **hold-human** (verifier upheld); agent_ready: False; missing blockers: []
- physics: The notation unification is worthwhile: storage, head and depth to water, with D = z_s - h_wt stated once, 'GWL' retired from unqualified use, and an 'uncalibrated assumption' status label (Aug 2026 comment). The scale principle is correct.

The core acceptance criterion, status boxes derived from open/closed issue states, is unsound. Roadmap-review R6 shows closures such as #110, #114 and #120 do not establish that work was delivered, so status needs evidence records.
- problems:
  - The title change to 'The GAIA State2Hazard Twin' conflicts with README's 'GAIA Digital Twin of Soil' (README.md:1) and with #24's 'gaia-soil-reanalysis'. Three names need one human decision.
  - Partial work D1 (instructions and README claims) exists only on the unmerged 2026-09-10 operational-start branch.
  - Epic, so excluded from the queue.
- proposed edit: A human decides the product and repo name together with #24.

Replace the 'derived from issue states' criterion with 'derived from closure-disposition evidence records (implemented / validated / superseded / duplicate / negative result / withdrawn)', per R6. Add the 'uncalibrated assumption' label and the storage/head/DTW vocabulary. Merge the D1 branch first.

## #60 Epic: peer-review remediation (P0/P1/P2)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Not applicable as a tracker. Its assimilation principle (assimilate only ground or satellite observations) remains a sound governing rule.
- problems:
  - 15 checkbox mismatches. Closed but unticked: #35, #36, #37, #38, #39, #41, #42, #48, #53, #55. Ticked but still open: #45, #46, #51, #54.
  - The P0 header claims documentation is done, yet #40 is still open with one leftover.
- proposed edit: Reconcile: tick the closed issues. For #45, #46, #51 and #54, verify the implementation evidence and close them or untick them. Move the P2 forecast-path items (#56, #58) to their superseded or deferred dispositions. Close the epic once only #47, #49, #50, #52, #57 and #59 remain, re-parenting those to ROADMAP milestones.

## #40 P0: Reconcile TerraClimate consistency r = 0.94 vs 0.98
- verdict: **rewrite** (verifier upheld); agent_ready: True; missing blockers: []
- physics: The reconciled number (0.94 domain, 0.93 cell median, total-water bucket) is correctly framed as a shared-forcing consistency check, not validation (README.md:67, 402; docs/twin/02-evaluation-data.qmd:53).

One stale statement remains in the published HTML: docs/gwl_audit_framework.html still says 'r = 0.98 vs TerraClimate, r = 0.85 vs MERRA-2', and quarto-pages copies it to Pages unchanged (finding of the prior issue-40 run, docs/gaia-runs/issue-40). The 0.98 in docs/gwl_soil_moisture_demo.html is a different quantity (TerraClimate vs PRISM forcing agreement) but still says 'Hamon'.
- problems:
  - Body says 'addressed' while the work stays at global P0, so it would burn queue batch 4 (roadmap-review R9).
  - The leftover sits in hand-maintained committed HTML.
- proposed edit: Lower to P2 and narrow the scope: edit docs/gwl_audit_framework.html to 'r = 0.94 / 0.93 (shared-forcing consistency)', and change 'Hamon' to 'Hargreaves-Samani' in docs/gwl_soil_moisture_demo.html. Then close.

## #25 Verify references.bib integrity (zero fabricated DOIs)
- verdict: **hold-human** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Not applicable. The bibliography reviews note that 5 of the 9 documented DOI defects were registered DOIs for the wrong papers, which the CI resolve check from #158 cannot catch (ci.yml comment). Entry-level metadata matching is still needed, and a failed lookup must report 'unknown', not pass.
- problems:
  - Eight corrections are on the unmerged operational-start branch (B1). An agent working from main would duplicate them and conflict.
  - Queued in batch 30 alongside unrelated validation science (#109, #49, #47).
  - 'Zero fakes' has no machine-checkable definition.
- proposed edit: Hold until the B1 branch is merged. Then rewrite the acceptance: `check-dois-metadata` (pixi.toml:79) matches title, first author and year for all 107 entries; failed lookups are reported as UNKNOWN; and a ledger records the evidence for each entry.

## #24 Rename repository to gaia-soil-reanalysis
- verdict: **hold-human** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Not applicable.
- problems:
  - Renaming a GitHub repo needs admin rights and breaks Pages URLs and agent configuration. An agent must not attempt it, yet the queue includes it in batch 38.
  - The name conflicts with #204's 'State2Hazard Twin' and with README's 'GAIA Digital Twin of Soil'.
  - pixi.toml already uses `name = "gaia-soil-reanalysis"` (line 2), and README.md:5 already notes the rename is pending.
  - Pillar-1 wording in docs/gaia-conventions.md:214-226 is still the 'complementarity' framing, which the 2026-07-01 decision said to rewrite.
- proposed edit: Add a needs-human-decision label and remove it from the agent queue. The one agent-safe slice is a separate issue to rewrite the docs/gaia-conventions.md:214 Pillar-1 section to say 'this repo is the Pillar-1 reanalysis'.

## #18 EPIC: gaia-soil-reanalysis coupled subsurface state
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: []
- physics: The state table should read 'groundwater storage -> water-table head -> depth to water' (Aug comment). The dv/v differentiator still holds. The epic is now superseded in role by ROADMAP's operating-loop milestones.
- problems:
  - Children #19-#25 are listed as a priority order with no status. #20 is stale ('scaffold', per R6), #24 needs a human, and #25 is held.
  - Its flood note duplicates #73's.
- proposed edit: Either close it in favour of the ROADMAP milestone spine, re-parenting #19-#23 to v0.2/v0.6 milestones, or update the table wording and child statuses. Prefer closing: it adds a second, stale ordering.

## #64 LandLab export: wire dynamic bundle to real products + CLI + sigma + mask
- verdict: **close-done** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Every task is implemented: the CLI (pixi.toml:210; landlab_export.py:323), the sigma sidecars (lines 120-160), the confidence mask (78-86), the seasonal-high water table (58), `align_to_grid` and manifest native/export resolution (154-185), and the figure (pixi.toml:212). Commit 13eaf07 is 'feat(#64)'. Three scientific leftovers:
- The recharge sigma is a hard-coded 0.1·|mean| placeholder (landlab_export.py:319), an uncalibrated assumption shipped as if it were uncertainty.
- The water-table sigma combines RF and kriging in quadrature before #186's back-transform (line 198).
- Stock LandLab `LandslideProbability` takes a recharge distribution and transmissivity, not water_table__depth, so the exported DTW is consumed only through #128's closure.
- problems:
  - Queue batch 28 would re-dispatch completed work.
  - There is no actual `landlab.io.esri_ascii` load test; tests/test_landlab_export.py checks only the header.
- proposed edit: Close as implemented. Open a small follow-up, or attach to #65: tag recharge sigma as 'uncalibrated assumption' in the manifest, re-derive the water-table sigma after #186, and add a landlab-optional load test using `importorskip`.

## #65 Publish LandLab bundle as COG/Zarr + STAC (s3://cresst)
- verdict: **rewrite** (verifier upheld); agent_ready: True; missing blockers: []
- physics: Recording method provenance is right. The STAC item should also carry measurement support (90 m native vs export), the sigma method and an 'uncalibrated' flag for placeholder sigmas, plus a forward-compatible member dimension so #200/#193 can reuse it. src/io/stac_publish.py exists (make_stac_item at line 31), but landlab_export.py does not call it.
- problems:
  - Writing to s3://cresst needs credentials and is a production write; an agent cannot do it unattended.
  - Acceptance is phrased as 'discoverable', which is not testable locally.
  - Queued in batch 37 with unrelated validation issues (#72, #31, #29).
- proposed edit: Agent scope: emit a local STAC item and collection plus COG assets from `export_dynamic_bundle`, validated with `pystac` `validate()` in a test, with provenance fields (pedotransfer, transmissivity method, forcing source and cadence, sigma method, the uncalibrated flag). The upload to s3://cresst is a human-gated step. Align the field names with #200.

## Gaps (proposed new issues)

### Meteorological ensemble member source: construction, reforecast calibration, and dependence preservation
- milestone: v0.7 — Probabilistic nowcast and ensemble forecast; blocked_by: [136, 187]
- why: #191 requires calibrated FuXi ensembles, but FuXi in earth2studio is deterministic (src/data/fetch_earth2studio.py:149, `deterministic(...)`). No issue commissions perturbation versus lagged versus GEFS-initialized members, ensemble size and compute, a reforecast archive for spread and bias, or restoring dependence after quantile mapping (roadmap-review R8). Without this, #191 has nothing to propagate.

Decide and implement how atmospheric members are produced: initial-condition perturbation via earth2studio perturbation methods, lagged initializations, or GEFS/ERA5 initial conditions. Fix N_members against the Tillicum H200 budget. Build a reforecast archive (at least 3 winters, ERA5 initial conditions, because GFS initial conditions do not cover hindcast years) for lead-dependent quantile mapping against PRISM. Use years separate from verification.

After bias correction, restore spatial and P-T rank dependence with ensemble copula coupling or a Schaake shuffle.

Acceptance:
- Spread-skill ratio within 0.8-1.2 and PIT flatness on held-out winters, by lead 1-15.
- P-T rank correlation preserved within tolerance.
- The one-member limit matches the deterministic forcing.

### Mass-conserving orographic precipitation downscaler (FuXi 0.25 deg -> 90 m)
- milestone: v0.7 — Probabilistic nowcast and ensemble forecast; blocked_by: [136]
- why: #71 files this under the state-field downscaler registry (#31; src/models/downscale.py:102-226), which uses soil and terrain covariates and does not conserve the coarse-cell total. At 0.25 deg (about 28x19 km) the Cascade crest enhancement is unresolved (ROADMAP.md:126). Nothing owns a physically consistent precipitation downscaler.

Baseline: a monthly PRISM-climatology ratio, P_fine = P_coarse x PRISM_clim_fine / mean over the coarse cell of PRISM_clim_fine, which conserves the coarse total by construction. Stretch: a linear-theory orographic model (Smith & Barstad 2004) driven by FuXi winds and humidity, for event-dependent enhancement.

Acceptance:
- The coarse-cell total is conserved to 1e-6.
- On held-out AR days, daily 90 m totals improve on bilinear in CRPS against PRISM 800 m and against independent gauges.
- The manifest records native and delivered resolution.

### Forecast-mode PET and lead-0 hindcast-to-forecast continuity
- milestone: v0.7 — Probabilistic nowcast and ensemble forecast; blocked_by: [136]
- why: The FuXi adapter emits only `precip_mm` and `tmean_c` (fetch_earth2studio.py:154-163). Hargreaves-Samani needs Tmax/Tmin, so forecast PET is undefined, while hindcast PET is Hargreaves-Samani from PRISM (fetch_prism_daily.py:42). Switching PET source or formula at lead 0 injects a step change into the calibrated bucket. Stale 'Hamon' text also remains at src/models/forecast.py:12 and src/data/stage_mvp_window.py:9.

Have the FuXi adapter emit daily Tmax/Tmin from 6-hourly t2m. Four samples per day bias the diurnal range low, so estimate and correct that bias against PRISM. Compute Hargreaves-Samani PET identically in both hindcast and forecast modes, and fix the stale Hamon docstrings.

Acceptance: on overlapping days, forecast-mode PET agrees with PRISM Hargreaves-Samani PET to within a stated bias, and the soil state shows no discontinuity at lead 0 in a replayed-reanalysis pseudo-forecast.

### Align FuXi daily aggregation with PRISM's 12-12 UTC day
- milestone: v0.7 — Probabilistic nowcast and ensemble forecast; blocked_by: []
- why: fetch_earth2studio.py:154 resamples tp06 into daily bins by lead time from a 00Z start (00-24 UTC). PRISM daily totals run 12-12 UTC. Bias correction and #195 scoring would carry a 12-hour phase error that inflates day-1 error and misattributes storm timing.

Aggregate the 6-hourly tp06 into 12-12 UTC windows (or interpolate the PRISM day definition) whenever it is compared with or calibrated against PRISM. Record the day-boundary convention in the forcing contract (#187).

Acceptance: a unit test with a synthetic 6-hourly series checks the window boundaries, and the documented day convention appears in the dataset attributes.

### Vs30(t) uses thickness weighting instead of travel-time weighting
- milestone: Water budget: vadose-zone physics & calibration; blocked_by: []
- why: src/models/forecast.py:181-182 weights the vadose band by d/30. Vs30 = 30/sum(h_i/V_i), so a fractional velocity change carries the travel-time fraction (h_i/V_i)/sum(h_j/V_j). For a 1 m root zone at 200 m/s over 400 m/s, the correct weight is about 0.065, not 0.033. Vs30 storm sensitivity is underestimated by about 2x, and #191/#193 would carry the error into hazard members.

Replace `w_vadose = d/30` with travel-time weights computed from the baseline velocity profile, using vs30_base and the dvv.py depth kernels, or a two-layer approximation when no profile is available.

Acceptance:
- Analytic two-layer test: the computed Vs30 change matches exact recomputation of 30/sum(h/V) to 1e-6 for small perturbations.
- Document the change in forecast-mode Vs30 sensitivity.

### Fix and validate the FuXi adapter call path before the GPU run
- milestone: v0.7 — Probabilistic nowcast and ensemble forecast; blocked_by: []
- why: fetch_earth2studio.py:149 passes `io=None` to `earth2studio.run.deterministic` and then calls `.to_xarray()`. Line 143 logs a GraphCast message even for FuXi. The module calls itself 'NOT YET VALIDATED'. Burning H200 time on #136 with an unverified call path is wasteful.

Use an explicit in-memory IO backend (for example `XarrayBackend`) and fix the log message. Add a CPU smoke test that mocks the prognostic model, a 2-step run, and checks tp06 unit handling and the shape of the daily aggregation.

Acceptance: the mocked test passes in CI without a GPU, and an optional real run on Tillicum is documented.

## Verifier extra problems

- Holds are not enforceable on origin/main. scripts/gaia_group_issues.py on main (435445f) excludes only 'epic'. The HOLD_LABEL ('needs-human-decision') exclusion exists only on the unmerged origin/docs/soil-twin-audit-and-plan-revision-2026-09-10 branch. Every 'hold-human' verdict (#24, #25, #204) and every 'label deferred' proposal (#58, #203) does nothing to the queue until that branch merges or the scheduler is patched.
- BLOCKED_BY is a hard-coded Python dict (gaia_group_issues.py:86-102). Issue-body 'Depends on' lines are not parsed. Every 'add to BLOCKED_BY' and every split (#193a/b/c, #195a/b, #153a/b) needs a script PR with the new issue numbers, or the new issues dispatch immediately.
- Paused work is still dispatched. ROADMAP.md:129 marks v0.3 Vs30 densification paused by the user, yet the queue simulation runs #81-#86 in batches 13-14. This bears on #193's 'degenerate Vs30 member' note.
- #136 (the FuXi run plus bias correction that the whole forecast lane depends on) sits in the 'Hazard: LandLab landslide handoff' milestone (batch 20), not v0.7. It needs re-milestoning, and the forecast-lane ordering in #73 depends on that.
- The existing hindcast and forecast driver (old/notebooks/make_forecast_leadtime.py:97-115, invoked by pixi 'hindcast' at pixi.toml:200) area-averages the forcing over the whole domain and broadcasts it to 90 m. Without forcing pet_mm it uses a constant 0.6 mm/day PET. Any agent doing #59, #70 or #136 that reuses this path produces spatially uniform forcing with no orography. It should be called out explicitly in those issue bodies.
- There is more stale Hamon text than the audit lists: pixi.toml:104 ('ppt+tmean→Hamon PET'), make_forecast_leadtime.py:100 ('PRISM ships a real Hamon PET'), and docs/gwl_hybrid_framework.html plus old/docs/gwl_hybrid_framework.qmd and old/docs/gwl_soil_moisture_demo.qmd.
- fetch_earth2studio.py documentation is stale. The module docstring and argparse description still say GraphCast and 'write the forcing netCDF' (lines 1, 29-30, 182), but the code writes Zarr and prefers FuXi. It also runs earth2studio deterministic() only (line 149), so no member source exists in code. That confirms R8's gap and contradicts any reading of #191 as near-ready.
- #155 and #156 are both queued in batch 5 and both refactor make_twin_gif.py:196-241 (rng and assimilate). That is a merge-collision risk. Sequence them, or merge them into one issue that moves assimilate into src with keyed RNG streams.
- pixi.toml:175-178 documents that make_twin_gif reads prism_daily_2025-09_2026-06.zarr, but no pixi task produces that filename. stage_mvp_window.py:91 writes it, under a Kopah root. Any reproducibility work (#153) must reconcile this producer/consumer mismatch.
