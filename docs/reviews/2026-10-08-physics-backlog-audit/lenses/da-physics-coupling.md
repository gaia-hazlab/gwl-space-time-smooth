# Lens: da-physics-coupling

# Is the planned data assimilation consistent with the twin's hydrology? A data-assimilation scientist's assessment

Scope: #187, #188, #189, #192, #194, #161–#170, #186, #198 and #226, checked against the hydrologic state that origin/main (435445f) actually carries. All code citations refer to the origin/main checkout. Probes ran read-only, from scratch scripts in `wf/da/` (mb.py, ident.py, probes.py).

## 1. Bottom line

The DA design documents (#187, #188, #192, #194, docs/probabilistic-nowcast-forecast-roadmap.md) are good textbook DA:
- a storage-based state;
- an ensemble that cycles from one analysis to the next;
- a separate ledger for DA increments;
- withheld-sensor value added.

The problem is the model they would sit on. It does not conserve water. It has no vadose store and no lateral exchange between cells. Its specific yield, recharge and river-sink strength can only be told apart with a gauge flux, not with wells alone. Its only "assimilation" today is a reference-mismatched, non-cycling BLUE fed by fabricated and self-generated observations.

The GAIA queue makes this worse. It runs the DA P0 issues (#161, #162, #163, #198) in batch 1, before the water-budget batches (#172–#175 in batch 7; #137 and #131 in batch 8) and before the state contract #187. #162 asks for a Kalman/RTS smoother with mechanical damage and disturbance states, which contradicts #188's "hydrology first". #226 (GNSS loading) is queued in batch 9 although its own body says it is blocked by #187 and #189.

The first real-data cycling pilot should be narrow:
- One small gauged basin.
- One state: head (equivalently storage) anomaly, with S_y fixed per cell.
- One observation type: per-well anomalies from continuous-recorder wells screened at the water table.
- The gauge and the soil probes held back for validation.
- No dv/v, SMAP, GRACE, GNSS or Stage-3 maps.

## 2. What the hydrologic state actually is

`coupled_water_budget` (water_budget.py:119-284) carries two stores per cell:
- a root-zone store S = θ·z_r;
- a head anomaly h for a linear-reservoir water table, with wt = d0 − h (:157, :215, :279).

Snow sits outside the budget, in forecast.liquid_input. There is no vadose store between the root base and the table, no interflow store, and no transfer between cells. `topmodel_watertable` is a static prior (:287-297). `accumulate_runoff` multiplies runoff by (1 + normalised accumulation), which can double it, so it is not mass-conserving (:300-311).

**Closure is false.** The docstring claims mass is "conserved by construction" (:30-33). But capillary rise is added to S (:217-219) and never debited from h (:266). I re-ran the prior agent's probe against origin/main (300 daily steps, three cells):

| Configuration | Closure residual P − out − ΔS − S_y·Δh | Matches |
|---|---|---|
| Legacy recession | 0, −42.8, −101.1 mm | exactly −Σ capillary rise |
| HAND sink on | 0, −101.8, −63.1 mm | exactly −Σ capillary rise |

On the valley cell the water table reached −0.01 m, i.e. above the land surface. Three other features break bounds or mass:
- `np.clip(S, Swp, Ssat)` (:251) is a further bound-enforcing step that does not conserve mass.
- `gw_recess` is 0 wherever HAND ≤ d0 (:195-196), so those cells have no groundwater sink.
- The river-sink coefficient is anchored on the Stage-1 baseline d0 through head0 = HAND − d0 (:193). An error in d0 therefore changes the dynamics, not just the offset. Example: HAND 60 m with d0 20 m versus a true 38 m gives head0 of 40 m versus 22 m, a 1.8× error in sink strength. The Stage-1 pooled block-CV RMSE is 18.5 m (docs/reviews/peer_review.md:32).

**Consequence for DA.** #187 and #188 rightly demand a DA-increment ledger kept separate from physical fluxes. That ledger only means something if the open-loop model closes to machine precision. Today the model's own leak (−43 to −102 mm per 300 days on shallow-table cells) is the same order as the DA increments the filter would make. A 1σ head increment (σ = 0.5 m, observability.py:698) is 150 mm of water at S_y = 0.30 (water_budget.py:62), or 50 mm at S_y = 0.10. A ledger cannot separate model leakage from DA correction. So #172 (and the valley-sink fix) are hard prerequisites for #188, not for "release". #188's own text only says "release depends on #171/#172/#137".

## 3. Storage versus head: when it matters

`hydro_state.water_table_head_from_storage` (hydro_state.py:158-197) correctly diagnoses Δh = ΔS/S_y and propagates σ_Sy.

If S_y is a fixed per-cell constant, S = S_y·h is an invertible linear map. The Kalman/EnKF analysis is then equivariant: updating S and updating h give the same answer. So the debate between #187's storage state and the roadmap's "#188 is scoped to … GWL (head) and soil moisture (θ)" (roadmap :215-221) is moot for a pilot.

The distinction becomes real in three cases:
1. **The ledger must be in mm of water.** Increments ΔS_DA should be logged, not Δh.
2. **S_y is uncertain or in the state.** Then H(x) = S/S_y is nonlinear. "Wells are linear in the state" (roadmap :217) stops being true and the EnKF linearises.
3. **A vadose or transit store exists.** Then the partition of an increment between S_root, S_vadose and S_gw is set entirely by ensemble cross-covariances, which #131/#172 have not built yet.

The contract should say this explicitly. As written, #187 and the roadmap disagree on what the state is, and an agent will pick one.

**Bounds.** `blue_update` (observability.py:1217-1263) has no bound handling. The twin applies unclipped increments to both θ and rise (notebooks/make_twin_gif.py:229, :245). I ran a stochastic-EnKF probe: 40 members, θ forecast 0.43 ± 0.03, a probe reading 0.45 ± 0.03, θ_sat 0.46. On average 11.9% of members ended above saturation, and clipping removed about 1 mm per analysis per metre of root zone. Clipping is a systematic one-sided mass sink at wet states. It must go in the ledger, or be avoided with a transformed variable (logit of saturation, or a Gaussian anamorphosis).

A related loose bound: `SPECIFIC_YIELD_RANGE` allows up to 0.6 (hydro_state.py:87), which is above the porosity of most aquifer materials. It does not guard against the S_y ≈ porosity compensation identified in #137.

## 4. Mass-conserving increments: what to require

A strictly mass-preserving EnKF is wrong here. That would mean projecting increments onto the null space of 1ᵀ, i.e. pure redistribution. The dominant error is in precipitation and forcing, so the total amount of water must be allowed to change.

What is right, and what #187 should state as acceptance:
1. Increments are allowed but ledgered per compartment in mm.
2. The open-loop closure residual is ≤ 1e-6 mm per step before any cycling test.
3. Any bound projection or clip is logged as its own ledger term.
4. The time-mean increment is a bias diagnostic. A persistent non-zero mean increment means model bias, and must not be absorbed by inflation (#192 already says "do not use inflation to hide biased dynamics").
5. Longer term, prefer correcting forcing (perturbing or smoothing precipitation) to dumping increments into the state.

## 5. Observation operators at native support

**Wells.** The gated operator `water_table_point_footprint` (observability.py:945-978) is correct and refuses `aquifer_head` and `unknown` wells. No production or notebook path calls it:
- `make_twin_gif.py` uses the ungated `point_footprint` and averages all wells in a 3.6 km cell into one datum.
- `gwl_dynamic.py:94-111` krige every well's window-mean anomaly with no `measurement_target` filter.

The classifier has a physical blind spot. A screen whose top is deeper than 30 m is labelled `aquifer_head` (well_hydrostratigraphy.py:186-188, SHALLOW_MAX_M = 30 at :49). Upland water tables deeper than 30 m therefore cannot be water-table observations, even when the screen brackets them. The docstring's "not entirely below the observed water level" test is not implemented.

**The existing BLUE is internally inconsistent.**
- Reference mismatch: the model's "rise" is d0 − wt_depth, relative to the run start on 2025-09 (make_twin_gif.py:207). The well datum is site_mean − v, relative to the site's all-record mean (:221). Around the September minimum this is an innovation offset of about A/2 ≈ 0.5 m for the observed 1.06 m amplitude, i.e. 1σ of B.
- Fabricated observations: wells that did not report that month get their monthly climatology assimilated at WELL_VAR = 0.15² (:215-221).
- Self-generated dv/v: "observations" are drawn from the forecast itself (:225, :241), so their innovations are pure noise.

None of this is evidence of a working observing system. #194 must not inherit any of it.

**Soil probes.** `fetch_insitu_sm` weights the 2/4/8/20-inch sensors by depth and uses `sum(min_count=1)` without renormalising (fetch_insitu_sm.py:77-79). When a sensor drops out, θ falls by that sensor's weight; losing the 20-inch sensor removes 59% of the value. That is a step artefact that will look like a large innovation.

The model has a single bucket over z_r of 0.1–2 m. A 0–50 cm probe anomaly is injected 1:1 as a root-zone anomaly (make_twin_gif.py:239). A depth-weighting operator, or an explicitly larger representativeness R, is required.

**SMAP and NISAR.** These measure 0–5 cm (fetch_smap.py:3, :124) and the model has no surface layer. H = θ_root is a representativeness error that depends on state, not white noise. SMAP is also fetched as monthly means, which removes the information carried within the provisional 5-day decorrelation time (observability.py:770). These streams cannot enter #188 before a surface-layer or exponential-filter operator exists. #29 also proposes to "calibrate/bias-correct θ against SMAP", which would consume the only independent θ check.

**Gauges.** STREAMS registers "USGS gauges" as observing `("gwl",)` with a 5 km footprint (observability.py:894). The checkerboard test uses an equivalent-circle footprint on head (docs/twin/04-assimilation.qmd:523-525). Both are category errors. A gauge measures a routed, time-lagged basin integral of runoff + interflow + baseflow fluxes (water_budget.py:33), and the model has no routing. A gauge operator needs:
- a basin mask;
- accumulation over a time window with a unit-hydrograph lag;
- an ensemble-evaluated flux, not a linear footprint on h.

Until then, gauges belong in calibration and validation.

**Forcing data in the state-observation catalog.** GHCN-Daily, NOAA Stage IV, and GNSS-TEC/ZTD precipitable water are listed as observing gwl or soil_moisture (observability.py:899, :903, :907). These are forcing (atmospheric) data. They belong in the forcing ensemble (Q, and #32/#71), never as rows of G.

**GRACE and GNSS (#226).** The domain is 141 × 170 km, smaller than GRACE's ~300 km effective resolution, so GRACE gives at most one leakage-contaminated number per month. For GNSS I used a Boussinesq disk load (E = 75 GPa, ν = 0.25). Over the domain's equivalent 87 km radius:

| Load | Vertical displacement at centre |
|---|---|
| 100 mm water over 87 km radius | 2.1 mm |
| 300 mm water over 87 km radius | 6.4 mm |
| 300 mm water over 10 km radius | 0.7 mm |

Daily vertical GNSS noise is a few mm. GNSS therefore constrains domain-aggregate TWS, dominated by snow and by loads outside the domain. In lowland confined aquifers, poroelastic deformation has the opposite sign. GNSS does carry one useful identifiability lever, covered in §6. It is a validation/aggregate constraint, gated on a credible snow model (#100) and on #187/#189. That gating is stated in #226's body but missing from `BLOCKED_BY` (gaia_group_issues.py:87-104).

**dv/v.** The linear gain K_SAT = 5e-4 per metre (make_twin_gif.py:77) means 1 m of head gives 0.05% dv/v. With noise of order 0.01–0.05%, SNR is about 1–5 per metre. But the gains are uncertain by about an order of magnitude (#45), and the forward and inverse operators differ (#198). The first role of dv/v is as a target for calibrating its own petrophysical gain against co-located screened wells. Only after that can it be a head observation. dv/v belongs last in the chain.

There is also a conflict between documents. The roadmap says dv/v "enters #188 … through its linearized k_sat Δh / S_θ Δθ coefficients" (roadmap :219-221). #198 (P0) says to retire exactly those gains from the operational assimilation path. #165 (put the gain into G) is a third, partly overlapping prescription. An agent working these in different batches will produce contradictory code.

## 6. Identifiability: S_y, recharge and lateral flux

Analytically, the head equation is h ← h + R/S_y − [HAND − d0 + h]₊·(R_ref/S_y)/head0 (water_budget.py:266, :195-196, :271-272). It is invariant under (S_y, R, R_ref) → c·(S_y, R, R_ref), apart from the saturation-excess term S_y·wt (:230), which is inactive on deep tables. Baseflow = S_y·drop (:278) scales by c. So heads identify only R/S_y and R_ref/S_y, and an absolute flux or storage observation is needed to set the scale.

> **Correction 2026-10-09 (C5; Codex review of PR #229, see `../2026-10-09-pr229-codex-response.md`).** The condition numbers in this table are **unreproduced**. The groundwater Jacobian script was written to `wf/da/ident.py` and later overwritten by the da-estimator auditor's #169 healing-basis probe of the same name; the archived `probes/da/ident.py` is that #169 probe. The verifier's `probes/verify-da-physics-coupling/sub.py` reads the lost file and fails. The analytic scaling argument above stands on its own; do not use the numbers below as issue gates until a pinned probe recomputes them.

I computed finite-difference Jacobians of `coupled_water_budget` over two years of synthetic seasonal forcing (ident.py), with respect to log S_y, log R_ref, a log precipitation multiplier and log K_a:

| Observable | Condition number | Notes |
|---|---|---|
| Head anomaly alone | 4.4e4 (ridge), 1.8e4 (mid-slope) | cos(R_ref, P-multiplier) = −0.98 / −0.97 |
| Discharge alone | ≈ 4.5–4.8 | |
| Head anomaly + Q | ≈ 14–17 | |
| θ | — | Jacobian exactly zero for S_y, R_ref and K_a wherever the table is deeper than z_r + 1 m |

The θ result means probes and SMAP carry no information about groundwater parameters. The θ–h cross-covariance an EnKF learns will come only from shared forcing perturbations, and right now it is a same-step coupling because recharge "teleports" to the table (#131).

Implications:
1. **Do not augment S_y in the first cycling pilot.** State-augmented S_y with heads only is ill-posed. If augmentation is wanted, augment a precipitation or recharge multiplier, which is the dominant error source, together with gauge data.
2. **Calibration and DA should share data roles explicitly.** #137's three-knob exactly-determined fit must stay out of the DA pilot's withheld set.
3. **A domain-scale effective S_y needs a storage-volume observation** (gauge recession volume, or GNSS/GRACE TWS minus SWE) combined with well amplitudes. That is the scientific case for #226, not cell-scale storage.
4. **The B/Q/R cross-covariances #192 would tune depend on #131/#172.** Tuning them first is wasted effort.

## 7. What the statistical Stage 1–3 GWL (RMSE 18.5 m) does and does not offer

- Stage 1 sets d0, the reference and the sink anchor. Its error is mostly a static spatial bias. That bias is 1369 times larger in variance than the dynamic anomaly prior (18.5² / 0.5²).
- `prior_calibration.py` fits a purely spatial Matérn to out-of-fold static residuals (prior_calibration.py:8-19, :223-287). That is the right covariance for a static-offset (bias) state. It is the wrong one for the dynamic B or Q.
- #192 says "estimate … prior correlation scales from held-out residuals/variograms". An agent following that literally would inflate the dynamic σ about 37×, producing head increments of ~18 m, i.e. ~5.5 m of water at S_y = 0.3.

The contract should carry two separate things:
- a static per-site or per-field offset (or assimilate per-well anomalies only, as the pilot proposes);
- the dynamic anomaly, with B and Q from forecast-residual statistics.

Stage-3 kriged fields and the `gwl_dynamic` kriged anomalies are interpolations of the same wells. Assimilating them as pseudo-observations alongside the wells double-counts. They should initialise B and the mean, never enter y.

`anchor.assimilate_points` (anchor.py:53-90) multiplies precision by a distance weight and ignores the observation–observation covariance. I compared it with `blue_update` at the same σ = 0.5 m, L = 12 km and σ_o = 0.15 m, for a cell 5 km from the wells:

| Wells | Anchor posterior σ | BLUE posterior σ | Anchor overconfidence |
|---|---|---|---|
| 1 | 0.149 m | 0.299 m | 2× |
| 10 co-located | 0.049 m | 0.277 m | 5.6× |

#28 proposes extending this path to SNOTEL θ, outside the #187 contract.

## 8. Ordering errors in the DA chain (GAIA queue)

From queue_sim.jsonl and gaia_group_issues.py:

1. **The DA P0 batch runs before the hydrology and contract issues.** Batch 1 is #198, #163, #162, #161, run before the water-budget batches (7–8) and before #187.
   - #162 builds an augmented [hydrology, D, Φ] Kalman/RTS smoother. That contradicts #188 ("start with hydrology only") and precedes the identifiability gate #169.
   - #161's "Kalman propagation" duplicates #188.
   - #198 needs a depth-resolved θ(z) that does not exist until #172/#131.
   - Fix: add `BLOCKED_BY` entries 161 → [187], 162 → [188, 169], 198 → [172, 187]. Alternatively, re-scope #161 into #188 and close it.
2. **#226 is not held** despite "Blocked by: #187, #189" in its body. It runs in batch 9.
3. **#164–#168 (batch 10) precede the #198 operator decision.** #165 and #198 prescribe incompatible treatments of the petrophysical gain.
4. **#187 is blocked by epic #171.** Epics are never work items (gaia_group_issues.py:178), so the whole chain stalls until a human closes #171, which also contains #176/#177/#225/#227. It should block on #131, #137 and #172 directly.
5. **Prerequisites for #189's well operator are not linked.** #9/#46 (aquifer screening) and #6 (continuous recorders) are unlinked rank-3 batches (11, 12, 29).
6. **#28 and #29 build parallel non-cycling "assimilation" paths** that consume SNOTEL and SMAP before #189 assigns permanent assimilate/validate roles.
7. **The `needs-human-decision` label is not honoured as a hold.** #163 and #186 carry it but are queued in batches 1–2. The label is only applied after the fact in gaia_run_queue.sh:582.
8. **Stale line citations will misdirect agents.** #161 cites observability.py:89-103 and :183 (lagged_observation is now :826). #162 cites :276-318 (blue_update is :1217). #165 cites :165 and :183 (now :923 and :981). #170 cites :215 and :321-330 (now :995 and :1266).

## 9. Minimal real-data cycling pilot: what to assimilate first

**Preconditions, as gates:**
- #172 capillary debit plus the HAND ≤ d0 sink fix, with an open-loop closure test passing at ≤ 1e-6 mm per step;
- #89 calibration in daily mode;
- #186 units fix;
- a fixed per-cell S_y from #137 (not augmented).

**Domain.** One small gauged basin that has at least 3–5 continuous-recorder wells with `measurement_target == "water_table"`, at least one SNOTEL/SCAN probe and one USGS gauge.

**State.** A per-member head anomaly h (logged as S_y·h in mm) plus S_root. Forcing ensemble from perturbed PRISM precipitation and temperature; no parameter augmentation.

**Assimilate first.** Daily or weekly per-well head anomalies from screened continuous recorders only:
- each relative to that well's own mean over the pilot window, compared with the model's mean over the same window, so the 18.5 m static bias cancels;
- R = instrument error + representativeness error (#7);
- no climatology infill;
- localisation by distance within the hydrogeologic domain.

**Withhold for validation.**
- the gauge (Q, BFI): does assimilating heads degrade discharge? This is the physical-consistency test of the increments;
- the probes;
- one or two wells, to measure CRPS gain over open loop (#194).

**Report.**
- the increment ledger: mean and seasonal increment per compartment, as a model-bias diagnostic;
- innovation statistics: mean, NIS and spread–error.

**Second step.** Add probe θ through a depth-weighted operator, with the dropout bug fixed.

**Later.** Add a precipitation multiplier constrained by the gauge, then SMAP via a surface operator, then dv/v once its gain is calibrated against wells, then GNSS/GRACE as aggregate validation.

**Never assimilate** Stage-3 maps, climatology-infilled wells, or self-generated dv/v.

## 10. Uncertainty in this assessment

- The identifiability Jacobians use synthetic forcing on two archetype cells. Condition numbers will vary with real forcing, but the analytic (S_y, R, R_ref) invariance does not depend on forcing.
- The GNSS numbers are a first-order half-space estimate, not a Farrell layered-Earth Green's function.
- The ~0.5 m reference offset in the twin BLUE is inferred from the observed 1.06 m amplitude and a September start, not measured with the live NWIS parquet, which is not in the checkout.
- The EnKF bound probe is illustrative of one wet-state configuration.

## Claims (with adversarial verdict)

- **da-physics-coupling-1** [critical] [partially] The coupled water budget does not conserve mass: capillary rise is added to the root store but never debited from groundwater head, so the open-loop closure residual equals minus the cumulative capillary rise.
  - evidence: water_budget.py:217-219 (S += cap_eff) vs :266 (h only += rech/Sy); docstring claims closure at :30-33. Probe wf/da/mb.py on origin/main, 300 daily steps: residual P-out-dS-Sy*dh = [0,-42.8,-101.1] mm (legacy) and [0,-101.8,-63.1] mm (HAND sink), identical to sum(cap_rise).
  - issues: #172 must be a hard BLOCKED_BY prerequisite of #188 (not only #187/release); add an acceptance test 'open-loop closure <=1e-6 mm/step' to #172 and #187.
  - verifier: Physics confirmed: water_budget.py:219 adds cap_eff to S, :266 raises h only by rech/Sy, and nothing debits h for capillary rise, so the docstring's closure claim at :30-33 is false. Re-running wf/da/mb.py on origin/main reproduces residuals of [0,-42.8,-101.1] mm (legacy) and [0,-101.8,-63.1] mm (HAND), equal to sum(cap_rise). That is about 2-4% of P over 300 d, and only in cells whose table is within z_r+1 m. Not new: #172 already states this almost word for word ('capillary rise pulls from a shallow table into S (:217-219) but never debits head'). The proposed fix is redundant: BLOCKED_BY[187] already contains 172 (gaia_group_issues.py:88) and 188 is blocked by 187, so #172 already holds #188 back transitively. The acceptance-test suggestion is good. 'Critical' overstates a few-percent, shallow-cell-only leak.
- **da-physics-coupling-2** [major] [partially] DA increments of the size the current prior implies are the same order as the model's own mass leak, so a DA-increment ledger cannot distinguish analysis correction from model leakage until closure is fixed.
  - evidence: Prior sigma 0.5 m (observability.py:698; make_twin_gif.py:78) x Sy=0.30 (water_budget.py:62) = 150 mm water per 1-sigma increment (probes.py); leak 43-102 mm per 300 d (claim 1).
  - issues: #187/#188: ledger acceptance requires closure gate first; record clip/bound projections as separate ledger terms.
  - verifier: The arithmetic is right: 0.5 m (observability.py:698, make_twin_gif.py:78) x Sy 0.30 = 150 mm. But it compares one 1-sigma increment with a leak summed over 300 days. Per weekly analysis the leak is about 1-2 mm, two orders of magnitude below a typical increment, so a per-cycle ledger could tell them apart. The leak is also systematic and limited to shallow-table cells, so only a seasonal mean-increment ledger in those cells is confounded. The conclusion 'cannot distinguish' is too strong. 'Fix closure first and ledger clip terms' is still sound.
- **da-physics-coupling-3** [major] [confirmed] Cells with HAND <= d0 have zero groundwater sink, and the sink coefficient depends on the Stage-1 baseline d0, so baseline error (18.5 m RMSE) corrupts dynamics, not just the static offset.
  - evidence: water_budget.py:193-197 gw_recess=(r_ref/Sy)/[HAND-d0]_+ and 0 where head0<=1e-3; drop=to_river*gw_recess (:271-272). Example HAND 60, d0 20 vs true 38 -> coefficient 1.8x off. Probe: valley table reached -0.01 m (above surface).
  - issues: Add to #175/#172: sink must exist for HAND<=d0 cells and must not be anchored on the uncertain baseline; #187 should list d0 as an uncertain parameter, not a constant.
  - verifier: Confirmed at water_budget.py:192-197: head0 = clip(HAND - d0), gw_recess = 0 where head0 <= 1e-3, and drop = to_river*gw_recess at :271-272. The coefficient scales as 1/(HAND - d0), so HAND 60 with d0 20 vs 38 gives 40/22 = 1.82x. The probe's valley cell (HAND 1, d0 3) ends at wt = -0.01 m, i.e. the table above the surface. A further point: the implied e-folding time Sy*head0/R_ref is also set by d0, so baseline error corrupts the timescale as well as the equilibrium.
- **da-physics-coupling-4** [major] [partially] Head-only observations cannot identify Sy separately from recharge and river-sink strength: the head equation is invariant under (Sy, R, R_ref)->c*(Sy,R,R_ref) except the inactive saturation-excess term; baseflow scales by c.
  - evidence: water_budget.py:266, :195-196, :271-272, :278. Jacobian probe wf/da/ident.py: head-anomaly condition number 4.4e4 (ridge) / 1.8e4 (mid), cos(R_ref,P-mult)=-0.98/-0.97; Q alone cond ~4.5; head+Q cond ~14-17.
  - issues: #188/#192: forbid Sy state augmentation in the first pilot; if augmenting, augment a precipitation/recharge multiplier constrained by gauges. #137: calibration must use a flux (gauge) or storage observation to pin absolute Sy.
  - verifier: The invariance is exact for the head equation: dh = R/Sy - (R_ref/Sy)*to_river/head0 (:266, :195, :272). I reproduced the cited numbers (cond 4.4e4 / 1.8e4, cos(Rref,Pm) = -0.98 / -0.97, Q cond ~4.5, joint cond 14-17). Subsetting the same Jacobian (wf/verify-da-physics-coupling/sub.py) shows the near-singularity comes from Ka, the recharge-partition coefficient: {Sy,Rref,Ka} cond 3.7e4 / 1.5e4. {Sy,Rref,Pmult} is only 37 / 27, and {Sy,Rref} with known forcing is 1.7. So head can separate Sy from R_ref when recharge is known; the degeneracy is with the interflow/recharge split. That also argues against the claim's suggestion to augment a recharge multiplier, which is exactly the degenerate direction unless gauges constrain it. The point that a flux observation is needed holds.
- **da-physics-coupling-5** [major] [confirmed] Soil-moisture observations carry zero information about groundwater parameters or state through model dynamics wherever the table is deeper than root zone + 1 m fringe; theta-h ensemble cross-covariance can come only from shared forcing perturbations.
  - evidence: ident.py: d(theta)/d(logSy, logRref, logKa) column norms exactly 0 for ridge and mid cells; coupling only via capillary rise (water_budget.py:105-116, reach=z_r+1 m).
  - issues: #188: document that theta->h updates are forcing-correlation driven; #192: tune cross-covariance only after #131 adds vadose lag (then use a lagged smoother/transit store).
  - verifier: Reproduced: theta Jacobian column norms are exactly 0 for logSy, logRref and logKa in both cells (d0 = 20 m and 6 m, both deeper than reach = z_r+1 = 2 m; :114). Ka only splits drain after S is debited, and the saturation-excess deficit Sy*wt_depth (more than 600 mm) never fires at these depths. Minor nuance: cross-covariance can also come from shared perturbed parameters (theta_fc, drain tau, PET), not only from forcing.
- **da-physics-coupling-6** [major] [confirmed] The existing wet-season BLUE compares inconsistent reference levels: model rise is relative to the run start (d0) while well data are relative to each site's all-record mean, giving an innovation offset of roughly half the seasonal amplitude (~0.5 m = 1 prior sigma).
  - evidence: notebooks/make_twin_gif.py:207 rise_f = d0 - wt_depth vs :221 site_mean[sid] - v; observed amplitude 1.06 m (water_budget.py:58-61); SIG_GWL=0.5 (:78).
  - issues: #189: well operator must define the anomaly reference identically for model and data (same-window means); #194 must not reuse make_twin_gif outputs as evidence.
  - verifier: make_twin_gif.py:207 rise_f = d0 - wt_depth, where h = 0 at the run start (PRISM 2025-09, :107). Data are site_mean - v at :221, with site_mean the all-record mean at :163. A run starting at the end of the dry season puts the model at ~0 while the data sit near -A/2, so the offset is about 0.5 m, roughly 1 prior sigma (SIG_GWL 0.5).
- **da-physics-coupling-7** [major] [confirmed] The twin BLUE assimilates fabricated observations: wells that did not report in a month have their monthly climatology injected with live-reading error variance (0.15 m)^2, and dv/v 'observations' are generated from the forecast itself.
  - evidence: make_twin_gif.py:215-221 (climo.get fallback, WELL_VAR at :80); :225 and :241 d_dvv/d_th = gain*(Gs@prior)+noise.
  - issues: #189 acceptance: no climatology infill as observations; synthetic data flagged and excluded from any value-added metric (#194).
  - verifier: Confirmed at :215-221: when a well has no live value, climo.get((sid, mo)) is injected with nv = WELL_VAR = 0.15^2 (:80, :224). Also confirmed at :225 and :241: d_dvv = K_SAT*(Gs@rise_c) + noise is built from the forecast itself, so its innovation is pure noise and only shrinks variance.
- **da-physics-coupling-8** [major] [confirmed] The aquifer-gated well operator exists but no pipeline uses it; the twin and gwl_dynamic assimilate/krige all wells regardless of measurement_target.
  - evidence: observability.py:945-978 water_table_point_footprint only referenced by tests and well_hydrostratigraphy.py; make_twin_gif.py uses point_footprint; gwl_dynamic.py:94-111 krige all wells.
  - issues: #189 must wire measurement_target gating; add BLOCKED_BY 189 -> [9, 46] (aquifer screening) and link #6 continuous recorders.
  - verifier: water_table_point_footprint (observability.py:946) is referenced only in tests/test_observability.py, the qmd, and well_hydrostratigraphy.py. The twin uses ungated point_footprint (:174, :190), and gwl_dynamic.py:94-111 krige every well in the window. Nuance: qc_nwis.py:307-311 does compute measurement_target, and calibrate_spatial_prior.py:29-33 requires screening, so the labels exist; they just are not wired into any operator path.
- **da-physics-coupling-9** [minor] [not-checked (minor)] The well classifier labels any screened well with top >30 m as aquifer_head, so deep upland water tables can never be water-table observations, and the documented 'screen not entirely below water level' test is not implemented.
  - evidence: well_hydrostratigraphy.py:49 SHALLOW_MAX_M=30; :186-188 screen rules; docstring :148-150 mentions observed water level but code never uses DTW.
  - issues: #9/#46/#189: compare screen interval to observed DTW, not to a fixed 30 m.
- **da-physics-coupling-10** [major] [confirmed] Static Stage-1 baseline error variance is ~1369x the dynamic anomaly prior variance; prior_calibration.py fits a spatial-only Matern to static out-of-fold residuals, which estimates a bias-state covariance, not the dynamic B/Q.
  - evidence: (18.5/0.5)^2=1369 (probes.py); prior_calibration.py:8-19, :223-287 (spatial only, no time); #192 task 'estimate prior correlation scales from held-out residuals/variograms'.
  - issues: #187: carry a separate static offset/bias state (or assimilate per-well anomalies only); #192: dynamic B/Q from forecast-residual statistics, prior_calibration reserved for the static offset.
  - verifier: prior_calibration.py:8-19 explicitly fits residuals from a spatially held-out BASELINE (static delta h). calibrate_spatial_prior.py usage then targets --state water_table_head_anomaly, the 0.5 m dynamic anomaly prior. That conflates the static-bias covariance with the dynamic B/Q. An optional 'season' column exists but the model is spatial-only. 1369 is the correct arithmetic, given the repo's 18.5 m baseline figure.
- **da-physics-coupling-11** [major] [confirmed] Stage-3 kriged fields and gwl_dynamic kriged anomalies are interpolations of the same wells and must never be assimilated as pseudo-observations alongside those wells.
  - evidence: gwl_dynamic.py:94-123 krige well anomalies; Stage-3 residual kriging per code_map; same NWIS wells feed make_twin_gif.py:213-226.
  - issues: #187/#189: add rule that interpolated products initialise mean/B only, never y.
  - verifier: gwl_dynamic.py:94-123 kriges per-well anomalies from the same NWIS table the twin uses. As a rule against double counting this is correct. No current pipeline was found assimilating the kriged field as y, so this is preventive, not an observed defect.
- **da-physics-coupling-12** [major] [partially] anchor.assimilate_points is overconfident because it multiplies precision by a distance weight and ignores observation-observation covariance: 2x too small a sigma for one well at 5 km and 5.6x for 10 co-located wells, relative to BLUE with the same prior.
  - evidence: anchor.py:53-90; probes.py: anchor sigma 0.149 vs BLUE 0.299 (N=1); 0.049 vs 0.277 (N=10), sigma=0.5, L=12 km, sigma_o=0.15.
  - issues: #28 must not extend anchor.py to SNOTEL; route via blue_update/#188; hold #28 behind #189 role assignment.
  - verifier: Qualitatively right: anchor.py:83-90 sets precision = sum exp(-d^2/2L^2)/sigma_i^2 with no prior-correlation cap, so N co-located wells shrink sigma like 1/sqrt(N). The cited numbers (0.149 vs 0.299; 0.049 vs 0.277) reproduce, but the BLUE side uses a Matern-1.5 prior (rho = 0.837) while anchor uses a Gaussian kernel. With the matching Gaussian kernel (rho = 0.917) BLUE gives sigma 0.239 (N=1) and 0.204 (N=10), so the overconfidence ratios are about 1.6x and 4.2x, not 2x and 5.6x. The recommendation for #28 stands.
- **da-physics-coupling-13** [major] [confirmed] blue_update and the twin apply unbounded increments; a stochastic EnKF near saturation pushes ~12% of members above theta_sat, and clipping is a one-sided mass sink.
  - evidence: observability.py:1217-1263 no bounds; make_twin_gif.py:229, :245 unclipped; probes.py: 40 members, prior 0.43+/-0.03, obs 0.45+/-0.03, sat 0.46 -> 11.9% exceed, ~1 mm/analysis per m removed by clip.
  - issues: #188: specify transformed variables (logit saturation / anamorphosis) or ledgered projection; #187 ledger must include bound-projection terms.
  - verifier: blue_update (observability.py:1217-1263) clips only the variance reduction; the mean is unbounded, and the twin adds increments unclipped (:229, :245). The probe reproduces 11.9% of members above sat and about -0.96 mm per analysis from clipping. The probe's prior is itself clipped at sat (about 16% of members pile up on the bound), which is realistic for the model's own clip at water_budget.py:255.
- **da-physics-coupling-14** [minor] [not-checked (minor)] With fixed per-cell Sy, analyses on storage and on head are identical (invertible linear transform), so #187 (storage state) vs roadmap (head/theta state) disagree in wording but matter only for ledger units, Sy augmentation (nonlinear H=S/Sy) and vadose partition.
  - evidence: hydro_state.py:158-204; #187 'Primary state should be storage based'; probabilistic-nowcast-forecast-roadmap.md:215-221 '#188 is scoped to ... GWL (head) and soil moisture'.
  - issues: Reconcile #187 and roadmap text: prognostic storage, head diagnostic, ledger in mm; state that wells become nonlinear once Sy is uncertain.
- **da-physics-coupling-15** [major] [partially] USGS gauges are registered as a linear footprint on the head anomaly, a category error: a gauge measures a routed, lagged basin integral of fluxes, and the model has no routing.
  - evidence: observability.py:894 ObsStream('USGS gauges', ('gwl',), 5.0, ..., 'flux'); docs/twin/04-assimilation.qmd:523-525 equivalent-circle footprint; water_budget.py:33 Q=runoff+interflow+baseflow, :300-311 accumulate_runoff non-conservative.
  - issues: #189: gauge operator = basin mask x time-window x unit-hydrograph lag on member fluxes; until then gauges are calibration/validation only (and the key withheld check in #194).
  - verifier: ObsStream('USGS gauges', ('gwl',), ..., 'flux') at :894 is confirmed, as is the equivalent-circle footprint in 04-assimilation.qmd:520-525. But the doc itself calls this a 'basin-integrated-flux approximation' for an observability/checkerboard resolution diagnostic, and no pipeline actually assimilates gauges against head. The category-error critique is correct as a warning for #189. accumulate_runoff (:300-311) multiplies runoff by (1+norm) and is indeed non-conservative (up to 2x).
- **da-physics-coupling-16** [minor] [not-checked (minor)] Forcing datasets (GHCN-Daily, NOAA Stage IV, GNSS-TEC/ZTD precipitable water) are catalogued as observing gwl/soil_moisture states; they belong in the forcing ensemble (Q), not in G.
  - evidence: observability.py:899, :903, :907.
  - issues: #189/#192: move them to forcing perturbation design (#32/#71); remove from STREAMS state rows.
- **da-physics-coupling-17** [major] [confirmed] SMAP (0-5 cm, fetched as monthly means) and the single root-zone bucket are support-mismatched; SMAP cannot be assimilated before a surface-layer or exponential-filter operator exists, and monthly averaging discards the signal at the 5-day theta timescale.
  - evidence: fetch_smap.py:1-3, :124 (L3 surface 0-5 cm, monthly); TEMPORAL_TAU_DAYS soil_moisture 5 d (observability.py:770); single bucket water_budget.py:150-155.
  - issues: #29/#197: no SMAP/NISAR bias-correction of theta before #189 roles; add surface-layer operator task; keep SMAP as independent validation first.
  - verifier: fetch_smap.py:1-3 and :124 show SPL3SMP_E surface 0-5 cm aggregated to monthly θ, with role 'independent ... validation'. TEMPORAL_TAU_DAYS soil_moisture = 5 d (observability.py:770). The model has a single root-zone bucket. The support and timescale mismatch is as stated.
- **da-physics-coupling-18** [major] [confirmed] In-situ soil-moisture depth averaging does not renormalise weights when a sensor is missing, creating step drops (e.g., losing the 20-inch sensor removes 59% of theta) that will appear as large innovations.
  - evidence: fetch_insitu_sm.py:77-79 weights normalised over 'use' then .sum(axis=1, min_count=1) without per-row renormalisation; depths (2,4,8,20) in -> 20/34=0.59.
  - issues: #189 QC task: per-timestep weight renormalisation and a depth operator matching root-zone support.
  - verifier: fetch_insitu_sm.py:77-79: weights are normalised once over 'use' and then .sum(axis=1, min_count=1) with no per-row renormalisation. Depths (2,4,8,20) from fetch_snotel.py:38 give 20/34 = 0.588. A second defect: the weights are proportional to sensor depth, not to the layer thickness each sensor represents.
- **da-physics-coupling-19** [minor] [not-checked (minor)] GNSS elastic loading constrains only domain-aggregate total water storage (2-6 mm uplift for 100-300 mm over the ~87 km equivalent-radius domain; <1 mm for 10 km-scale loads), dominated by snow and out-of-domain loads; GRACE gives at most one number per month for this domain.
  - evidence: probes.py Boussinesq disk load (E=75 GPa, nu=0.25): 87 km/100 mm 2.13 mm, 87 km/300 mm 6.40 mm, 10 km/300 mm 0.74 mm; domain 141x170 km (code_map).
  - issues: #226: re-scope as aggregate-TWS validation / domain-scale effective-Sy constraint gated on snow (#100); not a cell-storage observation.
- **da-physics-coupling-20** [major] [confirmed] #226 states 'Blocked by #187, #189' but is not in BLOCKED_BY, so GAIA queues it in batch 9 before the contract and observation records exist.
  - evidence: issues.json #226 body 'Blocked by: #187 ... and #189'; gaia_group_issues.py:87-104 has no 226 entry; queue_sim.jsonl batch 9 = [226,170,169,168].
  - issues: Add BLOCKED_BY 226 -> [187, 189, 100].
  - verifier: #226 body says 'Blocked by: #187 ... and #189'. BLOCKED_BY (gaia_group_issues.py:87-104) has no 226. queue_sim puts [226,170,169,168] in batch 10 (1-indexed), not batch 9; the claim's batch index is off by one, but the substance holds.
- **da-physics-coupling-21** [critical] [confirmed] The DA P0 batch (#198, #163, #162, #161) runs first, before the water-budget batches and #187; #162 asks for an augmented [hydrology, D, Phi] Kalman/RTS smoother, contradicting #188's hydrology-first scope and preceding the identifiability gate #169.
  - evidence: queue_sim.jsonl batch 1 = [198,163,162,161]; water budget batches 7-8 = [175,174,173,172], [137,131]; #162 body 'build the augmented-state Kalman/RTS smoother (state = [hydrology, D, Phi])'; #188 'Start with hydrology only'.
  - issues: Add BLOCKED_BY 161->[187] (or fold #161 into #188 and close), 162->[188,169], 198->[172,187]; re-scope #162 to post-#188 research.
  - verifier: Substance confirmed, with off-by-one batch indices. In queue_sim the DA P0 batch [198,163,162,161] is batch 2 (batch 1 is CI [153,152]), and the water-budget batches are 7-9 ([227,225,177,176], [175..172], [137,131]). #162 body: 'build the augmented-state Kalman/RTS smoother (state = [hydrology, D, Phi])'. #188: 'Start with hydrology only'. None of #161/#162/#198 are in BLOCKED_BY. Whether 'critical' is warranted depends on whether those PRs auto-merge, but the ordering is wrong.
- **da-physics-coupling-22** [major] [partially] #198 (P0) requires a depth-resolved theta(z,t), but the model has a single root-zone bucket and no vadose store, so an agent implementing #198 now must invent the hydrologic profile it is supposed to consume.
  - evidence: #198 body chain 'theta(z,t), Sw(z,t), h(t) -> Pc(z,t)...'; water_budget.py:150-157 single bucket; #172 'add an explicit unsaturated store'.
  - issues: Hold #198 behind #172/#131 and #187; meanwhile limit it to a documented 'linear_saturated' fidelity mode interface.
  - verifier: #198 demands theta(z,t) and Sw(z,t) feeding Pc(z,t), while water_budget has a single bucket. However, van Genuchten Pc(Se) already exists (dvv_coupling.py:23, :86; hysteresis.py:49). A hydrostatic-equilibrium θ(z) built from h_wt via vG is a standard, cheap construction, so an agent would not have to invent physics from nothing. It would, though, produce a profile whose storage is inconsistent with the bucket's θ. The hold recommendation is reasonable.
- **da-physics-coupling-23** [major] [confirmed] Roadmap, #198 and #165 prescribe incompatible treatments of dv/v petrophysical gains in the cycling filter (use linearized k_sat/S_theta in #188 vs retire them from the operational path vs encode gain in G).
  - evidence: probabilistic-nowcast-forecast-roadmap.md:219-221; #198 body 'Retire dvv_to_theta_change(..., S_THETA) and dvv_to_wtd_change(..., K_SAT) from the operational assimilation path'; #165 'encode the sensitivity gain into G'.
  - issues: Human decision before GAIA runs: exclude dv/v from #188 pilot entirely; merge #165 into #198; update roadmap text.
  - verifier: Roadmap :219-221 says dv/v enters #188 via linearized k_sat Δh / S_theta Δθ coefficients as an 'accepted' approximation. #198 says to retire dvv_to_theta_change/dvv_to_wtd_change from the operational path. #165 says to encode the gain in G and its variance in R. These are three incompatible directions.
- **da-physics-coupling-24** [major] [partially] dv/v cannot inform head until its gain is calibrated: K_SAT=5e-4/m gives 0.05% dv/v per metre (SNR ~1-5 per metre at 0.01-0.05% noise) while the gain is uncertain by about an order of magnitude.
  - evidence: make_twin_gif.py:77 K_SAT=5e-4; #45 (S_THETA=-2 implies ~20% per 0.1 theta vs observed 0.1-1%); #30 gains nominal.
  - issues: #30/#188: first use of real dv/v is gain calibration against co-located screened wells (validation role), last in the DA chain.
  - verifier: K_SAT = 5e-4/m (make_twin_gif.py:77) gives 0.05% per m, which is correct. But the cited evidence for an 'order-of-magnitude' gain uncertainty, #45, concerns S_THETA (θ gain, 1-2 orders too large), not K_SAT. The quoted noise level of 0.01-0.05% is not sourced in the repo. The conclusion (calibrate the gain before using dv/v) is sound, but the K_SAT uncertainty magnitude is asserted rather than shown.
- **da-physics-coupling-25** [major] [partially] #187 is blocked by epic #171, but epics are never GAIA work items, so the whole DA chain is held until a human closes the epic, which also contains non-blocking items (#176, #177, #225, #227).
  - evidence: gaia_group_issues.py:88 BLOCKED_BY 187 includes 171; :178 epics excluded; #171 sub-issues list.
  - issues: Replace 171 with [131, 137, 172] (and 173/175 if desired) in BLOCKED_BY[187].
  - verifier: Confirmed that BLOCKED_BY[187] includes epic 171 (:88), that epics are skipped (:178-179), and that the queue holds #187 on #171 (queue_held.txt). But #171's body lists only #131,#137,#172-#177, and the GitHub sub_issues API shows 0 sub-issues, so #225/#227 are not part of the epic (they share the milestone only). Also 137 and 172 are already in BLOCKED_BY[187], so the replacement effectively just adds #131 (plus optionally 173-175).
- **da-physics-coupling-26** [major] [partially] Issues pre-labelled needs-human-decision (#163, #186) are not held by the grouper and are queued in the first batches.
  - evidence: queue_sim.jsonl batches 1-2 contain 163 and 186; gaia_group_issues.py has no needs-human-decision filter; label only applied post hoc gaia_run_queue.sh:582.
  - issues: Hold needs-human-decision issues in the grouper or resolve the decision before launch.
  - verifier: #163 and #186 do carry needs-human-decision, and the grouper has no such filter; gaia_run_queue.sh only applies the label (:582, :1021-1031) and never reads it. But #186 sits in batch 3, not batches 1-2 (#163 is batch 2). Note the label's queue semantics are 'competing PR; a human must choose', which implies rival PRs may already exist, so re-queueing risks more duplicates.
- **da-physics-coupling-27** [minor] [not-checked (minor)] Several DA issues cite stale observability.py line numbers that no longer match origin/main, which will misdirect agents.
  - evidence: #161 cites :89-103 and :183 (lagged_observation now :826); #162 cites :276-318 (blue_update now :1217); #165 cites :165/:183 (point_footprint :923, normalise_footprint :981); #170 cites :215, :321-330 (satellite_footprints :995, information_gain :1266).
  - issues: Refresh citations to function names (not line numbers) in #161, #162, #164, #165, #166, #167, #170.
- **da-physics-coupling-28** [major] [partially] The minimal real-data cycling pilot should assimilate only per-well head anomalies (same-window reference for model and data) from aquifer-screened continuous-recorder water-table wells in one gauged basin, with Sy fixed, forcing-only ensemble, and the gauge and soil probes withheld for validation of increment consistency.
  - evidence: Synthesis of claims 1-8, 10-11, 15, 17, 24; roadmap :211 allows a small-fixture prototype; #194 requires withheld sensors.
  - issues: Write this as the explicit scope/acceptance of #188's first slice; defer probes (second step), precip multiplier+gauge, SMAP, dv/v, GNSS/GRACE.
  - verifier: A reasonable, conservative pilot scope, consistent with roadmap :211. Gaps: (a) anomaly-only assimilation leaves the 18.5 m static bias, and with it the d0-dependent sink coefficient (claim 3), uncorrected, so the dynamics stay biased. (b) A forcing-only ensemble with fixed Sy/Ka will be under-dispersive for parameter error, so it needs inflation or a parameter-error Q. (c) No count was made of aquifer-screened continuous-recorder water-table wells in a single gauged basin; feasibility is unverified (#6).
- **da-physics-coupling-29** [minor] [not-checked (minor)] #28 and #29 would create parallel non-cycling assimilation/bias-correction paths for theta (SNOTEL residual kriging, SMAP bias correction) that consume the very streams #189/#194 need as independent validation.
  - evidence: #28 tasks 'Bias-correct / residual-krige the bucket theta against SNOTEL'; #29 'Calibrate/bias-correct theta against SMAP'; queue batches 37-38 unblocked.
  - issues: Add BLOCKED_BY 28->[189], 29->[189] or restrict them to validation-only.
- **da-physics-coupling-30** [minor] [not-checked (minor)] SPECIFIC_YIELD_RANGE upper bound 0.6 exceeds the porosity of most aquifer materials and does not guard against the Sy~porosity compensation already identified.
  - evidence: hydro_state.py:87 (0.005, 0.6); water_budget.py:62 Sy=0.30 calibrated; #137 'S_y = 0.30 is near total porosity'.
  - issues: #137: tighten to a domain-specific physical range (e.g. <=0.35) with per-unit priors.

## Verifier: missed problems

- Timescale inconsistency between the model and the DA temporal prior: the HAND sink gives an e-folding time tau = Sy*head0/R_ref. With Sy 0.3, R_ref 3 mm/d and head0 = 22 m (ridge) or 9 m (mid), that is about 2200 d and 900 d, set by the uncertain d0. Meanwhile TEMPORAL_TAU_DAYS['gwl'] = 120 d (observability.py:771) and RECESSION_MONTHS = 6 (water_budget.py:63). Any Q or OU temporal prior in #161/#192/#205 will contradict the forward model's own memory.
- Reference-level inconsistency for soil moisture in the twin, analogous to claim 6: make_twin_gif.py:233 builds the SNOTEL datum as theta_c[cell] + (tv - sm_mean). The innovation is therefore the station's anomaly relative to its own record mean, applied regardless of the model's own anomaly, so a model that already tracks the wetting gets it added again.
- Representativeness error is missing from R: wells are averaged per 3.6 km coarse cell but always get WELL_VAR = 0.15^2 (make_twin_gif.py:224), a reading error, with no sub-cell or point-to-cell representativeness variance and no dependence on how many wells were averaged.
- Saturation-excess storage uses Sy*wt_depth (water_budget.py:231-232) for the whole column, including the root zone whose own deficit is Ssat - S. The two storages overlap, so infiltration capacity is double-counted near the surface. Valley cells with HAND <= d0 also have unbounded head rise (wt_depth reaches -0.01 m in the probe), driven by root-zone drainage that continues after the surface saturates.
- accumulate_runoff (water_budget.py:300-311) multiplies runoff by (1 + normalized accumulation) and creates up to 2x mass. It should be flagged directly against #200/#201 (flood source-term export), not only as gauge-operator evidence.
- In-situ SM depth weights are proportional to sensor depth rather than layer thickness (fetch_insitu_sm.py:78), and the 0-20 inch (~0.5 m) support is compared with a per-cell root_depth_m bucket of different depth. This is a support mismatch separate from the missing-sensor renormalisation.
- The needs-human-decision label is applied by the queue when it finds competing PRs. The presence of #163/#186 with that label suggests open rival PRs from earlier runs that should be resolved or closed before launch to avoid a third duplicate.
