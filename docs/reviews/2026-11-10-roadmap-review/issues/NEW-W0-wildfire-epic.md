# NEW-W0: [epic] Hazard: wildfire handoff, from soil-water state to fuel dryness, and burn severity back

Proposed new milestone "Hazard: wildfire handoff". Labels: epic.

## Purpose
The PI named wildfire susceptibility a fourth consumer on 2026-11-10. The open roadmap has none:
zero issues mention fuel moisture, vapour-pressure deficit or a fire-danger index, and `ROADMAP.md:32`
lists three hazards. Fire appears only as a disturbance that changes soil hydraulics (#122, #134, #255).

## Scope and non-claims
- The twin exports what it owns: root-zone water deficit and percentile, cumulative actual minus
  potential evapotranspiration, snow melt-out date, at 90 m daily, as members (NEW-W1).
- The twin does not model dead-fuel (litter and duff) moisture, live fuel moisture or fire spread.
  Those are driven by humidity, wind and radiation and belong to a fire-danger consumer that reads
  the same forcing (NEW-F1) and the twin's export.
- Whether soil water adds skill on the wet west side is an open question with a test (NEW-W2). The
  2020 Labor Day fires were wind-driven under extreme fuel aridity; if the test fails, the handoff
  is recorded as "not a claim" and the milestone closes with that result.
- The return path (burn severity changing infiltration and root cohesion) is NEW-W3, feeding #122, #134, #255.

## Children
NEW-W1 export contract; NEW-W2 value gate; NEW-W3 burn-perimeter and severity ingest.
Depends on NEW-F1 (wind, humidity, radiation in the hindcast) and NEW-I1 (schema).

## Hard blockers
Blocked by: none.
