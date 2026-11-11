# NEW-D5: SNOTEL snow-water-equivalent observation operator and error model

Milestone: Applied math: DA estimator correctness. Labels: stage-3, P1.

## Purpose
SWE is in the state vector (plan.md section 3.7). The sensor table points to "existing
calibration, #234", and #234 validates against SNOTEL without defining an operator or R.
SWE has a point mass at zero, which a Gaussian update mishandles.

## Deliverable
Point operator with elevation and canopy representativeness, R, and a stated treatment of the zero
bound (transform or constrained update consistent with #304).

## Acceptance
- Synthetic: an observation of zero SWE never produces negative analysis SWE and the removed water
  is booked; an observation of snow where all members have none produces a stated, bounded response.
- Leave-stations-out: melt-out date error with and without assimilation at withheld stations.
- Stations used in #234 calibration are excluded by manifest role.

## Hard blockers
Blocked by: #234, #188.
