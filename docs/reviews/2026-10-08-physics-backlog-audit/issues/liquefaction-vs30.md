# Issue family: liquefaction-vs30

Seventeen issues in two milestones. (A) "Hazard: Sanger-Maurer liquefaction framework": epic #139 plus #140-#149. (B) "v0.3 Vs30 densification": #81, #82, #83, #84, #86 (#85 is in the same milestone but outside this family), plus the unmilestoned #54. Nothing on origin/main computes liquefaction. src/models/soil_mechanics.py:64 raises NotImplementedError, and the only liquefaction-adjacent code is Vs30 (src/data/fetch_vs30.py), NEHRP class probability (fetch_vs30.py:73-121) and seasonal_high_water_table (src/io/landlab_export.py:58). Five findings change how this family should be run. (1) The epic's premise is quantitatively weak. In the Zhu et al. 2017 non-coastal GLM (X = 8.801 + 0.334 ln PGV - 1.918 ln Vs30 + 5.408e-4 P - 0.2054 dw - 0.0333 wtd; coefficients recalled from memory, verify), moving the water table from 1 to 5 m changes P by only 0.033. A +/-0.35 ln shift in Vs30 changes P by 0.32 and a 1.8x shift in PGV changes it by 0.10 (probe: scratchpad/wf/liq/zhu_sens.py). The "dynamic water table" that the epic calls the twin's main contribution is therefore the weakest of the three inputs, about 10x weaker than Vs30. (2) The model is not pinned. "Sanger-Maurer" in the bibliography is a geospatial-AI model (Sanger & Maurer 2025, arXiv 2509.10965; docs/references.bib:338), not a GLM with published coefficients, while the issues say "Zhu 2017 / Maurer". The two models have different inputs and different probability meanings. (3) The input the epic depends on does not exist: "No operational monthly series exists yet" for depth-to-water (landlab_export.py:333-335). (4) Several Vs30 densification issues contain physics errors. SOLUS restrictive-layer depth is a pedologic depth of about 2 m or less, not depth to rock, so it is the wrong h for #83. The existing lithology crosswalk lumps Holocene deposits with Vashon glacial units (rasterize_geology.py:10-12), which defeats #84. The block-mean constraint in #86 must be applied in slowness space and contradicts the bias-correction claims in #83. (5) None of the holds are machine-readable. The user's v0.3 pause (ROADMAP.md:129-133), the deferral of #146, and the #81-first gate are not encoded, so the queue runs v0.3 at batches 14-15 with the #81 gate last, and runs #146 at batch 26. #54 is essentially done but is still queued at batch 29.

**Queue ordering:** Queue simulation (scratchpad/queue_sim.jsonl): batch 14 = [86, 85, 84, 83], batch 15 = [82, 81], batch 24 = [145, 144, 143, 142], batch 25 = [141, 140], batch 26 = [149, 148, 147, 146], batch 29 = topic-geotech [64, 54]. No member of this family is in queue_held.txt. Problems: (1) v0.3 is fifth in MILESTONE_ORDER (gaia_group_issues.py:61), so the user-paused Vs30 work (ROADMAP.md:129-133) runs early, before landslide and liquefaction, and the gate #81 runs after the four issues it gates, because chunking follows descending issue number and both chunks are unranked. (2) Within the liquefaction milestone, P1 chunks sort before P2, so inputs #143/#144 run in batch 24, one batch before #141, with no BLOCKED_BY. If PRs are not merged between batches, #141 is built without them. #142, a multi-month water-budget calibration that depends on #137 and a non-existent DTW series, shares a 4-slot batch with two docs issues (#145) and a raster-sigma task (#144). (3) #140 (reframing) should precede #141, not share a batch with it; it is cheap and should merge with #147. (4) #146, explicitly 'Future', is executable in batch 26, and #149 is a cross-subsystem grab-bag that will produce an incoherent PR. (5) #54 (done) in batch 29 invites duplicate work. (6) The epic #139 is skipped by the grouper, so its ordered sub-issue list has no effect. Recommended: hold #81-#86 and #146 by label; close #54, #147 (merged into #140) and #149 (distributed); add BLOCKED_BY 141:[143,144,decision-gap], 142:[137], 82/83/84:[81], 86:[81,84]; insert the value-of-information gap issue between #143/#144 and #141, and run #142 only if it passes.

## #139 [epic] Sanger-Maurer liquefaction framework — a dynamic-water-table susceptibility product
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [137, 143, 144]
- physics: Framing it as a regional susceptibility screen rather than an LPI is right, and the Sept 10 audit agrees (soil-twin-system-audit:137; roadmap-review:20). The value proposition is wrong as stated: 'the twin's genuine contribution' is the modeled seasonal-high depth-to-water, but in Zhu 2017 wtd carries -0.0333 per metre, so a 1 to 5 m change gives dP of about 0.03, against about 0.3 for 1-sigma Vs30 and 0.1 for PGV (wf/liq/zhu_sens.py). Zhu's wtd was also fitted on an equilibrium mean water-table model (Fan et al. 2013), so substituting a P10 seasonal high is a covariate shift outside the fitted model. The 'Sanger-Maurer framework' named in the title is a geospatial-AI model (references.bib:338-346), not the published logistic model the MVP text describes.
- problems:
  - The model is not pinned: Zhu 2017 GLM and Sanger & Maurer 2025 geospatial AI are conflated (roadmap-review:89 demands pinning)
  - The premise that the dynamic water table adds value is unquantified and, under Zhu 2017, an order of magnitude below Vs30/PGV uncertainty
  - Sub-issue order and blockers are not encoded; the grouper skips the epic (gaia_group_issues.py:176-177) and has no BLOCKED_BY entries for 140-149
  - It depends on a depth-to-water time series that does not exist (landlab_export.py:333-335)
  - There is no event-based validation (WA DNR/Palmer are susceptibility maps, not event outcomes)
- proposed edit: Add a 'Decision required (human)' section that picks one model and version with its coefficient/weights source: Zhu 2017 Model 2 (BSSA 107:1365, plus Rashidian & Baise 2020 caps), or Sanger & Maurer 2025 if its weights are obtainable. State the probability semantics (Zhu P is converted to areal extent, LSE, not a point probability). Replace 'genuine contribution' with a hypothesis gated on the sensitivity study (new gap issue). Add order: 140/147 (docs) -> 144, 143 -> sensitivity gate -> 141 -> 142 (only if the gate passes) -> 146 deferred. Add the needs-human-decision label until the model is chosen. Add an event-validation sub-issue (Nisqually 2001).

## #140 Reframe Vs30 as site amplification / class, NOT a liquefaction triggering variable
- verdict: **rewrite** (verifier upheld); agent_ready: True; missing blockers: []
- physics: The physics is correct: Vs30 is a 30 m harmonic average and a site-amplification proxy, while triggering lives in a 1-10 m critical layer (Andrus-Stokoe and Kayen use the overburden-corrected Vs1 of that layer). It is largely already true on main. No doc derives CSR/CRR from Vs30 (grep finds only 07b-resolution-requirements.qmd:41-42, which already tiers screening against CPT triggering). The remaining errors are elsewhere. 07-hazard-integration.qmd:89-95 says 'For the Sanger liquefaction GLM the stiffness is delivered as NEHRP site-class probability', but every geospatial liquefaction model takes continuous ln Vs30, not P(class). 03b:31 and 07:89 call the Sanger & Maurer AI model a 'GLM'. 01-input-data.qmd:54 still lists Wald-Allen as the Vs30 source.
- problems:
  - Cited lines (fetch_vs30.py:175-218) are stale; the profile integrators are now at fetch_vs30.py:188-298
  - The 'remove CSR/CRR-from-Vs30 implication' task has no current target; the real defect is NEHRP-probability-as-GLM-input
  - There is no testable acceptance
- proposed edit: Retarget: (a) 07-hazard-integration.qmd:85-95: the GLM consumes ln Vs30 with its sigma, and the NEHRP P(class) is a separate design-engineering product; (b) stop calling Sanger & Maurer 2025 a GLM (03b:31, 07:89); (c) 01-input-data.qmd:54: SVM preferred, Wald-Allen fallback; (d) soil_mechanics.py:1-14 and :61-62 docstrings. Acceptance: grep shows no 'GLM' attached to sanger2025liquefaction and no P(class) described as a liquefaction-model input; the book builds. Merge #147 into this as one docs PR.

## #141 MVP: geospatial liquefaction GLM driven by the dynamic seasonal-high water table + scenario ShakeMap PGV
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [143, 144]
- physics: A published logistic screen is the right MVP, but four physics problems need fixing first. (1) The acceptance test 'dynamic DTW changes the map vs static' passes trivially for any nonzero change; under Zhu 2017 the change is at most about 0.03 in P for a 4 m swing, well inside the Vs30-driven sigma_P of about 0.3. (2) ShakeMap PGV already contains a site term computed with the USGS Vs30, and Zhu 2017 was fitted that way. Pairing ShakeMap PGV with the twin's SVM Vs30 applies two inconsistent site models; either use ShakeMap's own Vs30 grid in the GLM or regenerate the ground motion with the SVM Vs30. (3) The DTW product the twin would supply is regressed on Vs30 itself (baseline_regression.py:70; fetch_gaia.py:374-377), so entering both double-counts Vs30. (4) Zhu wtd was fitted on Fan 2013 mean water-table depth; a P10 seasonal high is outside the calibration domain unless refitted or bounded. Benchmarking against WA DNR/Palmer compares an event-conditioned probability with a static geologic susceptibility class (roadmap-review:89); it can serve as a sanity check, not validation.
- problems:
  - The model and coefficients are not pinned
  - The acceptance criteria are trivially satisfiable and contain no event validation
  - The required time-varying DTW series does not exist (landlab_export.py:333-335)
  - Blockers #143 (PGV) and #144 (Vs30 sigma) are not in BLOCKED_BY; the queue runs #141 in batch 25, right after them in batch 24, likely before they merge
  - The probability semantics (Zhu probability vs areal extent LSE; PGV < 3 cm/s and Vs30 > 620 m/s cutoffs) are unstated
- proposed edit: Pin 'Zhu et al. 2017 Model 2 with Rashidian & Baise 2020 caps; coefficients transcribed with a table citation and unit test against the paper's worked values'. Inputs: ln Vs30 with sigma from #144, ShakeMap PGV with sigma_lnPGV from #143, and DTW from a product that does NOT use Vs30 as a predictor (or quantify the collinearity). Monte Carlo over all three. Acceptance: (a) a probability map plus LSE with sigma; (b) a variance decomposition of P into Vs30, PGV and DTW shares, with the pre-registered statement that if the DTW share is under 10% the 'dynamic' claim is dropped from the docs; (c) a hit-rate/ROC against the observed 2001 Nisqually liquefaction sites using the 2001 ShakeMap, stating whether Nisqually is in Zhu's training set; (d) agreement with WA DNR/Palmer reported as a contingency table, labelled a sanity check. Add BLOCKED_BY 141:[143,144].

## #142 Seasonal-high depth-to-water in liquefiable units: sub-1.5 m accuracy, uncertainty, non-TOPMODEL prior
- verdict: **split** (verifier upheld); agent_ready: False; missing blockers: [137]
- physics: The truth-set fix in the Aug 20 comment (measurement_target == water_table, tail-coverage scoring) is correct, and the classifier now exists (src/features/well_hydrostratigraphy.py:53,129). The accuracy target is not derived from the consuming model. For the GLM screen, 1 m of DTW error is about 0.008 in P under Zhu 2017, so sub-metre accuracy is not needed for #141. Sub-metre accuracy matters only for depth-resolved LPI (#146), where the saturated thickness above 20 m with weight w(z) = 10 - 0.5z dominates. The title says sub-1.5 m, the body sub-metre, and domain_gates.py:31,33 sets the valley-fill threshold at 1.5 m and coastal at 2.0 m. Replacing TOPMODEL (water_budget.py:287) in tidal/confined fill is physically right: tidal fill heads follow sea level plus tidal damping, not TWI. It is, however, a model-development project, not an issue.
- problems:
  - Bundles four deliverables: truth-set restriction, lowland-specific scoring, a coastal/confined non-TOPMODEL prior, and DTW pdf propagation
  - Contradictory accuracy target (title vs body), noted in roadmap-review:89
  - Depends on #137 (specific yield/held-out validation) and a DTW time series, neither encoded
  - P10 over a short pilot series is not a return-period quantity (also #149 m2)
- proposed edit: Split into: (142a) restrict the truth set to measurement_target == water_table inside young alluvium/fill, report exclusion counts and lowland-only block-CV RMSE/bias plus PIT coverage of the P10 tail (agent-ready on existing code). (142b) Coastal/tidal/confined head prior to replace TOPMODEL there, needing a human hydrogeologist decision (hold). (142c) Set the accuracy target from the consumer: about 1.5-2 m for the #141 screen, sub-metre only for #146, and reconcile domain_gates.py coastal 1.0/2.0. Add BLOCKED_BY 142:[137].

## #143 Ingest USGS ShakeMap ground motion (PGA / PGV / Mw) with epistemic uncertainty
- verdict: **rewrite** (verifier upheld); agent_ready: True; missing blockers: []
- physics: The need is real: no ground-motion code exists on main (only the Vs30 URL at fetch_vs30.py:38). Missing physics: ShakeMap grids already embed a Vs30-based site amplification (the USGS/Heath hybrid Vs30), so the grid must carry ShakeMap's own Vs30 alongside PGV, or the twin must regenerate PGV with a GMPE plus the SVM Vs30 for consistency with #141. ShakeMap supplies per-cell sigma (uncertainty.xml / std grids, typically sigma_lnPGV around 0.5-0.65 away from stations), which should be used directly. Scenario candidates: the USGS Seattle-fault and Cascadia M9 scenario ShakeMaps, and the 2001 Nisqually event map for validation.
- problems:
  - Overlaps #124 (event catalog), and #121-#124/#143 consolidation is flagged in roadmap-review:103
  - 'Epistemic uncertainty' is undefined (GMPE branches vs ShakeMap sigma)
  - No acceptance criteria
- proposed edit: Do: fetch the ShakeMap grid.xml plus uncertainty grids for (i) the 2001 Nisqually event and (ii) one named scenario (Seattle-fault M7.x or Cascadia M9); reproject to the 90 m grid; store PGA, PGV, sigma_lnPGV, Mw and ShakeMap's own Vs30; cache offline-testable fixtures. Acceptance: unit test round-trip on a fixture grid; PGV units cm/s; the sigma field is present; the ShakeMap Vs30 is stored so #141 can compare it with the SVM. Rainier3d reads the USGS hybrid Vs30 by HTTP range requests (rainier/src/rainier3d/surface/soil.py:306-332), a pattern worth reusing instead of the 600 MB download in fetch_vs30.py:139-161.

## #144 Per-cell Vs30 sigma field so P(NEHRP class) is not decorative
- verdict: **rewrite** (verifier upheld); agent_ready: True; missing blockers: []
- physics: Still accurate: nehrp_class_probabilities requires vs30_std (fetch_vs30.py:73-107) and no producer of a sigma raster exists (only tests/test_vs30.py calls it). sigma_lnVs30 of about 0.3-0.5 for slope proxies is in the right range. There is a further problem the issue misses. Wald-Allen assigns exactly 180 m/s to all flat cells, which sits on the E/D boundary, so every flat cell gets P(E) = 0.50 regardless of sigma (probe: slope 0.001-0.12 deg gives P = [0.50, 0.46, 0.04, 0, 0]). That is decorative in the same sense the issue complains about. For the GLM, sigma should be propagated in ln Vs30 directly, not via P(class). For the SVM, sigma should come from the province profile residuals in Grant, Wirth & Stone 2025, which need #81's data if not published.
- problems:
  - Cited lines are stale (Wald-Allen is now fetch_vs30.py:51-63)
  - No acceptance criteria
  - SVM sigma may need the #81 profiles
- proposed edit: Do: write vs30_sigma_ln_90m.tif with a source-specific sigma: Wald-Allen a documented constant from the literature (cite the value and table); SVM from per-province residuals (cite, or mark pending #81). Write a per-cell source-provenance band. Assign Wald-Allen the bin geometric mid-value, not the lower edge, so flat cells do not sit exactly on 180. Acceptance: a test that P(class) for flat Wald-Allen cells is not pinned at 0.5; the sigma raster co-registers with vs30_90m.tif; documented sigma values with citations.

## #145 Firewall the coseismic dv/v damage/healing state from liquefaction TRIGGERING (category error)
- verdict: **rewrite** (verifier upheld); agent_ready: True; missing blockers: []
- physics: Correct. Coseismic dv/v drop is nonlinear damage with log-time healing (03c:65-83). Triggering is excess pore pressure reaching r_u = 1 within seconds, a different mechanism, depth and timescale. The category error also sits in code: soil_mechanics.py:11-14 calls dv/v 'a time-varying proxy for effective stress / pore pressure' and :61-62 asks for a liquefaction susceptibility term from it. forecast.py:181-183 produces Vs30(t) from dv/v, which as a GLM input is both conceptually wrong and numerically negligible (0.2% Vs30 gives dX of about 0.004). The issue must also preserve the legitimate path: seasonal hydrologic dv/v constraining the water table (03b:95-102), which then feeds DTW. The firewall applies to the damage state and to Vs30(t) entering the hazard model, not to the use of dv/v in hydrology.
- problems:
  - Docs-only scope misses the code contract in soil_mechanics.py and Vs30(t) in forecast.py
  - No acceptance criteria
  - Could over-firewall the legitimate dv/v -> water-table assimilation path
- proposed edit: Extend Do: edit the soil_mechanics.py docstring/contract to say dv/v is not a pore-pressure or triggering input; add a guard so any liquefaction consumer rejects time-varying Vs30 (Vs30 is a static site covariate). State explicitly that dv/v may constrain the water table via the hydromechanical operator (#198). Acceptance: docs and code comments updated; a unit test that the liquefaction entry point raises on a time-varying vs30.

## #146 Future: depth-resolved triggering (CPT/SPT + Vs(z) critical layer + CSR/CRR)
- verdict: **defer** (verifier upheld); agent_ready: False; missing blockers: [141]
- physics: The physics is right (Boulanger-Idriss 2014 CPT, Andrus-Stokoe 2000 / Kayen 2013 Vs1, a fines/SBT model, LPI/LSN on the critical layer). It is the only issue where sub-metre DTW accuracy matters. It requires data access agreements (WSDOT, Port of Seattle, WA DNR boring databases) and a human scope decision; roadmap-review:105 says to keep its deferral machine-readable.
- problems:
  - Eligible in the queue (batch 26 with #147-#149) despite 'Future/later'
  - No needs-human-decision label or BLOCKED_BY
  - Data acquisition is not agent-executable
- proposed edit: Add the needs-human-decision label (or remove the milestone and add a 'deferred' label the grouper filters). Add BLOCKED_BY 146:[141]. Note in the body that #142's sub-metre requirement belongs here.

## #147 Scope honestly: a susceptibility screen, not an LPI — 90 m from a 200 m SVM cannot resolve facies
- verdict: **merge** (verifier upheld); agent_ready: True; missing blockers: []
- physics: Correct and mostly done: 07b-resolution-requirements.qmd:41-42,62 already tiers liquefaction as a 100 m-1 km screen refined by point CPT, and ROADMAP.md:131-133 states the SVM 200 m limit. The cited ROADMAP.md:100-104 is stale (now :129-133). What remains is making 07-hazard-integration.qmd and the README use the same wording, which is the #140 docs pass.
- problems:
  - Stale line refs
  - Largely satisfied by 07b
  - Duplicates the #140 docs scope
- proposed edit: Merge into #140 as one docs PR: add a scope box to 07-hazard-integration.qmd §Liquefaction ('regional susceptibility screen; not LPI; resolution bounded by 200 m SVM and 1:100K geology'), linking 07b. Close #147.

## #148 Wald-Allen Vs30 proxy is near-degenerate on flat liquefiable ground — document and guard
- verdict: **rewrite** (verifier upheld); agent_ready: True; missing blockers: []
- physics: Correct and confirmed: a gradient below 2.2e-3 (about 0.126 deg) maps to a single bin of 180 m/s (fetch_vs30.py:44-45, 51-63), so there is no discrimination within the liquefiable population. More defects than the issue lists: (a) values are bin lower edges (180/240/300/... per range), a systematic low bias of about 10-15% per bin; (b) the Wald & Allen 2007 active table's E-class edge at gradient 1e-4 (Vs30 < 180) is missing, so true E sites cannot be identified (edges from memory; verify against the paper's Table 1); (c) the proxy was calibrated on 30-arcsec slopes and is applied to 90 m 3DEP slope, which is steeper, so upland Vs30 is biased stiff; (d) main() logs 'Wrote Vs30 (svm)' using args.source even when get_vs30 fell back to Wald-Allen (fetch_vs30.py:449-451), a provenance mislabel of the kind ROADMAP.md:180-181 warns about. The fallback is no longer silent (warning at :365), but it is not recorded in the output.
- problems:
  - Stale line refs (:367-373 is now :371-399)
  - Misses the lower-edge bias, the missing E bin, resolution dependence and the provenance mislabel
- proposed edit: Do: (1) write the actually-used source to raster tags/attrs and the log line; (2) fail, or require an explicit flag, when Wald-Allen would be used inside liquefiable units (needs the geology mask from #84 or the hydrogeologic domains); (3) add the 1e-4 E edge and use bin geometric centres, after verifying against Wald & Allen 2007 Table 1 (absorb #149 m1); (4) document the 30-arcsec calibration. Acceptance: tests for the provenance tag on fallback, the presence of the E bin, and the flat-cell value not equal to 180.

## #149 Minor fixes (liquefaction review)
- verdict: **split** (verifier upheld); agent_ready: False; missing blockers: []
- physics: A grab-bag of four unrelated items, two of them substantive (roadmap-review:101). m1 (verify Wald-Allen edges): the edges match the active table except the missing 1e-4 E edge, and it belongs in #148. m2 (seasonal-high tied to a return period): correct, P10 of a short pilot series is not a return-period statistic; belongs in #141/#142. m3 (single-band S_theta depth-diluted to -0.08, 03b:123): a dv/v sensitivity item unrelated to the GLM; belongs in #198/#145. m4 (coastal gate 1.0/2.0 m vs valley-fill 0.75/1.5 m, domain_gates.py:31,33): only matters for #146-class triggering, and tidal-fill DTW error is bounded by tidal amplitude; belongs in #142c.
- problems:
  - Mixed scope across three subsystems; labelled 'minor' and P2 while containing tail-validation requirements
  - Line refs partly stale (03b:99 is now :123)
- proposed edit: Move m1 to #148, m2 to #141 acceptance (state the epoch: an annual P10 over at least N water years, or a scenario-date conditional), m3 to #145/#198, m4 to #142c. Close #149.

## #54 P1: Replace synthetic Vs30 with a real Vs30 model + real uncertainty
- verdict: **close-superseded** (verifier upheld); agent_ready: False; missing blockers: []
- physics: Done in substance. HAND is gone; Wald-Allen (PR #61, per the 2026-07-07 comment), the SVM (fetch_vs30.py:296-367, staged on Kopah per ROADMAP.md:45, D4 #95 closed) and the USGS grid are wired in get_vs30. Remaining parts are owned elsewhere: measured profiles (#81), per-cell sigma (#144). The 'Sanger-Maurer via GAIA vs-STAC' source is still a placeholder (fetch_vs30.py:164-178), which is acceptable.
- problems:
  - Queued as batch 29 (topic-geotech with #64), so an agent would redo finished work
  - No milestone
- proposed edit: Close with a comment: superseded by #144 (sigma) and #81 (measured anchors); the implementation is on main at fetch_vs30.py:371-399.

## #81 Vs30 densification: source measured Vs profiles (the validation anchor — BLOCKER)
- verdict: **hold-human** (verifier upheld); agent_ready: False; missing blockers: []
- physics: This is the right gate: scoring against the SVM is circular. It has gaps. (1) The 649 profiles are the SVM's own training data (fetch_vs30.py:5-8), so comparing 'SVM vs densified' on them flatters the SVM, though only a little since it is province-averaged; independent profiles not used by Grant et al., or SVM refits with blocks left out, are needed. (2) Many MASW/ReMi profiles end shallower than 30 m; vs30_from_vs_profile returns NaN when not covered, so the issue must specify a Vs30-from-Vsz extrapolation (Boore 2004 / Boore et al. 2011) with its added sigma, or most profiles drop. (3) Obtaining data from authors/WSDOT is a human task.
- problems:
  - Under the user's v0.3 pause (ROADMAP.md:129-133), which is not machine-encoded
  - The queue runs it LAST in the milestone (batch 15) after #83-#86 (batch 14), the inversion flagged in soil-twin-system-audit:92
  - Data acquisition needs human contact/agreements
- proposed edit: Add the needs-human-decision label (pause). Add: a profile-independence flag (in SVM training set: yes/no); a depth_max < 30 m extrapolation rule with sigma; report the in-pilot count split by geologic unit (feeds #84). In the grouper, BLOCKED_BY 82/83/84/86:[81].

## #82 Vs30 densification: fetch the missing SOLUS soil covariates (bulk density, organic carbon, soil thickness)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [81]
- physics: The fetch is done: dbovendry, soc, resdept_all_cm and anylithicdpt_cm are in src/data/fetch_solus_domain.py:16-58 (via the closed #94; roadmap-review:79 calls #82 stale). The physics claim is overstated. SOLUS samples only the top ~1-2 m (point depths 0-100 cm, fetch_solus_domain.py:27-28). A 2 m cap at 120 m/s over 250 m/s lowers Vs30 by only about 7% (30/(2/120+28/250) = 233 vs 250 m/s). The thick (5-15 m) Duwamish/Kent-valley peat and organic tideflat deposits that produce the NEHRP E tail are invisible to SOLUS and come from geology (#84). 'Residual variance vs the SVM' is the circular target #81/#86 forbid.
- problems:
  - Fetch already done
  - Scoring target is circular (residual vs SVM)
  - Under the v0.3 pause
- proposed edit: Retitle 'Assess SOLUS bulk density/SOC as Vs residual covariates'. Do: void ratio from dbovendry with a theta_sat cross-check; explanatory power for measured-profile residuals (#81) under block CV, not the SVM residual; state the 2 m sampling-depth limit up front. Keep under the pause; BLOCKED_BY [81].

## #83 Vs30 densification: two-layer travel-time model from soil thickness / depth-to-bedrock
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [81]
- physics: The formula is correct (harmonic travel time, exact reduction for h >= 30), but the proposed h is wrong. SOLUS resdept/anylithicdpt is a pedologic restrictive depth of about 2 m or less (often dense Vashon lodgement till, about 400-600 m/s, not rock). Using it as h with CVM rock Vs below would put about 28 m of 'rock' under most columns and bias Vs30 strongly high. In the Puget Lowland, glacial/Quaternary sediment is tens to over 1000 m thick, so h >= 30 almost everywhere liquefaction matters; the model is a no-op there and helps only in thin-regolith Cascade uplands (site amplification, not liquefaction). The 'single biggest structural win' claim is unsupported for the hazard this family targets. GAIA dtb (fetch_gaia.py:415-425) is of unknown provenance and accuracy in deep basins.
- problems:
  - Wrong thickness variable (pedologic restriction ≠ soft-sediment thickness)
  - No-op in the liquefaction region
  - Acceptance 'beats plain SVM against #81' depends on #81, which is paused
  - The CVM below the SVM may already encode the soil/rock transition, risking double-counting
- proposed edit: Restate h as soft-sediment (Holocene + soft Pleistocene) thickness over the stiff unit, from geology/boring compilations or the SVM/CVM layer interface, never SOLUS restrictive depth. Restrict scope to thin-regolith terrain. Add a regression test that h >= 30 gives the identical result, and a test rejecting h taken from a variable capped at about 2 m. Keep under the pause; BLOCKED_BY [81].

## #84 Vs30 densification: stratify Vs(z) profiles by surficial geology (glacial overconsolidation)
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [81]
- physics: The best-founded issue in the milestone. Glacial overconsolidation (Vashon till/outwash about 400-600+ m/s vs Holocene alluvium/fill/peat about 150-250 m/s) is the first-order Puget Vs control, and stratifying by unit rather than regressing is correct. Two factual errors. (1) The 'existing lithology crosswalk' maps to 4 hydrogeologic classes (0 unconsolidated / 1 fractured bedrock / 2 young volcanic / 3 CRBG; rasterize_geology.py:10-12), which merges Holocene and Vashon units, the exact distinction needed. A new age-plus-genesis crosswalk is required. (2) The shipped source is DNR 1:100K (rasterize_geology.py:7), not 1:24,000, and rasterizing to 90 m discards the 10-30 m signal the issue values.
- problems:
  - Relies on a crosswalk that destroys the needed classes
  - Overstates map scale
  - Depends on #81 counts per unit; under the pause
- proposed edit: Do: a separate vs_geology_crosswalk.json keyed on age and genesis (artificial fill, Holocene alluvium, peat/organic, tideflat/estuarine, Vashon recessional outwash, Vashon till, advance outwash, pre-Fraser, bedrock), from 1:24K where available and otherwise 1:100K, with a fractional-cover raster at 90 m rather than a majority class. Acceptance as written (per-unit counts, explicit SVM-prior fallback). BLOCKED_BY [81]; keep paused.

## #86 Vs30 densification: mean-preserving block-constrained downscaling + block CV
- verdict: **rewrite** (verifier upheld); agent_ready: False; missing blockers: [81, 84]
- physics: The architecture is sound: predict profile parameters rather than Vs30, residuals from the prior, no lat/lon, block CV against measured profiles, a negative result allowed. Three physics gaps. (1) Vs30 is a harmonic (travel-time) quantity, so the block constraint must preserve the mean slowness (1/Vs30, or equivalently 200 m block travel time), not arithmetic Vs30; an arithmetic mean-preserving redistribution biases the block high. (2) Strict SVM block-mean preservation contradicts #83/#85 and the issue's own (b): if the SVM is biased (e.g., ignores shallow stiff units), the constraint forbids the correction measured profiles would justify. Split into a mean-preserving redistribution step and a separately validated block-bias correction. (3) With 649 profiles PNW-wide and probably tens in the pilot, block-CV skill estimates will be very noisy; a power analysis is needed before (b) is meaningful.
- problems:
  - Constraint space (slowness vs velocity) unspecified
  - Internal contradiction with the bias-correcting siblings
  - Depends on #81 and #84; the queue runs it in batch 14 before #81
  - Under the user pause
- proposed edit: Specify the slowness-space block constraint with a unit test (block-average of 1/Vs30 equals the SVM within tolerance). Separate the bias-correction step with its own held-out test. Add a minimum held-out count per fold, decided from the #81 count. BLOCKED_BY 86:[81,84]; needs-human-decision until the pause lifts.

## Gaps (proposed new issues)

### Value-of-information gate: does the dynamic water table matter in the chosen liquefaction model?
- milestone: Hazard: Sanger-Maurer liquefaction framework; blocked_by: [143, 144]
- why: The epic's justification (#139) is unquantified. A probe of Zhu 2017 Model 2 (scratchpad/wf/liq/zhu_sens.py) gives dP = 0.033 for DTW 1 to 5 m, against 0.32 for Vs30 +/-0.35 ln and 0.10 for PGV x1.8. #142's expensive sub-metre DTW work should not start on #141's behalf unless this gate passes.

For the pinned model (Zhu 2017 Model 2, or Sanger & Maurer 2025 if weights are obtainable), compute a variance-based (Sobol) decomposition of P/LSE over realistic input pdfs on the Puget lowland: ln Vs30 (sigma from #144), ln PGV (ShakeMap sigma from #143), DTW (pilot seasonal range, plus the static-vs-seasonal-high difference). Acceptance: a table of first-order indices per input; a decision rule recorded in #139: if the DTW share is under 10%, the 'dynamic water table' claim is removed from 07-hazard-integration.qmd and #142's accuracy target is set by #146 only. Coefficients transcribed with a citation and a unit test.

### Event-based validation of the liquefaction screen against observed ground failure (2001 Nisqually; 1949/1965)
- milestone: Hazard: Sanger-Maurer liquefaction framework; blocked_by: [141, 143]
- why: WA DNR/Palmer are static susceptibility maps; agreement with them is not validation of an event-conditioned probability (roadmap-review:89). There is no observed-outcome test anywhere in the family.

Compile mapped liquefaction/no-liquefaction observations for 2001 Nisqually Mw 6.8 (and 1949 Olympia / 1965 Seattle-Tacoma where digitized), with the corresponding ShakeMaps. Score #141 output: ROC/AUC, Brier score, reliability. State whether each event is in the model's training set (if so, it is a calibration check, not validation). Report the DTW epoch used (Feb 2001 is wet season) and whether the twin can hindcast it.

### Decision record: pin the liquefaction model, version and probability semantics (needs-human-decision)
- milestone: Hazard: Sanger-Maurer liquefaction framework; blocked_by: []
- why: The milestone is named for Sanger & Maurer 2025 (a geospatial-AI model, arXiv 2509.10965) while #141 describes a Zhu 2017 GLM. These differ in inputs, availability of weights and output meaning. An agent will otherwise pick one arbitrarily.

Human decides: Zhu 2017 Model 2 (+ Rashidian & Baise 2020 caps), USGS ground-failure implementation, or Sanger & Maurer 2025 (confirm weights/licence). Record: inputs and their native datasets (which Vs30, which wtd model the coefficients were fitted on), output meaning (point probability vs areal extent LSE), applicability cutoffs. Label needs-human-decision; #141 is blocked on it.

### Encode the v0.3 Vs30 pause, the #81-first gate, and #146 deferral in the GAIA grouper
- milestone: Software: CI, tests, reproducibility, scale; blocked_by: []
- why: The queue runs v0.3 at batches 14-15 with #81 last and #146 at batch 26; BLOCKED_BY (gaia_group_issues.py:86-104) has no entry for this family, and the grouper filters only 'epic' (:176). Flagged by soil-twin-system-audit:92-94,199 and roadmap-review:105.

Add a label-based hold (needs-human-decision / paused) that the grouper skips, and apply it to #81-#86 and #146. Add BLOCKED_BY entries 82:[81], 83:[81], 84:[81], 86:[81,84], 141:[143,144,<decision issue>], 142:[137], 146:[141]. Test: the queue simulation contains none of #81-#86 or #146 and holds #141 while #143/#144 are open.

### Seasonal-high DTW time-series product for hazard consumers (hindcast + scenario epoch)
- milestone: Water budget: vadose-zone physics & calibration; blocked_by: [137]
- why: #141's core input does not exist: 'No operational monthly series exists yet (only a short pilot)' (landlab_export.py:333-335). Without it, the 'dynamic' MVP falls back to the static baseline_dtw_m.tif, which is itself regressed on Vs30 (baseline_regression.py:70), creating collinearity with the GLM's Vs30 term.

Produce a multi-year monthly DTW Zarr over the Puget lowland from the water-budget model, with sigma, using a predictor set that excludes Vs30 (or report the Vs30-DTW correlation). Define the hazard epoch: an annual P10 over at least N water years with a stated exceedance meaning, plus date-conditional DTW for event hindcasts. Acceptance: PIT coverage of the P10 tail on measurement_target == water_table wells (#142a).

## Verifier extra problems

- Hold mechanism does not exist. gaia_group_issues.py filters only the 'epic' label (line 178); needs-human-decision is applied to PRs, not read from issues (gaia-automation.md:106,320). Every proposed hold (#81, #86, #139, #146) that relies on that label, a 'deferred' label, or removing the milestone will still be queued. Only BLOCKED_BY entries or a grouper change actually hold issues.
- #85 (v0.3, 'effective-stress coupling to the water table (makes Vs dynamic)', batch 14, no priority label) is outside the family list. It is under the same ROADMAP pause, depends on #81, and directly contradicts the #145 guard that liquefaction must reject time-varying Vs30. It needs BLOCKED_BY [81] and a scope note saying dynamic Vs is a monitoring quantity, not a GLM input.
- Covariate shift is not addressed anywhere in the family. Zhu 2017 coefficients were fitted on the slope-proxy USGS Vs30 and a global equilibrium water table. Swapping in SVM Vs30 shifts the logit by about 0.26 (lowland 206 vs 180 m/s), roughly 8x the effect of a 1 m DTW change (0.033/m). This can silently dominate any 'dynamic water table' signal.
- Zhu 2017 coastal versus non-coastal model choice: as I recall it, only the non-coastal model (Model 2) contains wtd, and the whole Puget lowland is coastal. This needs verifying against BSSA 107:1365 before #141 is pinned, because it decides whether DTW enters the screen at all.
- 07b-resolution-requirements.qmd:43 claims that a few tens of cm of DTW error can flip a liquefiable cell. That is LPI/CPT logic and is inconsistent with the GLM screen being built. It, together with 07:80 (sub-metre target), drives the inflated #142 accuracy requirement and should be corrected in the #140/#147 docs PR.
- tests/test_vs30.py:117-118 asserts wald_allen_vs30(flat) == 180 and labels it NEHRP E, but np.digitize(180, NEHRP_BOUNDS) assigns class D. Any #144/#148 bin-centre or E-bin fix must state that this test is updated. Otherwise an agent will see a test fail and either revert or appear to soften a gate.
- Boundary pinning is wider than flat ground: the 360 and 760 Wald-Allen bin values also sit exactly on NEHRP boundaries (D/C, C/B), so roughly half the P(class) mass is split by construction in three of the seven bins.
- #144 and #148 both propose rewriting _WA_ACTIVE_VS30 (bin centres) in different batches (24 and 26). Assign the change to one issue.
- Provenance mislabels: the Vs30 raster is called 'Sanger & Maurer 2025' in baseline_regression.py:12,70,294 and soil_mechanics.py:47,73, and README.md:15 says 'Sanger liquefaction GLM'. The audit's #140 file list leaves all of these out.
- Rashidian & Baise 2020 and the Palmer/WA DNR susceptibility maps are not in docs/references.bib. Given the fabricated-citation history recorded at references.bib:334-337, the #141 rewrite should provide verified DOIs rather than leave agents to find them.
- Line 89 of the 2026-09-10 roadmap-review notes that a WA DNR/Palmer comparison does not calibrate an event probability. The audit's Nisqually 2001 event validation addresses this, but whether Nisqually 2001 is in Zhu 2017's training set is unknown to me and must be checked; if it is, the validation is in-sample.
