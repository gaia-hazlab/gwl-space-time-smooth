# NEW-F1: Hindcast near-surface meteorology: wind, humidity, radiation on the model grid

Milestone: Water budget: land surface and root zone. Labels: P1, atmospheric. Splits the hindcast half out of #58.

## Purpose
The target names wind and temperature as forcing. Wind, humidity and radiation are ingested
nowhere (`src/data/fetch_prism_daily.py:42-56` computes Hargreaves-Samani PET from temperature);
#58 is P2, deferred and held; #234 requires "a wind/turbulent DDF term" with no wind source;
NEW-W1 needs a PET that responds to vapour-pressure deficit.

## Deliverable
`src/data/fetch_surface_met.py` and a versioned Zarr for WY2001 to present: 10 m wind speed, 2 m
dewpoint or specific humidity, vapour-pressure deficit, downward shortwave and longwave, daily on
the PRISM 12-12 UTC day and, where the source has it, hourly.

## Inputs and conventions
Two independent sources so that forcing spread exists (one reanalysis, one gridded observation
product); the PR names them and their native resolution. Units SI; wind height stated.

## Acceptance
- Station check: wind, dewpoint and shortwave against held-out stations in the domain (count
  stated), bias and RMSE by elevation band.
- Penman-Monteith minus Hargreaves-Samani PET reported by month and elevation band; no tuning.
- The 12-12 UTC aggregation conserves the hourly sum to 1e-6 (#244 convention).
- The product is not wired into the model in this issue.

## Hard blockers
Blocked by: none.

## Advisory
#58 keeps the decision of which PET drives the model; #234 takes its wind term from here.
