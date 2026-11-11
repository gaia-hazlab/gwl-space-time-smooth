# NEW-D1: Production estimator specification and a scale test that the fixture cannot pass by accident

Milestone: Applied math: DA estimator correctness. Labels: stage-3, P1, modflow.

## Purpose
#188 checks "the EnKF at N = 500" on one confined layer, where no localization is needed. The pilot
will run near N = 50 (#283's projection) against more than 1e6 unknowns. Ensemble size,
localization radius, the vertical rule, the cross-variable rule (root-zone storage, vadose water
content, heads, reach flow) and the rule for an integral observation (a gauge has no distance) are
unset. The design record names "LETKF or EnSRF" (plan.md:187); #188 names neither.

## Deliverable
`docs/da-estimator-spec.md` and a test fixture: filter variant; N; taper function and radius per
variable pair; vertical rule; integral-observation rule; inflation method and bounds; time
convention for sub-daily observations assimilated at stress-period boundaries.

## Acceptance
- Multi-layer confined linear fixture, 30 wells, Matern prior with the range of #299, exact Kalman
  filter as reference: the localized filter at N = 20, 50, 100 gives analysis variance at held-out
  cells within 10 % of exact and a mean within Monte Carlo error; the gauge rule is exercised.
- Sub-daily observation times: the increment under the chosen time convention is compared with the
  exact filter at true times and the error is stated.
- #192's barrier-leak test (increment beyond a barrier "< 5% of the in-basin increment") is
  reconciled with #188's "no hard zeros": one of them is rewritten and the PR says which.

## Hard blockers
Blocked by: #188, #283.
