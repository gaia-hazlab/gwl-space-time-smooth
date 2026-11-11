# Reviewer round: twin-hydrogeologist (2026-11-11)

Read-only agent report, transcribed. "#N" = issue body in the 2026-11-09 snapshot; plan.md =
`docs/reviews/2026-10-18-modflow-groundwater-core/plan.md`. Nothing rerun. My check of each probe is
in `adopt-reject.md`.

## Verdict

The groundwater half of the roadmap is sound below the root base. Storm-time landslide physics has
no owner. At least six acceptance criteria in the two groundwater milestones cannot fail.

## Leads

| Lead | Verdict | Evidence |
|---|---|---|
| L1 no u(z,t), no suction | partly | #294: "MODFLOW UZF carries water content without matric potential."; plan.md:176-177 builds u(z) from layer heads only; #302 derives psi in a column test, not in the state; positive pressure has coarse owners (#130 at k x 90 m, #174 at 90 m); suction and sub-daily psi(z,t) have none; stress periods are daily (plan.md:162) |
| L2 no transient hillslope model at <= 10 m | partly | #133: "a steady-state or kinematic lateral delivery on the 90 m D8 graph, plus a 10 m TOPMODEL wetness downscaler"; the 10 m step is steady and one-way; #135 held |
| L3 no thermal state, no wind | confirmed | zero hits for "frozen ground", "frost", "soil temperature" in all bodies; #234 requires "a wind/turbulent DDF term" with no wind source |
| L4 preferential and lateral unsaturated flow | confirmed (macropore), partly (lateral) | only mention is superseded #131: "Macropore preferential flow can be much faster."; #174's lateral flux is saturated transmissivity |
| L5 mountain basins | confirmed; cannot fail | #288: "A plain statement of which quantities remain prior-dominated." No threshold; its OSSE is model-to-model |
| L6 regolith thickness | confirmed | #276 "say which"; #83 "GAIA dtb ... is of unknown provenance"; #134 SOLUS "capped at 2 m"; #276 checks units only at wells, so the uplands are never checked |
| L7 pumping, lakes | confirmed | #279: "a short memo bounding each omitted term as a fraction of mean recharge", no ceiling; #293 blocked by #287 |

## Physics with no owning issue, ranked

| # | Missing physics | Hazard | Decisive test |
|---|---|---|---|
| 1 | Transient psi(z,t) over 0-3 m at hourly steps; the land-surface model is a bucket "with no profile" (plan.md:86) | landslide | hourly Richards (#267) against daily land surface + UZF under #302 forcing: peak pressure head at 1 m |
| 2 | Perched water straddling the MODFLOW top: #130 puts it in MODFLOW, #174 in the land surface; split wherever colluvium is deeper than the root depth | landslide | column with 2 m colluvium over till, root depth 1 m: pressure continuity and the ledger at the MODFLOW top |
| 3 | Artificial fill and Holocene deltaic units on tidal margins; #10 drops inland tidal setup | liquefaction | near-shore fill wells: (head - mean sea level) against distance from shore, versus a GHB-only model |
| 4 | Turbulent and advective heat for rain on snow; no wind or humidity source | flood | December 2025 rain-on-snow hindcast with and without reanalysis wind: melt difference at SNOTEL |
| 5 | Preferential flow | landslide, recharge timing | storm lags at #235 recorders shorter than UZF celerity allows (#131: 15-40 d through 4 m) |
| 6 | Frozen soil | flood (low in the lowland) | count of frozen-soil days coinciding with large rain |

## Wildfire: what the model can supply

| Quantity | Support | Defensible? |
|---|---|---|
| Root-zone deficit | 0 to root depth (2 m SOLUS cap), daily, 90 m | yes, as anomaly or percentile; summer drawdown limited by Hargreaves PET with no vapour-pressure deficit |
| Plant-available-water fraction | same | yes, as a relative index; misses water in weathered bedrock |
| Surface water content 0-5 cm | not in the state | no |
| Duff and litter (dead fuel) moisture | O horizon, hourly | no: driven by humidity, wind, radiation, none ingested |
| Live fuel moisture | none | no; covariate only |

## Acceptance criteria that cannot fail (agent list)

1. #236 "model and observation BFI agree exactly when the series are identical".
2. #288 "A plain statement of which quantities remain prior-dominated."
3. #287 "compare no-flow vs a joined exchange and report the difference in baseflow": no rejection rule.
4. #286 "A negative result (MF6 not better on some metric) is reported as such".
5. #279 "If omitted: the bound with its arithmetic": no size limit.
6. #281 "Reported, not gated: head residuals at calibration wells (by HSU), number and map of dry cells".

## Mis-ordered work

- #276 has no blocker but names #295 "the primary source"; #295 waits on #275.
- #269 has no blocker yet needs #295's overlap table and the bedrock overlay its own text calls decisive.
- #284 is blocked by #282 and #235 only; #130 and #264 change the layering after calibration.
- #271 fits to "the Richards oracle per HRU" but is blocked only by #268, not #267 or #309.
- #234 is blocked by nothing yet needs #263 and a wind source.

## Proposals

| Title | Acceptance | Blockers |
|---|---|---|
| New: event-mode pressure-head column, hourly psi(z) over 0-3 m at hollow columns | peak pressure head at 1 m within 0.1 m of Richards (#302's tolerance), or storm-time FS labelled "unsupported" | #267 or hydrostate#1, #132, #302 |
| New: upland regolith thickness with provenance | fewer than 10 % (proposed) of upland #277 logs with bedrock deeper than 2 m have product thickness <= 2 m | #277, #21 |
| Amend #287: divide rule | keep no-flow only if the joined run changes baseflow by less than the gauge sigma (#189); >= 3 divides, one in drift | #283, #189 |
| Amend #288: negative control and release rule | gauge-only OSSE keeps K-S_y posterior correlation \|r\| >= 0.9; a cell head is released only if posterior/prior variance < 0.5 (proposed) | #287, #198, #226 |
| Amend #276, #10: fill and deltaic units, tidal mean setup | fails if median seasonal-high depth error at near-shore fill wells exceeds 1.5 m (#142) | #277, #9 |
| New: wildfire soil-water contract | if August-September plant-available water under Hargreaves and under Penman-Monteith differs by more than the #290 probe sigma, the product is labelled forcing-limited | #52, #309, #290, #58 |

Decision raised: is storm-time landslide triggering a claim or a non-claim.
