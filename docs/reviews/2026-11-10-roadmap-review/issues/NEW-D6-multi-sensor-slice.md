# NEW-D6: Cycling ensemble nowcast, multi-sensor slice (split from #306 c)

Milestone: Applied math: DA estimator correctness. Labels: stage-3, uncertainty, P1, modflow.

## Purpose
#306 holds two slices on one blocker line (`Blocked by: #188, #285, #9, #235.`). Slice (c), the
multi-sensor nowcast, also needs the gauge operator, the soil-moisture operators, the
hydromechanical operator, the dv/v error model and real dv/v data, none of which that line lists.
Split out so the wells-only pilot (#306 b) is not read as ready for them, and the reverse.

## Deliverable
The #306 (c) scope unchanged: gauges as total SFR outflow (#237), soil moisture (#290), dv/v from
non-overlapping stacks through the forward operator (#198) with its bias state, each stream
admitted under NEW-D3.

## Acceptance
- Per-sensor degrees of freedom for signal and held-out scores, with and without each stream;
  "no value added" is recorded when found.
- No stream enters without a passed admission record (NEW-D3).
- Gauge-years assimilated here are disjoint from those used in #284 (manifest check, #235).
- Rank histogram and 90 % coverage at withheld sensors within the thresholds restored on #306.

## Hard blockers
Blocked by: #306, #237, #290, #198, #164, #239, #30, NEW-D3.
