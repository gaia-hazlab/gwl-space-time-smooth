# NEW-F2: Hourly observed precipitation record and its relation to the daily forcing

Milestone: Water budget: land surface and root zone. Labels: P1, atmospheric, landlab.

## Purpose
The model step is daily. Storm-time landsliding, post-fire runoff and floods in basins with a time
of concentration under a day need sub-daily input (#132, #199). MRMS appears in the roadmap only
as an event comparison (#132, #224).

## Deliverable
`src/data/fetch_hourly_precip.py`: hourly radar-gauge precipitation on the domain for a stated
period, plus an aggregation to the PRISM day.

## Acceptance
- Aggregation to the 12-12 UTC day conserves the hourly sum to 1e-6.
- Daily difference from PRISM reported by elevation band and season as an inter-product
  difference, not validation; radar beam-blockage area in the Cascades mapped and masked.
- Maximum 1 h and 6 h intensities per event of the #305 manifest are tabulated.

## Hard blockers
Blocked by: none.

## Advisory
Earthnote (NEW-E1) indexes the November 2026 hours; the quantitative fields come from the source.
