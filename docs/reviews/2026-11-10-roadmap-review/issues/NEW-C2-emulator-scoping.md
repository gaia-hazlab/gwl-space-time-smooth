# NEW-C2: Scoping decision: is a learned emulator of the soil-state model needed, and of which part

Milestone: Software: CI, tests, reproducibility, scale. Labels: P2, needs-human-decision.

## Purpose
The target includes ensemble forecasts driven by AI weather surrogates. If NEW-C1 shows that the
physics ensemble cannot meet the forecast latency at a useful N, the only options are a coarser
physics model or an emulator. No open issue owns that choice. The only "surrogate" in the roadmap
is the liquefaction model (#260, #270).

## Deliverable
A decision memo (`docs/reviews/<date>-emulator-scoping.md`), no model code: what would be emulated
(MF6 head response to recharge per watershed; the land-surface step; the forward operators), what
the training set would be (the PEST++ IES and reanalysis members already paid for), and the
stopping rule that keeps an emulator out of the analysis step unless it passes.

## Acceptance
- States the NEW-C1 numbers that trigger or dismiss the need.
- For each candidate target: input and output tensors, the conservation property that must hold
  exactly (water ledger of #232) and how it is enforced or checked, and the extrapolation test
  (members withheld by forcing percentile, not at random, per the mean-seasonal-cycle caveat
  already recorded for ParFlow-ML emulators).
- Recommends one of: no emulator; emulator for forecast members only with physics for the analysis;
  emulator inside the filter. The PI decides.

## Hard blockers
Blocked by: NEW-C1.

## Advisory
Hybrid use (physics for the analysis and a small member set, emulator to enlarge the forecast
ensemble) keeps the assimilation mass-conserving.
