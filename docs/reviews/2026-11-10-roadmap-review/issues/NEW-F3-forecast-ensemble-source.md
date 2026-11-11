# NEW-F3: Decision: forecast forcing sources by lead range (HRRR; ACE2 + Stage IV downscaler), and the baseline each is scored against

Milestone: v0.7 Probabilistic nowcast and ensemble forecast. Labels: needs-human-decision, atmospheric.
Revised 2026-11-11 after PI direction: the forecast could be HRRR, or ACE2 with the downscaling
model Brandon Kerns is prototyping on Stage IV rainfall.

## Purpose
The forecast path is one deterministic FuXi run from one GFS initial condition, precipitation and
mean temperature only (`src/data/fetch_earth2studio.py:149-164`). #241, #242, #243 wait on the GPU
run of #136. The two sources the PI named answer different questions, and the roadmap has one
undifferentiated "forecast". This issue records which source serves which lead range and product.

## Candidates and what each can serve

| Source | Native grid and step | Lead | Ensemble | Variables at the surface | Serves | Open question |
|---|---|---|---|---|---|---|
| HRRR | 3 km, hourly | to 48 h on the 00, 06, 12, 18 UTC runs | deterministic; spread only from time-lagged runs | precipitation, 10 m wind and gust, 2 m temperature and dewpoint, radiation | storm-time products: hourly forcing for NEW-P1, flood source terms for basins that respond within a day, the wind and humidity NEW-F4 needs | a time-lagged ensemble is small and not calibrated; how many lagged runs, and is the spread usable |
| ACE2 + Stage IV downscaler (Kerns prototype) | ACE2 near 1 degree, 6-hourly; downscaler target is the Stage IV grid, about 4 km | long rollouts | many members cheaply, from perturbed initial conditions or forcing | precipitation from the downscaler; ACE2 winds, temperature, humidity at its own grid | ensembles of antecedent state over weeks to seasons; scenario and compound-hazard statistics | see below |
| FuXi (current code) | 0.25 degree, 6-hourly | 15 d | one member | precipitation, temperature | kept as one deterministic medium-range member | superseded as the ensemble source |

Open questions on the ACE2 path, to settle with Brandon Kerns before it is scoped:
1. Initialised forecast or climate emulator. #71's audit text reads "ACE2 is a climate emulator
   with no deterministic skill at days 1-15". If the prototype is run as an initialised forecast,
   the stopping rule below applies; if as a scenario generator, its product is a distribution of
   antecedent states conditioned on the season or the sea-surface state, and it is scored on
   climatology of extremes, not on event timing.
2. Precipitation. `src/data/fetch_earth2studio.py:61-62` states ACE2 "emits NO precipitation";
   #71 calls that "questionable and unverified". The downscaler makes the point moot only if it
   predicts precipitation from ACE2's dynamical fields; the PR records which fields it reads.
3. Training target. Stage IV in the Pacific Northwest comes from the river forecast center's
   gauge-and-climatology analysis rather than radar alone (my recollection, to verify), so it may
   share PRISM's orographic pattern. If so, scoring the downscaler against PRISM is not independent,
   and held-out gauges plus SNOTEL accumulation are the reference.
4. Step from the Stage IV grid to 90 m: #242's mass-conserving orographic downscaler still applies,
   now from about 4 km instead of 0.25 degree; its acceptance (coarse-cell total conserved to 1e-6) is unchanged.
5. Extremes. The standing caveat for learned emulators in this project (trained largely on the mean
   seasonal cycle, weak in the tails) is tested directly: reliability of basin 24 h and 72 h totals
   above 50, 100, 150 mm.

## Decision requested
(a) HRRR as the short-range source (0 to 48 h), hourly, with a time-lagged ensemble.
(b) ACE2 + Stage IV downscaler as the ensemble source beyond HRRR's range, as an initialised
    forecast or as a scenario generator (question 1).
(c) Whether an operational medium-range ensemble is also read as the baseline both are scored against.
(d) The variable list each must deliver: precipitation, Tmax and Tmin, 10 m wind, dewpoint, freezing level.

## Acceptance (of the decision record)
- A table like the one above with every cell sourced (page or code read, date), including
  licence and access for the downscaler weights and for Stage IV.
- Member count fixed per source and justified against the smallest tail probability a consumer needs.
- Lead-range handoff: a rule for the seam between HRRR and the longer-range source (which run,
  which hour), and a lead-0 continuity requirement passed on to NEW-F4.
- Stopping rules written before any scoring. HRRR: beats persistence of MRMS at 1 to 6 h and the
  medium-range baseline at 6 to 48 h on basin totals for the #305 events. ACE2 path as a forecast:
  CRPSS for 72 h basin precipitation against the baseline >= 0 at leads 1 to 5 days. ACE2 path as a
  scenario generator: return-level curve of basin 72 h totals inside the bootstrap interval of the
  gauge record.
- #241's blocker line is rewritten to follow the decision; #136 is no longer on the path of #241, #242, #243.

## Hard blockers
Blocked by: none.

## Advisory
Earthnote (NEW-E1) already keeps every 6-hourly HRRR run for the November 2026 event, which gives
one frozen event for the HRRR stopping rule at no extra cost. NEW-F2 should name Stage IV beside
MRMS as an hourly observed source, with the independence caveat of question 3.
