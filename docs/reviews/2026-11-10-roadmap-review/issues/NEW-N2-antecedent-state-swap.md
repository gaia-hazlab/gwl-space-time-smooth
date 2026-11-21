# NEW-N2: Flood: does the twin's antecedent soil state add skill over the National Water Model?

Milestone: Hazard: flood / inundation handoff. Labels: P1, validation, needs-compute.

## Purpose
The one experiment that tests the twin's added value for floods.

## Deliverable
Two arms with identical forcing and identical routing. Arm A: the reference initial soil and snow
state. Arm B: soil water and SWE replaced at initialisation by the twin's posterior members,
mapped with a volume-conserving operator. Either inside a WRF-Hydro/NWM configuration or, if that
is not runnable here, inside the twin's own source-term and routing chain with NWM-like and
twin-like initial states; the memo says which and why.

## Acceptance
- >= 10 events from the #305 manifest, issue times frozen.
- Scores at gauges excluded from nudging and from #284 calibration: event volume, peak, peak timing.
- Skill is claimed only if the block-bootstrap interval (over events) of the KGE difference excludes 0;
  otherwise the memo records "no added value shown" and the flood claim in `ROADMAP.md` is reworded.
- The volume moved by the state swap is booked in the ledger (#232).

## Hard blockers
Blocked by: NEW-N1, #306, #305, #257.
