# NEW-W1: Wildfire: soil-water export contract (root-zone deficit, percentile, melt-out date)

Milestone: Hazard: wildfire handoff. Labels: P1, water-budget.

## Purpose
Give a fire-danger consumer the soil-water quantities the twin can defend, with their limits written in.

## Deliverable
`src/io/wildfire_export.py`: a view of the NEW-I1 schema with `root_zone_water_deficit` (mm),
`plant_available_water_fraction` (1), `root_zone_percentile` (1, against the member's own
hindcast climatology for the day of year), `cumulative_aet_minus_pet` (mm since 1 April),
`swe_melt_out_date`, each on `(member, valid_time, y, x)`.

## Inputs and conventions
Root-zone store from the single owner decided in #309; depth support is 0 to root depth and is
written in the metadata (SOLUS caps at 2 m; water held in weathered bedrock is not seen).

## Acceptance
- Deficit plus storage equals capacity per cell and member to float64 rounding.
- Percentile is computed from a climatology that excludes the evaluated year (leave-one-year-out);
  a test fails if the evaluated year is in the reference set.
- Forcing-limited flag: August to September plant-available water under Hargreaves-Samani and under
  Penman-Monteith (NEW-F1) is compared at the #290 probe sites; where the difference exceeds the
  probe sigma of the #189 table the product carries `pet_limited = true`.
- Metadata states the non-claims of NEW-W0 verbatim.

## Hard blockers
Blocked by: #52, #309, NEW-I1.

## Advisory
NEW-F1 is needed for the flag, not for the export.
