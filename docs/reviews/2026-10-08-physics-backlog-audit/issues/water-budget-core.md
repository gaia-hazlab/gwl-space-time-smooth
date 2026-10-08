# Issue family: water-budget-core

The family is the coupled bucket plus linear-reservoir water budget: src/models/water_budget.py (311 lines), the forecast chain in src/models/forecast.py, the shipped SM product in src/models/soil_moisture.py, the D7 calibration in notebooks/calibrate_fluxes.py, and the older statistical Stage-2 path in src/models/climate_response.py. I checked against origin/main 435445f. Every line reference in #131/#137/#172-#177 still points at the right code, so the July review findings are current and nothing in the epic has been fixed. My probes are in scratchpad/wf/wb_probe_water.py and use synthetic single-cell forcing.

(1) Mass is not conserved. Capillary rise is credited to S (water_budget.py:217-219) and never debited from head (:266). With a 0.8 m table, one year of daily forcing creates 33.8 mm of water, which matches the 34.1 mm of capillary rise. The audit's 0.739 mm/day figure (science-review S1) reproduces. The docstring claim "conserved by construction" (:30-33) is false.

(2) Valley-floor ratchet. Where HAND < d0, gw_recess is 0 (:193-197). Head can then only rise: with HAND 2 m and d0 5 m, the table rose 0.51 m in a year with zero baseflow. This then feeds VSA runoff.

(3) The baseline anchor contradicts the calibration targets. RECHARGE_REF = 3.0 mm/d (:88) is about 1095 mm/yr, roughly 70% of P. The observed targets imply long-term baseflow of BFI x Q/P x P = 0.47 x 0.65 x 1500, about 460 mm/yr or 1.25 mm/d, and the code's own estimate is 1.6 mm/d (:86-87). So the baseline cannot be a steady state, and the table drains for the whole run. Part of the modelled BFI is storage depletion.

(4) The calibration is weaker than claimed. It uses 10 months of daily PRISM (Sep-2025 to Jun-2026) with no spin-up (calibrate_fluxes.py:48). Fluxes are domain-wide means over every land cell, not the gauged basins or the well cells (:61-79). Q/P has no storage-change correction. "BFI" is the model's baseflow flux divided by Q, whereas the observation is a Lyne-Hollick filter of a hydrograph. Four targets, including peak month, are fit with three knobs on a 120-point grid (:94-99). Every number then reported as validation (ROADMAP, book 05) is a calibration target.

(5) No continuous well data exists. NWIS ingestion is discrete field measurements (param 72019) aggregated to site-month medians (download_nwis_domain.py:6-15). The storm-lag acceptance in #131 and #87 cannot be met with current data.

(6) The interflow formula f_lat = Ka*tan(b)/(1+Ka*tan(b)) (:199-206) is the ratio of slope-parallel to slope-normal flux. It does not vanish for isotropic soil (Ka=1 gives 19% lateral at 13 deg). The fitted Ka is therefore not the physical anisotropy, and the 10-100 literature range is the wrong comparator. Note that soil_hydraulics.py:29 already uses f of about 2.5.

Most of the issues are real and correctly diagnosed. The main problems are missing ordering and dependencies, acceptance criteria that cannot be tested with the available data, and calibration targets reused as validation. #20 is done; #87 duplicates #131; #57 and #70 are largely superseded by the daily coupled budget; #23 belongs with #8.

**Queue ordering:** The simulated queue (queue_sim.jsonl) runs batch 6 = [227, 225, 177, 176], batch 7 = [175, 174, 173, 172], batch 8 = [137, 131]. Within a batch GAIA resolves issues sequentially in the grouper's order, which is gh's newest-first (gaia-automation.md:69,291), and closes each issue with 'Closes #N'. The family therefore runs almost exactly backwards:
- The Rainier stores (#225 interception, #227 glacier melt) and the hysteresis-in-dynamics work (#176) edit coupled_water_budget before the storage contract exists.
- #173, which explicitly needs #172's store, and #174/#175 run before #172 in the same batch.
- #137 (recalibration) runs before #131 (the lag that changes the fit).
- The foundations #52, #89 and #70 have no milestone and fall to batches 26, 36 and 39, after every hazard milestone. Yet #52 and #89 are hard blockers of P0 #187 (gaia_group_issues.py:87), and #70's multi-year forcing is upstream of #137 and #175.
- #87 (a duplicate of #131) sits in batch 36, so a second lag implementation is possible.
- #57 in batch 32 would 're-derive' an already-daily bucket.
- #100 is in batch 15 with an acceptance criterion that is really #137's.
- BLOCKED_BY uses epic #171 as a #187 blocker, which is indefinite. It encodes none of the intra-family dependencies.
- The grouper ignores the needs-human-decision label (it only checks epic and BLOCKED_BY, gaia_group_issues.py:175-186). So scope decisions here (narrowing the GWL claim, retiring the monthly product) have no enforced hold.
- The Vs30 #81-#86 pause until water-budget work lands (ROADMAP v0.3) is not enforced either: they run in batches 13-14, before the water-budget leaves are validated.
Required order, encoded as BLOCKED_BY or as a typed registry: ledger-harness gap and #52 and #89 (code part) and #70 (multi-year forcing) and continuous-wells gap and calibration-harness gap, all independent and run first. Then #172 (store). Then #131 (store timescale). Then #173, then #174, then #175 + ratchet fix (sequential, each touches :215-279). Then #176. Then #225/#227 (on top of the ledger). Then #137 (re-close on frozen holdouts, absorbing the #100 phase criterion). Close #87 and #20 now, merge #23 into #8, and defer #57.

## #171 [epic] Water budget: restore the unsaturated zone; validate the calibration
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: []
- physics: The diagnosis is correct and confirmed on main. The unsaturated zone has no storage (water_budget.py:247-266). Capillary rise creates water (probe: 33.8 mm/yr at a 0.8 m table). S_y does three jobs (:230, :266, :278). The closure is a calibration fit, not validation (calibrate_fluxes.py:81-99). The alternative it offers, narrowing the GWL claim to antecedent/seasonal state, is a scope decision for the PI, not for an agent.
- problems:
  - The grouper skips it as an epic (gaia_group_issues.py:178), which is fine. But it is listed as a hard blocker of #187 (gaia_group_issues.py:87). Epics are closed by humans, so this can hold the P0 contract indefinitely (system audit line 95; dependency review line 24).
  - The sub-issue list omits #89 (timestep, also a #187 blocker), #87 (duplicate of #131), the #100 phase residual, the Rainier #225 (canopy interception) and #227 (glacier melt), which edit the same loop, and the missing continuous-well and conservation-harness work.
  - The 'or narrow the GWL claim' branch is an unresolved scope decision that should carry needs-human-decision. The grouper ignores that label anyway (it only checks epic and BLOCKED_BY, gaia_group_issues.py:175-186).
- proposed edit: In BLOCKED_BY[187], replace 171 with the leaf evidence: the conservation harness (new) and #172. Add #89, the #100 residual, #225, #227 and the new gap issues to the sub-issue list, and mark #87 as superseded by #131. Add an explicit decision checkbox (needs-human-decision): 'GWL product scope: storm-scale (1-15 d) head forecast vs antecedent/seasonal state', with the lab lead as owner. State the order: ledger harness, then #172, then #131, then #173/#174/#175 (sequential), then #176, then #137 re-close.

## #172 Consistent storage account: close the massless vadose gap between the two reservoirs
- verdict: **split** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Correct and confirmed. cap_eff is added to S (:218-219) and h is never debited (:266). The legacy recession clips signed baseflow (:268, :278), leaving a residual of 0.00404 mm even after a one-line debit (followup line 40). The existing test only checks the root store (test_water_budget.py:26-33), so it cannot catch this. An explicit unsaturated store between the root base and the table is the right fix, but it needs a moving-boundary rule: as the table rises into the vadose layer, that layer's water becomes saturated storage. The physically consistent form is an effective specific yield S_y,eff = theta_sat - theta_u(table-top), which shrinks for shallow tables because of the capillary fringe (Duke 1972). That also resolves part of #137's 'S_y does three jobs'.
- problems:
  - It bundles two deliverables: a conservation repair that is small and testable, and a new physics store that is a design task. GAIA closes the whole issue with 'Closes #N' (gaia-automation.md:82,119), so a capillary-debit PR would close #172 with the store unbuilt. The operational plan (line 44) warns about exactly this.
  - There is no acceptance criterion in the body at all.
  - The vadose store IS the #131 lag mechanism. Unless the two are coordinated they will become two competing implementations.
  - In the queue it is the last of batch 7, after #175, #174 and #173, which all depend on it. Batches run in descending issue-number order (queue_sim batch 7: [175,174,173,172]).
- proposed edit: Split into two issues. (a) 'Whole-system water ledger + capillary/recession conservation repair' (new, P0/P1, agent-ready): define the control volume (root S + vadose U + S_y*h above datum), debit capillary rise from groundwater, and account for signed recession. Test: the residual over all branches (legacy, HAND, slope on/off, wet/dry limits, multi-step) is below 1e-6 mm per step in float64, and dt=1 d vs 0.25 d agree. (b) Keep #172 as 'explicit unsaturated store U with moving-boundary S_y,eff', blocked by (a). Acceptance: the conservation suite passes, and a zero-store limit reproduces the current behaviour. Add BLOCKED_BY 172:[ledger].

## #173 Saturation-excess runoff: no one-step fill to the water table; stop double-counting root-zone space
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [172]
- physics: The arithmetic is correct. deficit = S_y*dtw*1000 (:230), so at 5 m, 1500 mm, and at 0.5 m, 150 mm. VSA effectively never fires except where d0 is under about 0.5 m. The root-zone space is counted twice (:230 and :236). Runoff Q/P is therefore produced mostly by interflow (Ka), not VSA, which contradicts the docstring (:15-19). The physically right deficit is the unsaturated storage deficit, integral of (theta_s - theta) over the column, taken from the new store U. Additional bias: the valley-floor ratchet (HAND < d0, :195) pushes those cells up to the surface over time and makes VSA fire artificially there.
- problems:
  - The body depends on '#...', a placeholder for the store issue (#172) that was never filled in. That dependency is not in BLOCKED_BY.
  - It is batched before #172 in batch 7, so it would be implemented first.
  - It has no testable acceptance criterion.
  - There is no independent check of saturated-area extent.
- proposed edit: Replace '#...' with #172. Acceptance: (1) the deficit is computed from U and the root store with no double count, and the ledger test passes; (2) report runoff by mechanism (VSA, root-zone excess, interflow) per gauged basin; (3) an independent check: the modelled saturated-area fraction in wet-season storms vs NWI wetland/riparian area or TWI-saturation maps for Newaukum. Do not use Q/P, because that is a calibration target. Add BLOCKED_BY 173:[172] and the ratchet-fix gap issue.

## #174 Interflow: give it a store and a defensible coefficient
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [172]
- physics: The issue is right that interflow is an instantaneous fixed fraction (:247-249) with no hillslope memory. It is wrong about why Ka looks too low. f_lat = Ka*tan(b)/(1+Ka*tan(b)) is the ratio of slope-parallel to slope-normal Darcy flux. For gravity drainage in an anisotropic slope, the lateral:vertical ratio is (Ka-1)*sin(b)*cos(b)/(Ka*sin^2(b) + cos^2(b)) (Zaslavsky & Sinai 1981), which is zero for isotropic soil. The code gives 19% lateral at Ka=1 and 13 deg. So the fitted Ka is a lumped coefficient, and 'refit within 10-100' is not a meaningful target. With 90 m slopes biased low (true slopes are steeper), correcting the slope at fixed Q/P drives Ka down further. Real subsurface stormflow comes from perching on the soil/till/bedrock contact and is threshold-driven: a kinematic perched store, q = K_h*sin(b)*H_perched (Sloan & Moore 1984), with soil thickness already available (baseline_wt_domain.py:62). Interflow also leaves at the cell with no downslope convergence, so hollows never get wetter. That matters for landslide pore pressure (#130/#133).
- problems:
  - 'Re-fit Ka within a physical range' cannot be satisfied with the current formula and will push an agent to tune.
  - It does not depend on #172 but edits the same lines (:247-250).
  - It overlaps #130/#133 (the roadmap review asks for one shared perched/interflow state).
  - 'Report the residual' does not say against what. Q/P is a calibration target.
- proposed edit: Rewrite the Do section as: a perched interflow store on the soil-bedrock/till contact, a kinematic outflow K_h*sin(b)*H/L, flux routed downslope via flow accumulation (or explicitly sent to the stream, stating which), and a slope from the 10 m DEM aggregated as mean tan(b) per 90 m cell. Ka is reported as an effective parameter, with the anisotropy formula corrected or relabelled. Acceptance: ledger passes; interflow recession timescale vs held-out storm hydrograph recessions at gauges; coordinate one state with #133. BLOCKED_BY 174:[172].

## #175 Baseflow sink: break the near-circular BFI anchor; nonlinear recession
- verdict: **keep** → verifier: **rewrite** (The physics premise is right: the steady-state anchor is gw_recess=(R_ref/S_y)/head0 (water_budget.py:193-196), and R_ref is fitted to BFI (:56-61; calibrate_fluxes.py:6-10). But 'keep' contradicts the audit's own findings: two missing blockers, a missing ratchet fix and no validation design. Probe results: HAND<=d0 cells get zero baseflow and the table rises 5.0->2.05 m in year 1 and reaches the surface (wt -0.03 m) by year 3 under ~1570 mm/yr. That is much larger than the audit's +0.51 m/yr, which depends on the forcing. R_ref=3 mm/d (1095 mm/yr) is about 2.4x BFI*Q/P*P (~458 mm/yr) and about 2x the code's own comment of ~1.6 mm/d (:86-88). As a result, slope cells drain the observed baseline (5.0->8.55 m over 3 yr, baseflow 1023 mm/yr vs recharge 668 mm/yr), and the 10-month calibration counts storage depletion as baseflow. Per-cell Boussinesq b also risks double counting: the HAND-distributed linear tau (=100*head0 d) already gives a nonlinear aggregate recession (Harman et al. 2009). Recession tests must therefore be done on the basin aggregate.); agent_ready: False; missing blockers: [172, 70]
- physics: Correct, and worse than stated. R_ref = 3 mm/d (:88), about 1095 mm/yr. The targets imply long-term baseflow of 0.47 x 0.65 x 1500, about 460 mm/yr or 1.25 mm/d. So at the 'observed baseline' the cells discharge about 2.4x their sustainable recharge and the table drains through the run (probe: HAND 6 and 30 m cells lose 1-3 m/yr). BFI is contaminated by storage depletion over a 10-month run with no spin-up. The recession timescale is S_y*head0/R_ref: 100 d at head0 = 1 m, 13.7 yr at 50 m. Ridges barely recede. A Boussinesq nonlinear recession (b about 1.5 late-time, Brutsaert & Nieber 1977) is appropriate. Model BFI must come from the same Lyne-Hollick filter applied to the modelled basin hydrograph, not from bf/Q flux bookkeeping (calibrate_fluxes.py:72-75).
- problems:
  - The valley-floor ratchet (#177 m5) belongs here, not under 'minor'. With HAND < d0 there is no discharge and head ratchets up (probe: +0.51 m/yr, zero baseflow).
  - It needs basin masks, a multi-year spun-up record and a frozen holdout set, none of which exist (calibrate_fluxes.py:48,61).
  - If b is fit from the same gauge recessions, a recession check is calibration, not validation.
- proposed edit: Add: (1) anchor R_ref per cell to the long-term mean recharge from a spun-up multi-year daily run, and check that the domain mean is consistent with BFI*Q/P*P; (2) fix the HAND < d0 ratchet; (3) compute model BFI with Lyne-Hollick on the basin-aggregated model Q; (4) validate on held-out gauges and years. Add BLOCKED_BY 175:[172, 70 (rewritten multi-year forcing)].

## #176 Route hysteresis into the soil-water DYNAMICS, not only the dv/v observable
- verdict: **keep** → verifier: **rewrite** (The physics is correct: forecast.py:168-174 uses vadose_dvv_hysteretic only on the dv/v output, while theta comes from the single-valued budget. However, the issue has no acceptance criterion, bundles an unrelated SIGMA0/G_REF calibration (dvv_coupling.py:47-48), and sits in batch 6 [227,225,177,176], ahead of the #172 restructure. The audit itself lists these problems plus a missing blocker, so the verdict should be 'rewrite', not 'keep'. Physics caveat for the proposed acceptance: K(theta) is nearly non-hysteretic, so drainage hysteresis has to enter through the psi-dependent field-capacity threshold or gradient. Also, closed-loop invert_dvv equality (dvv_coupling.py:126) requires a path-aware inversion.); agent_ready: False; missing blockers: [172]
- physics: Accurate: forecast.py:166-174 applies Kool-Parker hysteresis to the dv/v output only, so the theta trajectory is single-valued. In a theta-only bucket, hysteresis enters physically as a path-dependent drainage endpoint: a wetting-branch vs drying-branch effective theta_fc, with Delta-theta about 0.02-0.05. That is second-order next to the missing vadose store. The SIGMA0/G_REF magnitude calibration (dvv_coupling.py:47-48) is a separate dv/v petrophysics task that needs observed dv/v.
- problems:
  - It is in batch 6, the first water-budget batch, before #172 restructures the same loop. That means rework and conflicts.
  - It bundles an unrelated dv/v calibration (SIGMA0/G_REF) that needs data.
  - It has no acceptance criterion.
  - #198 depends on it (roadmap review line 43, dependency review line 27), but that is not in BLOCKED_BY.
- proposed edit: Move SIGMA0/G_REF calibration to the dv/v family. Acceptance: same final theta reached by wetting vs drying gives different drainage; ledger passes; invert_dvv theta equals budget theta on a closed loop. Add BLOCKED_BY 176:[172] and 198:[187,176].

## #177 Minor fixes (groundwater / vadose review)
- verdict: **split** (verifier upheld); agent_ready: False; missing blockers: []
- physics: m1, rain-on-snow: real. Degree-day melt (forecast.py:105-131) misses the turbulent fluxes that dominate melt in warm atmospheric rivers. It also passes rain straight through the pack with no liquid retention or refreezing (:130), which over-delivers on cold packs. So the bias goes both ways. m2, two inconsistent models: real. The shipped product is monthly TerraClimate with a drain-to-nowhere bucket (soil_moisture.py:162-187, 291-293, 330). m3, Ksat unused: real. drain_tau is 2 d regardless of texture (water_budget.py:73). m4, Hamon PET: partly stale. Calibration forcing uses daily Hargreaves-Samani (fetch_prism_daily.py:9-12,156), though forecast.py:12 and stage_mvp_window.py:9 still say Hamon, and #58 covers Penman-Monteith. m5, valley ratchet: a confirmed defect, not 'verify' (probe above).
- problems:
  - It mixes a P1 bug (m5), a P1 flood mechanism (m1), a product-identity decision (m2), and a stale item (m4) under a P2 'minor' label, which the roadmap review (line 101) also flags.
  - A single agent pass would Close #177 on a partial checklist.
  - It is in batch 6, before the storage restructure.
- proposed edit: Split into: (a) m5 HAND<d0 ratchet as a P1 bug (or fold into #175); (b) m1 snow state + rain-on-snow/liquid retention (combine with the SWE-state gap); (c) m2 documented as a product statement, with retiring the monthly product as a needs-human-decision item tied to #89/#52; (d) m3 texture-dependent drainage via K(theta), folded into #131 (the same K(theta) sets celerity); (e) drop m4 as covered by #58 and fix the docstrings.

## #131 Vadose transit lag: recharge must not teleport to the water table
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [172]
- physics: The diagnosis is right: there is zero delay (:266, forecast.py:31-34). Two parts of the prescription are physically off. (1) Unsaturated thickness should be depth-to-water minus root depth (d0 - h - z_root), not HAND. (2) Head responds to the kinematic celerity c = dK/dtheta, not the particle velocity, and Ksat-based or Green-Ampt estimates (#87) are far too fast. For Brooks-Corey K ~ theta^n with n about 8-12 at about 3 mm/d flux, c is roughly 0.1-0.3 m/d. That gives about 15-40 d through 4 m, and months through the roughly 20 m Puget-lowland vadose zones (#87 comment). Macropore preferential flow can be much faster. A 3-30 d sensitivity is reasonable only for shallow tables. Note the tension with #100: the calibrated model already peaks a month late (#100 comment). That evidence comes from a 10-month unspun run and is weak, but any lag must not degrade seasonal phase.
- problems:
  - Acceptance requires 'a continuous well hydrograph'. The repo only ingests discrete field measurements aggregated to site-month medians (download_nwis_domain.py:6-15), so the acceptance cannot be tested.
  - It is the same mechanism as #172's store. As written, two issues would each add a store.
  - It duplicates #87.
  - The 'or narrow the GWL claim' branch is a human scope decision.
  - In batch 8 it runs after #137, so the lag would be added after the calibration.
- proposed edit: Make it the timescale parameterization of #172's store: outflow from U with tau = (d0-h-z_root)/c(theta, K(theta)), using a texture-specific K(theta) (folds in #177 m3). Acceptance: (1) ledger passes; (2) storm-to-peak lag vs at least N continuous wells (new gap issue) at held-out sites; (3) seasonal peak month on held-out wells is no worse than before. Carry over #87's Nash-cascade option and comment history. Move the scope decision to #171. BLOCKED_BY 131:[172, continuous-wells gap].

## #137 Defensible specific yield + held-out water-budget validation (shared foundation)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [172, 131, 173, 174, 175, 89, 70]
- physics: Correct: S_y = 0.30 (:62) was picked from the grid {0.05...0.40} (calibrate_fluxes.py:96). 0.30 is the top of the coarse sand/gravel range (Johnson 1967: sand about 0.27-0.30). It is implausible for the till and volcanic rocks that dominate the Cascades: Vashon till about 0.02-0.10, fractured volcanics below 0.05. The amplitude it is fit to (1.06 m) comes from monthly medians of discrete well visits, but the model side is a domain-mean over all land cells, not the well cells (calibrate_fluxes.py:76-79). S_y absorbs the missing vadose attenuation. 'Exactly-determined' is slightly inaccurate: it is 4 targets (BFI, Q/P, amplitude, peak month) on a coarse 120-point grid, but the conclusion holds. The right structure is S_y by hydrogeologic unit, with a depth-dependent S_y,eff for shallow tables, which matters for liquefaction (M2).
- problems:
  - 'S_y in a defensible range' gives no numbers or source, so the criterion cannot be tested.
  - 'Skill on data NOT used' does not say which partition, metric or threshold.
  - Every physics change (#172, #131, #173, #174, #175) shifts the fit, so this must come last. It also needs multi-year daily forcing (#70/#89), basin masks and frozen holdouts, none of which exist.
  - It is a #187 blocker, but #189 (holdouts) is itself downstream of #187. If #137 waits for #189's holdout machinery, the dependencies form a cycle.
  - The #100 phase residual should be judged here, but peak month is itself in the objective (calibrate_fluxes.py:81-86).
- proposed edit: Acceptance: (1) S_y bounded per hydrogeologic unit with cited ranges, e.g. till 0.02-0.10, outwash 0.15-0.30, volcanic below 0.05; (2) a frozen holdout manifest (wells by site, whole basins, one water year) committed BEFORE fitting, owned here and adopted by #189; (3) model fluxes basin-masked, model BFI from Lyne-Hollick on model Q, wells sampled at their cells; (4) report held-out metrics that are NOT in the objective: daily KGE at held-out gauges, recession constant, held-out well amplitude/phase, storm lag. Peak month and amplitude stop being called validation. Run on a multi-year spun-up daily record. Add these to BLOCKED_BY.

## #89 Water budget: daily and monthly timesteps drain 4.7x differently
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Reproduced: 455 mm in one month gives 90 mm of monthly recharge vs 432 mm daily (4.8x). Part of the issue is already done: D7 calibrated in daily mode (calibrate_fluxes.py:1-4, :68 dt_days=1.0), and fetch_prism_daily has a PRISM-service fallback covering any window (fetch_prism_daily.py:59-139). What remains: dt_days=None (monthly) is still the DEFAULT (water_budget.py:122,161-164), the tests run monthly (test_water_budget.py:28), and the shipped SM product uses monthly drain_frac (soil_moisture.py:158-187). The physically consistent fix is a single process timestep, with monthly output produced by daily sub-stepping. Exact agreement between lumped-monthly and daily is not the right target.
- problems:
  - It has no milestone, so it lands in queue batch 36 although it is a hard blocker of #187 (gaia_group_issues.py:87), as the system audit (line 93) notes.
  - Mixed scope: the code-consistency work, data acquisition (now just a run), calibration (belongs in #137) and the product-retirement decision.
  - 'Agree within a defensible tolerance' gives no number.
- proposed edit: Move to the 'Water budget' milestone. Scope: make dt_days required (no implicit monthly); implement monthly as daily sub-steps; add a timestep-convergence test (dt = 1, 0.25 d, and 30 d via sub-stepping) with recharge totals agreeing within 2%. Move the multi-year calibration to #137/#70, and the monthly SM product retirement to a needs-human-decision checkbox.

## #87 Forecast: recharge reaches the water table instantaneously (no unsaturated travel-time lag)
- verdict: **close-superseded** (verifier upheld); agent_ready: False; missing blockers: []
- physics: The same mechanism as #131. Its velocity estimate (Ksat/Green-Ampt) is physically wrong for head response: kinematic celerity from K(theta) is what matters. Its claim that storm lag is 'directly observable' in the NWIS wells is false for the discrete, monthly-median data the repo has. The two comments (promoted, then demoted, saying 'do not spend effort before v0.4') conflict with #131's later framing.
- problems:
  - It is an exact duplicate of #131 (the roadmap review consolidates #87/#131/#172).
  - It is unmilestoned and sits in batch 36. An agent could implement a second lag after #131's.
  - Its comment explicitly says do not work on it, but nothing enforces that.
- proposed edit: Close as superseded by #131. First copy into #131: the Nash-cascade option, the 162 mm/1.35 m AR example, and the seasonal-phase demotion evidence, which becomes #131's 'phase must not degrade' criterion.

## #52 P1: Resolve the two-theta ambiguity; fix sigma math
- verdict: **keep**; agent_ready: True; missing blockers: []
- physics: Still valid on main. soil_moisture_90m ships total-water theta = wp + sf*(sat - wp) (soil_moisture.py:309-311), but its dynamic sigma is _W_SIGMA*awc with awc = fc - wp (:322, and main() :454-456). estimate_soil_moisture uses the plant-available definition (:253-260). The physical choice is clear: the canonical state should be total volumetric water content, because that is what probes, SMAP and the dv/v petrophysics observe. Plant-available water is derived from it. The sigma terms then become (1-sf)*sigma_wp, sf*sigma_sat and sigma_w*(sat - wp).
- problems:
  - It has no milestone, so it lands in queue batch 26 (topic:bug) although it is a hard blocker of the P0 #187 (gaia_group_issues.py:87).
  - The acceptance criterion is implicit.
- proposed edit: Assign it to the foundation milestone (Water budget or Applied math) so it runs before the hazard milestones. Acceptance: one documented canonical theta (total volumetric); sigma partials verified against finite differences in a test; estimate_soil_moisture either aligned or renamed to plant_available_*; the #20 remnant folded in.

## #20 Implement soil-moisture state module (theta static envelope + dynamic driver)
- verdict: **close-done** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Delivered. estimate_soil_moisture is implemented with theta_std (soil_moisture.py:243-261). There is a 90 m product with a 3-term uncertainty budget (:267-337), a make/pixi target (Makefile:228, pixi.toml:120), and tests (tests/test_soil_moisture.py). The body still calls it a scaffold, so it is stale (roadmap review line 79). The remaining semantic issue (which theta) is #52.
- problems:
  - Stale body: an agent could re-implement working code.
- proposed edit: Close as done, citing soil_moisture.py:243-337 and the tests. Move any remaining SMAP/SPoRT-driver wish to the soil-reanalysis assimilation issues, and the theta definition to #52.

## #70 Hindcast forcing: drive the coupled water budget from PRISM rainfall
- verdict: **rewrite** (verifier upheld); agent_ready: True; missing blockers: []
- physics: Mostly done. Daily PRISM with Hargreaves-Samani PET exists (fetch_prism_daily.py), and D7 is forced by it (calibrate_fluxes.py:48). The real missing deliverable, and the one the whole family needs, is a MULTI-YEAR daily record (e.g. WY2005-2025) with a spin-up protocol. #89, #100 (the phase residual is attributed to spin-up), #131, #137 and #175 all need it. Physics notes: PRISM 'days' end at 12 UTC, so a half-day offset matters for daily lag validation. PRISM is 4 km and undercatches mountain snow.
- problems:
  - As written it is the old monthly/TerraClimate framing.
  - It is unmilestoned and sits last in the queue (batch 39), although it is upstream of #137.
- proposed edit: Retitle: 'Multi-year daily PRISM forcing record + spin-up protocol for the coupled budget'. Acceptance: a versioned Zarr for WY2005-2025 on the domain grid with checksums; a documented PRISM day convention; a spin-up test where the table's state at the end of each repeated spin-up cycle changes by less than 1 cm/yr; a TerraClimate-vs-PRISM comparison kept as the forcing-spread item (#32). Move to the 'Water budget' milestone so it runs first.

## #100 D8: Snow is the water-table clock — calibrate the snow module and verify the April peak emerges
- verdict: **rewrite** → verifier: **rewrite (blocker should be #70, not #137)** (The rewrite content is sound. v0.4 is DONE in ROADMAP.md:87 while #100 is open. Snow is SNOTEL-calibrated per the comments, so a leave-stations-out test is a fair new requirement. liquid_input starts SWE at zero on every run (forecast.py, swe=np.zeros), so SWE state is a real gap. But adding BLOCKED_BY 100:[137] inverts the issue's own ordering ('do D8 before or alongside D7, not after') and would delay the snow fix until after calibration. The phase residual depends on multi-year spin-up (#70), per the last comment.); agent_ready: False; missing blockers: [137]
- physics: The snow calibration is done (forecast.py:53-61, 28-30 SNOTEL stations, melt-out objective). The acceptance criterion (April well peak emerges) is not met (model peaks in month 5), and it cannot serve as validation, because peak month is inside the D7 objective (calibrate_fluxes.py:81-86). The 'snow is the clock' hypothesis is physically questionable for the observed wells. The 863 NWIS wells are largely lowland, below the seasonal snow zone, so their April peak is more plausibly aquifer and vadose response to winter rain. Domain-mean melt timing matching the well-ensemble peak month is a phase coincidence, not a mechanism test. The snow calibration was also evaluated on the stations it was fit to. Gap: SWE is not a carried state. liquid_input starts SWE = 0 on every call (forecast.py:123), so a forecast initialized mid-winter melts nothing.
- problems:
  - The acceptance criterion is a calibration target.
  - Its milestone (v0.4) is declared done in ROADMAP (audit R4).
  - The mechanism is untested.
- proposed edit: Narrow it to snow: (1) a falsification test: stratify wells by elevation and snow fraction. If snow is the clock, rain-dominated low wells should peak earlier than snow-affected wells; (2) leave-stations-out SNOTEL validation of melt-out; (3) carry SWE as model state and initial condition. Move the WT-phase criterion to #137's held-out metrics.

## #23 Prototype Rung-2 TFN dynamics (linear reservoir, Pastas) behind climate_response
- verdict: **merge** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Still not implemented. climate_response.py is the monthly OLS beta-map with beta4 = 0 (:1-14), and pastas is not in pixi.toml. Its most valuable use now is as an independent per-well estimate of response time and recession (Gamma/Hantush impulse response) to validate #131 and #175 against data the budget was not fit to, rather than as a competing Stage-2 forecast model. Discrete, irregular monthly well data allows TFN only at monthly resolution.
- problems:
  - It overlaps #8 (roadmap review: consolidate #8/#23).
  - The dependency is missing from the environment.
  - There is no acceptance criterion.
- proposed edit: Merge into #8 and rescope it as 'Pastas TFN per well: response-time and recession maps as independent diagnostics for #131/#175'. Acceptance: TFN response time per well with a CI on held-out wells; compared against the budget's vadose tau. Add pastas to pixi.

## #57 P2: Re-derive the bucket at daily/hourly resolution; populate beta4/TFN for atmospheric rivers
- verdict: **defer** → verifier: **rewrite-then-defer** (The claim 'already-daily bucket' is only half true. coupled_water_budget is daily-capable, but the SHIPPED 90 m SM product still uses the monthly-only total_water_bucket (soil_moisture.py:162-200, :292, :452), with no dt argument. So the daily-derivation residual is not done; it depends on the #177 m2 product decision. Restricting Hortonian runoff to burned/impervious cells is physically defensible, because PNW forest Ksat of 15-55 mm/hr exceeds typical AR rates (water_budget.py:41-44). Moving beta4 (the Stage-2 AR regression term, climate_response.py:12-13) to #8 (aquifer-type tau) is a mismatch. It belongs with the TFN work (#23) or AR validation (#59).); agent_ready: False; missing blockers: []
- physics: The daily derivation is done (water_budget.py:160-172, with drain_tau, cap and recession rates converted per step), and TFN is #23/#8. What remains is sub-daily infiltration-excess. That is physically minor in forested PNW soils: Ksat is 15-55 mm/hr (water_budget.py:41-44) against typical AR hourly intensities of about 5-15 mm/hr. It matters for burned (hydrophobic) or impervious surfaces. beta4 belongs to the statistical Stage-2 model.
- problems:
  - The body is stale. An agent would 're-derive' an already-daily bucket.
  - It is mixed with Stage-2 beta4.
- proposed edit: Close the daily-derivation part. Retitle the remainder 'sub-daily infiltration-excess for burned/impervious cells' and move it to v0.6 (wildfire disturbance). Move beta4 to #8.

## Gaps (proposed new issues)

### Whole-system water ledger: conservation harness for coupled_water_budget (all branches, signed fluxes, dt-refinement)
- milestone: Water budget: vadose-zone physics & calibration; blocked_by: []
- why: Capillary rise creates water: about 34 mm/yr at a 0.8 m table (probe), and the audit measured 0.739 mm/day. A one-line debit still leaves a 0.004 mm residual on the legacy path. The existing test checks only the root store (test_water_budget.py:26-33). #172-#176, #225 and #227 all edit the same loop and need a shared conservation gate first.

Add a test module that sums root S, the vadose store (when present), S_y*h and the cumulative boundary fluxes (P in; runoff, interflow, baseflow, AET out) for: legacy and HAND branches, slope on/off, deep/shallow table, dry-down, storm, snowmelt, and a synthetic analysis increment logged separately. Acceptance: residual below 1e-6 mm per step in float64. Then fix the capillary debit and the signed recession so the suite passes. dt = 1 d vs 0.25 d recharge totals agree within 1%. Do not choose a physical boundary condition just to zero the residual: document the control volume.

### Ingest continuous groundwater-level records + frozen well/basin holdout manifest
- milestone: Water budget: vadose-zone physics & calibration; blocked_by: []
- why: #131 and #87 need storm-lag validation, and #137 needs held-out wells. The repo only has discrete NWIS field measurements (param 72019) aggregated to site-month medians (download_nwis_domain.py:6-15), so no storm-scale lag can be measured.

Fetch USGS daily-value groundwater levels (OGC daily collection), WA Ecology EIM continuous wells and county logger networks inside the domain. QC them, tag aquifer and screen depth, and record the support. Commit a holdout manifest (sites, basins, water years, spatial buffer) BEFORE any recalibration, for use by #137 and adoption by #189. Acceptance: a list of N continuous wells with at least 2 years of daily data and their storm-response lags, a versioned dataset with checksums, and the manifest file.

### Calibration/validation harness: basin-masked fluxes, model-hydrograph Lyne-Hollick BFI, well-cell sampling
- milestone: Water budget: vadose-zone physics & calibration; blocked_by: []
- why: calibrate_fluxes.py compares domain-wide mean fluxes over every land cell (:61-79) with 6-gauge BFI and 2-basin Q/P. It computes BFI as bf/Q rather than with the observation's filter, and it uses the domain-mean head change for well amplitude. That support mismatch biases whatever #137/#175 calibrate.

Refactor the scoring: aggregate model Q per gauged basin polygon; apply the same Lyne-Hollick filter (same alpha and passes) to the modelled daily Q; sample head at the well cells; correct Q/P for storage change over the record. Acceptance: unit tests on synthetic hydrographs; the score function reproduces the observed-side metrics when fed observed series.

### Fix HAND < d0 valley-floor ratchet in groundwater discharge
- milestone: Water budget: vadose-zone physics & calibration; blocked_by: []
- why: gw_recess = 0 where HAND <= d0 (water_budget.py:193-197), so head only rises. Probe: HAND 2 m, d0 5 m gives +0.51 m/yr with zero baseflow. It biases VSA runoff and the spatial baseflow field. Currently buried as 'verify' in P2 #177 m5.

Give cells with HAND < d0 a physically consistent discharge, e.g. relax to max(HAND, d_floor) using the local recession, or flag them as losing reaches. Acceptance: no monotone head drift in a zero-net-forcing test; count of affected cells reported; ledger passes.

### Snowpack as a carried state (SWE initial condition) + rain-on-snow / liquid retention
- milestone: Water budget: vadose-zone physics & calibration; blocked_by: []
- why: liquid_input resets SWE to 0 on every call (forecast.py:123), so mid-winter forecasts have no pack. Rain passes through the pack instantly (forecast.py:130), and warm atmospheric-river melt is under-predicted. Rain-on-snow is the PNW extreme-antecedent flood mechanism.

Carry SWE (and pack liquid water) in the state and in the forecast initial condition. Add liquid holding capacity (about 5-10% of SWE) with refreezing, and a rain-on-snow melt enhancement (advective heat plus a wind/turbulent DDF term). Acceptance: leave-stations-out SNOTEL melt-out and RoS event tests (e.g. Dec-2025 AR); conservation including the snow store.

## Verifier extra problems

- R_ref=3 mm/d (water_budget.py:88) is inconsistent with the code's own estimate of ~1.6 mm/d (:86-87) and with BFI*Q/P*P of about 1.26 mm/d. The steady-state anchor therefore drains the observed baseline on every slope cell whose recharge is below 1095 mm/yr. Probe: 5.0->8.55 m over 3 yr, baseflow 1023 vs recharge 668 mm/yr. The 10-month cold-start calibration (calibrate_fluxes.py:48) counts this storage depletion as baseflow, which inflates BFI. No issue tracks this explicitly; it belongs in #175/#137, which should require reporting the dS storage term.
- The HAND<=d0 ratchet is larger than the audit's +0.51 m/yr: about 3 m in year 1 and up to the surface by year 3 under ~1570 mm/yr, with zero baseflow. In the 10-month calibration these cells add a monotonic rise to the amplitude metric that pins S_y (calibrate_fluxes.py:76-84), so S_y=0.30 is biased by the bug.
- notebooks/close_basin_budget.py:85-86 still runs S_y=0.10 and Ka=20 and hard-codes bf_mod=0.0, contradicting the calibrated constants and the baseflow-reporting fix (water_budget.py:274-278). It is the one per-basin closure script, so it is stale and misleading.
- Model BFI in the calibration is the bf/Q volume ratio (calibrate_fluxes.py:71-73), while observed BFI comes from Lyne-Hollick separation (:13). The current 'BFI 0.52 vs 0.47' agreement compares different estimators.
- Batch 6 [227,225,177,176] puts the Rainier canopy (#225) and glacier (#227) stores, which edit the same per-step loop, ahead of the #172 ledger/store restructure. Without BLOCKED_BY on #172 (or the new ledger issue), two P2 features will be merged and then reworked.
- #52 (keep, P1 bug, #187 blocker) is unmilestoned in batch 26, behind every milestone batch. It should move to the Water-budget milestone. The sigma error is quantifiable: the dynamic term uses (theta_fc-theta_wp) where the total-water partial is (theta_sat-theta_wp), an underestimate of about 1.8x for typical loams (soil_moisture.py:323-325, 454-456). Uncertainty on theta_sat is also omitted.
- The physics tension between #131 (add vadose lag) and #100 (the calibrated model is already one month late, so a lag worsens phase) is unresolved in both issues. Agents working #131 first would degrade phase. A hard 'phase no worse' gate and the scope decision (#171) must be in place first.
- forecast.py:31-34 says 'see issue' with no number, and its docstring and stage_mvp_window.py:9 still say Hamon PET. Agents reading the docstrings will be misdirected.
- ROADMAP.md:87 marks v0.4 DONE while #100 and #223 are open in that milestone. This also expires #87's 'do not work before v0.4' soft hold, so #87 is now eligible (batch 36) to implement a second lag.
