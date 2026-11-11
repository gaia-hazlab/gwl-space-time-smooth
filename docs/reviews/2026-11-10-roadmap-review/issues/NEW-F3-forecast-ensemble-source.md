# NEW-F3: Decision: member source for the forecast ensemble, and the physics baseline

Milestone: v0.7 Probabilistic nowcast and ensemble forecast. Labels: needs-human-decision, atmospheric.

## Purpose
The forecast path is one deterministic FuXi run from one GFS initial condition, precipitation and
mean temperature only (`src/data/fetch_earth2studio.py:149-164`). #241, #242, #243 wait on the
GPU run of #136. No issue scores AI members against a physics ensemble. Operational AI and physics
ensembles with 50 or more members exist and need no GPU here (reviewer note; to be verified at decision).

## Decision requested
Which of: (a) FuXi with constructed members as in #241; (b) an operational AI ensemble as the
member source; (c) an operational physics ensemble as the member source with an AI ensemble
compared against it. And the variable list: precipitation, Tmax and Tmin, 10 m wind, dewpoint,
freezing level.

## Acceptance (of the decision record)
- Member count is fixed and justified against the smallest tail probability a consumer needs.
- For each candidate: variables available at the surface, lead range, step, native resolution,
  access and licence, each with the page read and the date.
- A stopping rule is written: the AI source is kept only if its CRPSS for 72 h basin precipitation
  against the physics ensemble is >= 0 at leads 1 to 5 days on the #305 events.
- #241's blocker line is rewritten to follow the decision.

## Hard blockers
Blocked by: none.
