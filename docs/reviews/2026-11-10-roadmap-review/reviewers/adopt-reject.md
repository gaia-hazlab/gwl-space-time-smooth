# Reviewer probes: what I checked and what I adopted

Method: every issue quote a reviewer used was searched in `snapshot/open_issues.json`, split at the
first `<details` so that current scope and archived scope are distinguished; every `file:line` was
reopened on branch `review/roadmap-2026-11-10` (`src/` identical to `main` at `435445f`). Online
statements by the atmospheric reviewer were not re-fetched by me and are carried as "agent, online".

| Reviewer | Probe | My check | Outcome |
|---|---|---|---|
| geotech | #128 acceptance tests `{'hydrostatic','slope_parallel'}` only; "with suction" is in the plain-words line | both strings in current scope | adopted |
| geotech | `hydro_state.py:221-223` returns suction as zero | reopened: "Suction above the water table is returned as zero" | adopted |
| geotech | `landlab_export.py:217-218` seasonal-high field has no sigma | reopened lines 214-219 | adopted |
| geotech | #250 blocked by #198, P2 | "Blocked by: #198."; label P2 | adopted; the unblock is a PI decision |
| geotech | two definitions of seasonal high (#261 P10, #138 GEV) | both in current scope | adopted |
| geotech | #252 points at "#130's regional store" | in current scope | adopted |
| geotech | one-way coupling bound eps_v <= 1e-2, Kozeny-Carman arithmetic | not checked; agent estimate | carried as an estimate; the issue asks for the number to be computed |
| geotech | design-storm I15 values 12, 24, 40 mm/h | recalled by the agent, in no issue | not adopted as numbers; the draft asks for the published thresholds to be cited |
| geostat | `uncertainty_stack.py:191,195-199` quadrature sum with a 5.0 m constant | reopened | adopted |
| geostat | #188 dropped "spread/RMSE ratio within 0.8-1.2" at the rescope | string present only in archived scope | adopted |
| geostat | #305 already has spatial-block bootstrap | in current scope | adopted; my lead L7 was overstated |
| geostat | #142 target is 1.5-2 m for the screen, 1 m of DTW about 0.008 in P | both in current scope | adopted; my lead L8 was overstated |
| geostat | #289 signature has no geometry argument; #292 reaches PEST++ only | both quotes in current scope | adopted |
| DA | #289 acceptance cites #304 while #304 is blocked by #289 | both in current scope | adopted |
| DA | #289 cites decision #308, absent from its blocker line | confirmed | adopted |
| DA | #191 blocked by #188 only, yet initialised from #306 | confirmed | adopted |
| DA | gauge in #284 (baseflow) and #306 (c) (total outflow); role rule is per well-year | confirmed in #284, #306, #235, #237 | adopted |
| DA | #192 barrier test "< 5% of the in-basin increment" | in current scope | adopted |
| DA | plan.md:187 "LETKF or EnSRF", :203 vertical coupling | reopened | adopted |
| hydro | #58 "currently not ingested" | string is in archived scope only | adjusted: the code check carries the claim, not #58 |
| hydro | zero hits for frozen ground, frost, soil temperature | recounted over all 194 bodies: 0, 0, 0 | adopted |
| hydro | six acceptance lines that cannot fail (#236, #288, #287, #286, #279, #281) | all six quotes in current scope | five adopted; #236's identity test is a legitimate code test and is not listed as a defect |
| hydro | mis-ordering: #276, #269, #284, #271, #234 blocker lines | all five blocker lines confirmed | adopted |
| atmos | `fetch_earth2studio.py:149,156-157,164`; `forecast.py:58-60` | reopened | adopted |
| atmos | #241 blocked by #136 and #187; #242, #243 by #136 | confirmed | adopted |
| atmos | #224 "MRMS 1 h QPE at 1 km" | not found in current scope; current text has "PRISM vs MRMS by elevation band" | quote dropped, substance (MRMS only as comparison) kept |
| atmos | AIFS ENS operational, 51 members; earth2studio model list; NWM page | agent, online; not re-fetched | carried with that label; each becomes a "verify at implementation" line in the drafts |
| atmos | NWM has four soil layers, a conceptual groundwater bucket, no soil-moisture assimilation | recalled by the agent | not asserted; NEW-N1 makes documenting it the first acceptance line |
| all | "Blocked by: none (beyond the queue-guard PR, #231)" | 44 issues carry #231 as their only parsed blocker (`snapshot/critical_path.json`) | adopted as the first sequencing finding |

Leads of mine that the reviewers corrected: the filter type is named in the design record
(LETKF or EnSRF) though not in #188; boundary conductances are in the PEST++ ensemble; #305 has a
block bootstrap; the liquefaction screen needs 1.5 to 2 m, not sub-metre; #58 is not the only
owner of forecast PET (#243).
