# NEW-F4: Forecast forcing beyond precipitation: Tmax/Tmin, wind, humidity, freezing level, to 90 m

Milestone: v0.7 Probabilistic nowcast and ensemble forecast. Labels: P1, atmospheric.

## Purpose
`fetch_earth2studio.py:156-164` resamples 6-hourly output to daily and keeps precipitation and mean
temperature. #263 lapse-rate downscales PRISM only. Forecast wind and humidity have no owner.

## Deliverable
Forecast adapter output on `(member, issue_time, lead_time, y, x)` with the NEW-F3 variable list,
6-hourly kept, temperature lapse-corrected from the forecast model's own orography to the 90 m DEM.

## Acceptance
- A uniform-elevation case is unchanged by the lapse step (the #263 test, applied to forecast orography).
- Lead-0 continuity: on a replayed analysis, the jump in PET and in SWE between hindcast and
  forecast forcing is below the hindcast station bias of NEW-F1, per elevation band.
- The rain/snow partition uses forecast freezing level where available; the difference from the
  0 to 4 degC ramp (`src/models/forecast.py:58-60`) is reported on the #305 events.

## Hard blockers
Blocked by: NEW-F3, #263, #244.
