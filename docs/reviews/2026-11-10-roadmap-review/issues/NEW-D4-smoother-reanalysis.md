# NEW-D4: Reanalysis product from an ensemble smoother (retrospective states for hazard consumers)

Milestone: v0.7 Probabilistic nowcast and ensemble forecast. Labels: uncertainty, P1, modflow, needs-compute.

## Purpose
Seasonal-high depth to water (#261, #142) and antecedent states for event hindcasts are
retrospective quantities. Filter analyses ignore later recession data and carry the update
sawtooth; #142 currently takes the product from the calibrated open-loop ensemble (#286). No issue
owns a smoothed product.

## Deliverable
A fixed-lag ensemble Kalman smoother over the pilot and the WY2001 to present reanalysis written in
the NEW-I1 schema with `product = reanalysis`.

## Acceptance
- Linear fixture: matches the exact Rauch-Tung-Striebel mean and covariance within Monte Carlo error.
- Held-out wells: seasonal-high error of the smoother versus the filter versus the open loop,
  with block-bootstrap intervals; the lag is chosen on the fixture and frozen before scoring.
- Ledger: smoother increments are booked per store (#232).
- A guard refuses a reanalysis product as input to any issue-time-frozen evaluation (#305).

## Hard blockers
Blocked by: #306.
