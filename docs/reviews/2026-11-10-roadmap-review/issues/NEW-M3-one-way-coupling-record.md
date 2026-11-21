# NEW-M3: Design record: one-way hydromechanical coupling and its validity bound

Milestone: Groundwater model: MODFLOW 6 hydrogeologic core. Labels: needs-human-decision, geotech, modflow.

## Purpose
In every open issue hydrology drives stress and nothing returns (no compaction package, no
stress-dependent K or storage; only event multipliers in #122 and #190). That is a reasonable
choice for stiff glacial sediments and an unexamined one for peat, tideflat and fill, which are the
liquefiable units. The roadmap should say so and say where it stops holding.

## Deliverable
A short record in `docs/assumptions.md` and a mask on the grid.

## Acceptance
- Skeletal volumetric strain eps_v = S_ske x seasonal head range computed per hydrostratigraphic
  unit from cited S_ske ranges and the observed amplitude at #235 recorders; the induced change in
  ln K from a cited porosity-permeability relation is tabulated beside the calibrated sigma of ln K (#285).
- Units where the induced change exceeds one tenth of that sigma are mapped and flagged
  `one_way_coupling_questionable`; the count of cells is reported.
- Ground-failure footprints: after an earthquake the state inside mapped failure areas is flagged
  invalid until re-assimilated (links #145).
- #291's scoping arithmetic is extended to report eps_v, so one calculation serves both.

## Hard blockers
Blocked by: #276.
