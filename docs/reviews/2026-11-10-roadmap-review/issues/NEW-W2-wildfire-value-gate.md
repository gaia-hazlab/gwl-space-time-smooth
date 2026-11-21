# NEW-W2: Wildfire: does the soil-water state add skill over atmospheric fire-danger indices?

Milestone: Hazard: wildfire handoff. Labels: P1, validation.

## Purpose
A gate, in the manner of #270 for liquefaction: decide by test whether the handoff is a claim.

## Deliverable
A scored comparison and a memo. Baseline: a model of fire occurrence or large-fire days from
gridded energy release component and 100-hour and 1000-hour dead fuel moisture alone. Candidate:
the baseline plus the NEW-W1 percentile and deficit.

## Inputs and conventions
Fire record: MTBS perimeters and ignition dates in the western-Cascades domain; station fuel
moisture where available. Sources and licences are listed before any fit. Years are split before
any fit and entered in the #235 manifest. East-side (Stehekin, v0.5) is scored separately.

## Acceptance
- AUC difference (candidate minus baseline) on held-out years with a block-bootstrap interval over
  years; "adds value" only if the interval excludes zero.
- The number of fire events in the test set is stated; if fewer than 30 the result is reported as
  underpowered and the claim stays open.
- A negative result closes the milestone as "not a soil-twin claim" and edits `ROADMAP.md` accordingly.

## Hard blockers
Blocked by: NEW-W1, NEW-F1, #70.
