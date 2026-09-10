# GAIA Digital Twin of Soil — workspace instructions

## Scope and current evidence

The research target is a coupled soil reanalysis for PNW flood, landslide and
liquefaction applications: groundwater storage, water-table state, soil moisture
and near-surface stiffness, with uncertainty. The common state/reference grid is
approximately 90 m; observations and hazards retain their own spatial and temporal
supports. Resampling alone creates no new information or hazard-scale validation.

The current western Cascades grid is defined in `src/config/domain.py` (EPSG:5070).
Import that definition and check alignment; never silently mix legacy grids.
The monthly groundwater/soil-moisture pipeline remains a scoped baseline. Its
current regression model is a random forest with kriged residuals. Existing
monthly and legacy modules, and explicitly scoped LightGBM comparisons, may be
maintained; they do not define the whole twin or establish daily forecast skill.

Daily coupled physics and assimilation code exist, but conservation, state
closure, independent validation and hazard adapters have unresolved audit findings.
Treat probabilistic cycling, forecasts and hazard outputs according to demonstrated
capability; a demo, calibration fit or passing CI is not an operational product.

## Working order and review

Start with the [operational plan](../docs/soil-twin-operational-plan.md),
[ROADMAP](../ROADMAP.md), scoped issue criteria and current human decisions.
Use the immutable [system audit](../docs/reviews/soil-twin-system-audit-2026-09-10.md)
and [follow-up](../docs/reviews/soil-twin-audit-followup-2026-09-10.md) as evidence
snapshots, not proof that later fixes or deployed runners were verified.

- Proceed with bounded local science and engineering work through manual review.
  The existing queue is uncommissioned and contains automatic PR readiness/merge
  paths. Do not launch it on the assumption that watching it enforces draft-only
  behavior. Follow the operational plan's commissioning and deployment gates.
- Respect `needs-human-decision`, explicit issue holds and the Vs30 densification
  pause. A valid reviewer response does not release a hold; record the authorized
  human decision and remaining prerequisites before resuming held work.
- All mandatory reviewers must explicitly approve the same scoped plan/change.
  Missing, invalid, failed, `revise` or `block` responses prevent advancement.
  Resolve substantive concerns, iterate and obtain the required re-review.
- Bind acceptance evidence and approvals to the reviewed commit SHA. Recheck after
  changes; never relax tests or gates to make a change appear approved.
- Track per-issue acceptance criteria. Completing a subtask or partial batch does
  not close its parent issue or other unstarted work. Report residual scope.

## Scientific checks for each relevant change

- Use `src/models/hydro_state.py` for the distinctions between storage, water-table
  elevation, positive-downward DTW, screened aquifer head and pore pressure. Record
  datum, sign, units and the chosen storage-to-head/pressure closure explicitly.
- Preserve native observation footprints and depth sensitivity. NWIS QC classifies
  water-table, aquifer-head and unknown observations; do not promote unknown wells
  or apply the shallow water-table operator to confined heads. Monthly QC leaves
  gaps unfilled; changing sampling requires explicit provenance and validation.
- State each interface's units and timestep, including water-depth totals versus
  rates and conductivity conversions. Hydrologic APIs use units such as mm/day;
  do not impose a blanket seconds-only convention or infer units from names.
- Test conservation across coupled stores, signed boundary fluxes and multistep
  limits. Distinguish accounting closure from fit to gauges and wells. Calibrated
  parameters and shared-forcing comparisons require independent held-out evidence.
- Use spatial/temporal/domain holdouts suited to the claim; keep tuning and
  assimilation observations separate from evaluation. Check uncertainty coverage,
  approximation assumptions and identifiability as well as prediction errors.
- Verify hazard adapters against the consuming component's actual versioned API,
  support, units and physical assumptions. Cite code and reproducible evidence for
  implementation claims; test passes alone do not establish scientific validity.

## Environment, code and records

- `pixi.toml` is the dependency/task source; `environment.yml` is historical.
  Use `pixi install`, `pixi run python …`, and `pixi run test` as appropriate.
  The test task covers `tests/` and `scripts/gaia-launch/tests/`; report skips and
  whether checks used a clean installation or the existing environment.
- Inspect the task and input paths before running a pipeline: some tasks require
  downloads, credentials, staged data or a GPU. `richdem` stays in conda dependencies.
- Use `pathlib.Path`, module logging, public-function type hints and NumPy-style
  docstrings. Keep timestamps explicit and consistent with UTC metadata.
- Keep downloaded/generated data out of Git; record dataset sources, versions,
  transformations and uncertainty in manifests and product provenance. Update
  `data/raw/MANIFEST.md` when adding data and preserve GAIA provenance contracts.
- Update assumptions and limitations when behavior or evidence changes. For
  literature edits, verify full bibliographic metadata and claim support; DOI
  resolution alone is insufficient. Record unavailable checks as unchecked.
  The bibliography audit and existing issue #25 govern remaining corrections;
  the current metadata checker can pass after skipping all lookups.
