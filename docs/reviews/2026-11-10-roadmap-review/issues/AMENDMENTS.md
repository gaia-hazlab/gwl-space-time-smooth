# Proposed amendments to existing issues (drafts; nothing posted)

"Current" is quoted from `snapshot/open_issues.json` (current scope, above the first `<details>`).
On posting, the previous scope goes under `<details>` as on 2026-11-09. No closes, no hold removals.

## A. Blocker lines (sequencing)

| Issue | Current | Proposed | Reason |
|---|---|---|---|
| #289 | `Blocked by: #275, #280, #155.` and acceptance "clip rule that #304 shows passes" | `Blocked by: #275, #280, #155, #308.`; the bullet becomes "Exposes the analysis-constraint hook; #188 adopts the rule #304 selects." | #304 is `Blocked by: #289`, so the acceptance closes a loop the parser cannot see; #289 already cites decision #308 |
| #188 | `Blocked by: #289, #187.` | `Blocked by: #289, #187, #304.` | the constrained update is decided before the filter fixture is accepted |
| #191 | `Blocked by: #188.` | `Blocked by: #187, #306, NEW-F3.` | its own text: "Posterior initial conditions come from #306"; members come from the forecast source |
| #306 | `Blocked by: #188, #285, #9, #235.` with slice (c) inside | same line; slice (c) moves to a new issue blocked by #306, #237, #290, #198, #164, #239, #30, NEW-D3 | slice (c) names six dependencies its line omits |
| #194 | (no #306) | add #306 | it scores the cycling nowcast |
| #241 | `Blocked by: #136, #187.` | `Blocked by: NEW-F3, #187.` | the member source is a decision, not a GPU run |
| #242, #243 | `Blocked by: #136.` | `Blocked by: NEW-F3.` | same |
| #250 | `Blocked by: #198.` | split per NEW-M1: part (a) `Blocked by: #187.` | pore pressure from heads needs no dv/v operator |
| #255 | `Blocked by: #134.` | `Blocked by: NEW-W3.` | the fetcher is the dependency |
| #276 | `Blocked by: none.` while "#295 ... is the primary source" | `Blocked by: #295.` inside its footprint, or state that the published surfaces are used first and #295 refines | work precedes its primary source |
| #269 | `Blocked by: none.` | add the bedrock overlay (#21) its text calls the "Decisive check before deciding" | decision precedes its evidence |
| #284 | `Blocked by: #282, #235.` | add #130, #264 | cap and lahar layers change the layering after calibration |
| #271 | `Blocked by: #268.` | add #267, #309 | it fits to "the Richards oracle per HRU" and to a bucket not yet chosen |
| #234 | `Blocked by: none.` | add #263; wind term reads NEW-F1 | melt-out above calibration elevation; "wind/turbulent DDF term" has no source |
| 44 issues | `Blocked by: none (beyond the queue-guard PR, #231).` | unchanged; merge PR #272 to release them | list in `snapshot/critical_path.json`, key `directly_blocked_by_231` |

## B. Acceptance lines that cannot fail

| Issue | Current | Proposed |
|---|---|---|
| #288 | "A plain statement of which quantities remain prior-dominated." | gauge-only OSSE reports the K-S_y posterior correlation; a cell head is released as a product only if posterior/prior variance is below a threshold fixed in the PR before the run |
| #287 | "compare no-flow vs a joined exchange and report the difference in baseflow" | keep no-flow at a divide only if the joined run changes baseflow by less than the gauge sigma (#189); at least three divides, one in drift |
| #286 | "A negative result (MF6 not better on some metric) is reported as such" | add: the metrics and the baselines to beat are listed before the run; "validated for consumer X" requires the #142 target per unit |
| #279 | "a short memo bounding each omitted term as a fraction of mean recharge" | add a ceiling: above a stated fraction the term is implemented, not omitted |
| #281 | "Reported, not gated: head residuals at calibration wells (by HSU), number and map of dry cells" | gate the dry-cell fraction and the sign of the mean residual per unit |
| #188, #306, #286 | rank histograms and coverage "with a stated threshold" (none stated) | spread/RMSE within 0.8 to 1.2 (the value #188 carried before its rescope, and #241); 90 % coverage within +-0.05 (#194) |

## C. Scope

| Issue | Proposed change |
|---|---|
| #58 | hindcast meteorology moves to NEW-F1 (P1); #58 keeps the PET-method decision |
| #127 | add the storm-time claim / non-claim decision of NEW-P1 |
| #128 | add the `suction_stress` closure of NEW-M2 |
| #142, #261, #138 | one definition of seasonal high (NEW-U3); deliver P(depth < d*) beside the quantile |
| #193, #200, #254, #261, #65 | cite the NEW-I1 schema instead of defining formats |
| #199, #201, #202, #257 | NWM adapter and baseline (NEW-N1); the state-swap experiment (NEW-N2) is the flood value test |
| #235 | role rule extends from "each well-year" to each gauge-year; #284's test checks both |
| #252 | replace the stale input "#130's regional store" with per-member layer heads and geometry |
| #276, #10 | fill, peat, tideflat and deltaic units separated; tidal mean setup inland of the shoreline |
| #283, #301 | feed NEW-C1; #283's projection is replaced by its measurement |
| #289, #187 | `framework_realization` on the ensemble (NEW-D2) |
| #305 | effective sample size and time blocking; the November 2026 event entered from NEW-E1 |
| `ROADMAP.md:32` | "Act" row gains wildfire, pending NEW-W2 |
