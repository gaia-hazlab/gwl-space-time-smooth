# NEW-W3: Burn perimeter and severity fetcher (MTBS, and rapid products for recent fires)

Milestone: Hazard: wildfire handoff. Labels: P1, landlab.

## Purpose
#134 states "No MTBS/burn-perimeter fetcher exists in src"; #255 ingests MTBS and dNBR inside an
issue blocked by #134; #124 lists perimeters in a catalog. Three issues need one fetcher.

## Deliverable
`src/data/fetch_burn_severity.py`: perimeters, ignition and containment dates, and severity class
or dNBR on the 90 m grid, with source and product version per fire.

## Acceptance
- Returns every fire above a stated size inside `DOMAIN` since 2000 with counts in the PR.
- Burned-area fraction per HUC12 reproduces the source's reported area within 2 % for five fires.
- Fixture-backed test (one small fire) runs offline.
- #134 (B), #255 and #124 cite this fetcher; #255's blocker becomes this issue instead of #134.

## Hard blockers
Blocked by: none.
