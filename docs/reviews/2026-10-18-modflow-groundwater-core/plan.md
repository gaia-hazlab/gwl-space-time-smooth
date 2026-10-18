# Plan: MODFLOW 6 as the groundwater core of the twin

**Date:** 2026-10-18. **Branch:** `plan/modflow-groundwater-core`, stacked on PR #272
(`gaia/queue-holds-and-blockers`, head `618fea9`). **Base of record:** `main` at `435445f`.
**Status:** proposed, for PI approval. Approval of this plan is the approval of the design
record in issue #265. **Revision 1** (same day) folds in review round 1
(`plan-review-round1.md`: hydrogeologist and DA methodologist, both approve-with-edits).

## 1. Decision this plan records

On 2026-10-18 the PI asked to replace the water-balance closure model with MODFLOW groundwater
modelling, with watershed-specific models, a water table and soil moisture in the state, and
data assimilation of the full sensor set (raw measurements, geophysical proxies, satellites).

This **supersedes two earlier positions**:

| Earlier position | Where recorded | What changes |
|---|---|---|
| "Keep the twin's light store model as the cycling/DA model; make it modular so DHSVM/ParFlow can run in particular watersheds as benchmarks" | PI decision 2026-10-08, body of #265 | MODFLOW 6 becomes the groundwater model below the root zone. The store model survives only as the land-surface/root-zone component and as a skill baseline. |
| "A conservative storage model is appropriate. Full flow PDEs ... are not prerequisites for the first implementation." | Scope paragraph of `docs/reviews/2026-10-09-codex-pr229-review.md` | A groundwater-flow PDE solver is now the first implementation. |

What is **kept** from the Codex PR 229 rulebook, unchanged: one deliverable per issue; the
Purpose / Deliverable / Inputs and conventions / Acceptance / Hard blockers / Advisory sections;
only indispensable hard blockers; conservation tolerances derived from the numerics, not fixed;
forecast conservation kept separate from DA increments; the OSSE criteria (independent nature
run, no requirement of a nonzero innovation mean); the corrected redundant-observation test.

## 2. Why the store model cannot be the groundwater core

Measured on the current code and data, not argued:

1. **No lateral groundwater.** Every 90 m cell drains to its own HAND datum
   (`src/models/water_budget.py`), rivers can never lose water to the aquifer, and there is no
   seepage face or pumping sink (#266). A groundwater divide that departs from the surface
   divide, a losing reach, or a spring line cannot be represented.
2. **The calibrated closure is a fit, not a mechanism.** The v0.4 numbers in `ROADMAP.md`
   (BFI 0.52 vs 0.47, amplitude 1.02 vs 1.06 m) come from three parameters each pinned by one
   observation (`notebooks/calibrate_fluxes.py`). The 2026-10-08 audit found capillary rise
   creating water and valley cells with no sink (#232, #233).
3. **The gauged basins have no wells.** Counting NWIS wells from
   `data/processed/nwis_gwlevels_domain_monthly.parquet` (1,524 sites, 2000–2026, site-month
   medians) inside the NLDI basins of the eight calibration gauges (fetched 2026-10-18 with
   `src/data/fetch_gauge_basins.fetch_basins`, rerun in this session):

| Gauge | Basin | Area (km²) | NWIS wells | Wells with ≥12 months |
|---|---|---|---|---|
| 12082500 | Nisqually R nr National | 361 | 0 | 0 |
| 12092000 | Puyallup R nr Electron | 238 | 0 | 0 |
| 12097500 | Greenwater R at Greenwater | 190 | 0 | 0 |
| 12115000 | Cedar R nr Cedar Falls | 110 | 0 | 0 |
| 12134500 | Skykomish R nr Gold Bar | 1,386 | 0 | 0 |
| 12144500 | Snoqualmie R nr Carnation | 977 | 0 | 0 |
| 12108500 | Newaukum Cr nr Black Diamond | 79 | 21 | 11 |
| 12102078 | Clarks Cr at Stewart Ave | 70 | 16 | 6 |

The "well amplitude 1.02 vs 1.06 m" in the D7 calibration therefore compares a domain-wide
model to lowland wells that sit outside six of the eight basins whose fluxes set the other two
parameters. A MODFLOW pilot must be lowland, and in the mountains heads are unobserved. There,
baseflow recession constrains basin drainable storage and diffusivity (K·b/S_y), not K and S_y
separately; dv/v sees head change only through the hydromechanical operator; GNSS loading from a
single basin is probably below daily GNSS noise (a reviewer estimate, to be tested in #226). The
mountain product is therefore basin storage with an uncertainty, and cell heads stay labelled
unconstrained unless MF-14 shows otherwise.

(Side finding: `src/data/fetch_usgs_discharge.PUGET_GAGES` names 12097500 "Green R nr Lester";
`data/processed/usgs_gauge_sites.parquet` names it Greenwater River at Greenwater. The basin
polygon follows the site number.)

## 3. Design record (proposed text for #265)

### 3.1 Components and the vertical partition

Three components share one water ledger:

| Component | Owns | Grid | Step |
|---|---|---|---|
| Land surface model (LSM): existing snow, canopy, root-zone code, repaired | SWE, canopy storage, root-zone storage over [0, d_root(x)], AET | 90 m ledger grid (`src/config/domain.DOMAIN`, EPSG:5070) | daily |
| MODFLOW 6 GWF + UZF | unsaturated transit and groundwater from the root base down; heads per layer | MF6 grid nested in the ledger grid (3.2) | daily stress period, adaptive sub-steps |
| MODFLOW 6 SFR (+ MVR) | stream–aquifer exchange, rejected infiltration and seepage routed to streams, reach flows at gauges | NHDPlus HR reaches on the MF6 grid | daily |

**Partition (recommended, option B):** the MF6 model top is the root base, z_s − d_root.
The LSM owns all water in the root zone; MF6 owns everything below. Downward exchange is LSM
gravity drainage → UZF infiltration. Upward exchange is UZF/groundwater seepage at the MF6 top
→ LSM root zone (and saturation-excess runoff when the root zone is full). No pore volume is
counted twice. Depth to water is still reported against land surface: D = z_s − h_wt. The LSM
is a single-layer bucket with no profile, so inside the root zone D follows an explicit rule:
the root zone saturates from its base up, with saturated thickness s = W_fc+ / (θ_sat − θ_fc),
where W_fc+ is root-zone water above field capacity (m), so D = d_root − s while the MF6 head is
at or above the root base. Upward flux from a table just below the root
base (capillary rise, riparian ET) is UZF groundwater ET with an extinction depth below the root
base, booked in the ledger like seepage. A 1-D valley column with the table crossing the root
base, run under options A and B against the Richards reference (#267), checks head continuity,
D (within 0.1 m) and the upward flux. Upland stormflow that moves laterally in colluvium inside
the root zone is an LSM process (#174), not MODFLOW. This is the same soil-zone-over-UZF split
that GSFLOW uses (reference pending verification, §8).

**Option A (benchmark variant):** MF6 top = land surface, UZF owns the whole unsaturated
column including root-zone ET, and the LSM keeps only snow and canopy. One ledger, simpler
coupling, but root-zone θ comes from a gravity-only kinematic wave with no capillarity, which
degrades the validated θ product and every soil-moisture and dv/v operator. Run it once on the
pilot as a structural comparison, not as the production path.

### 3.2 Horizontal grid

- MF6 uses a structured DIS grid in EPSG:5070 whose origin is snapped to the 90 m ledger grid
  and whose cell size is Δ = k × 90 m, k ∈ {1, 2, 3}. Each MF6 cell is an exact k × k block of
  ledger cells, so aggregation (LSM → MF6) and disaggregation (MF6 → 90 m products) are exact,
  area-weighted and conservative.
- Δ is chosen by a convergence test on the pilot (issue MF-09), not asserted. Criterion: Δ must
  put at least three cells across the median ridge-to-channel distance computed from the
  existing flow-routing layers, and heads at calibration wells and simulated baseflow must
  change by less than their observation error between Δ and Δ/2.
- The convergence test also requires at least three cells across the valley-floor width and
  compares SFR gain/loss per reach between Δ and Δ/2.
- Quadtree/DISV refinement (cells of 90·2ⁿ m also nest exactly) is advisory, adopted only if the
  convergence test fails at an affordable Δ; XT3D is required at any refinement interface or
  non-conforming GWF–GWF exchange.

### 3.3 Vertical layering

Layers follow hydrostratigraphic units (HSUs), not uniform slabs. Lowland sequence (top down):
Holocene alluvium / Vashon recessional outwash; Vashon till (aquitard, perched water above it);
Vashon advance outwash; pre-Vashon fine-grained units; older coarse units; bedrock. Uplands:
colluvium, weathered bedrock, fractured bedrock with K decreasing with depth. Absent units are
vertical pass-through cells (MF6 `IDOMAIN = -1`). Mapped lahar deposits (Osceola/Electron) are
their own unit (#264). Sources: published Puget Sound framework surfaces (MF-02), WA Ecology
well reports (MF-03), DNR geology (#21). Geometry uncertainty (surface elevations, till
continuity) enters as framework realizations conditioned on the logs (MF-18), not only as K
perturbations. Perched water above the till or the lahar cap uses NPF `VARIABLECV DEWATERED`
with `PERCHED` (#130). Glacial sediments reach several hundred metres in southwestern King
County (reviewer citation of USGS WRIR 92-4098, to verify), so the model bottom depth is tested
in MF-09 (bedrock top vs 300 m deeper).

### 3.4 Boundaries

| Boundary | MF6 package | Data |
|---|---|---|
| Puget Sound shoreline | GHB at mean sea level in NAVD88 | NOAA tide station + VDatum (#10) |
| Streams and rivers, both directions | SFR | NHDPlus HR via SFRmaker (MF-04) |
| Seepage faces, springs | UZF seepage, DRN at the model top | DEM |
| Lowland boundaries between neighbouring watershed models | GWF–GWF exchange in one MF6 simulation | shared HSU framework |
| Mountain front (lowland model meets the foothills) | either the domain extends into a bedrock HSU with K decreasing with depth, or a specified mountain-front flux from LSM drainage on the uplands; sensitivity tested | DNR bedrock contact (#21), LSM |
| Regulated rivers (Green below Howard Hanson Dam, White below Mud Mountain Dam / Buckley diversion) | SFR specified inflow from the upstream gauge | USGS discharge |
| Lakes and reservoirs (Lake Washington, Sammamish, Tapps, Kapowsin, kettle lakes) | LAK with stage observations (milestone B); pilot wetlands as UZF seepage + DRN | MF-19 |
| Upland watershed divides in bedrock | no-flow, tested (Haitjema & Mitchell-Bruker 2005: a surface divide need not be a groundwater divide) | DEM, geology |
| Model bottom | no-flow at the base of the bedrock layer, depth tested | framework |
| Pumping and return flows | WEL; septic/irrigation return as recharge | WA Ecology withdrawals, county septic records, or a documented bound (MF-05) |
| Glacier melt, snowmelt | via LSM into UZF / SFR | #227, #234 |

### 3.5 Watershed-specific models

One MF6 GWF model per watershed (lowland groundwater basins and the gauged mountain basins),
each with its own HSU parameter zones, run together in a single MF6 simulation joined by
GWF–GWF exchanges where aquifers cross surface divides. A groundwater model domain encloses its
gauge basin with head-dependent river boundaries; it is not clipped to the surface basin.

### 3.6 Time

- Daily stress periods on the PRISM 12–12 UTC day (#244), adaptive time stepping inside a day.
- Initial condition: steady state on long-term mean LSM drainage, then a warm-up repeating the
  first water year until the head drift per year is below 1% of the observed seasonal amplitude
  at calibration wells (a measurable stopping rule, recorded with the run).
- Hindcast window WY2001–present (matches the 2000–2026 well record; PRISM daily covers it, #70).
  Calibration / validation split by years and by wells, frozen in the #235 manifest before any fit.

### 3.7 State, parameters and the DA contract (#187)

State vector x per member: heads h_k for every active MF6 cell and layer; LSM root-zone storage
and SWE on the 90 m grid. UZF internal wave state is advanced but not updated (it is forced by
LSM drainage); this is a declared approximation, valid only where vadose transit time is short
relative to the cycle. #188 (a) sets the transit-time threshold above which UZF water content is
added to the state. Heads are now the prognostic variable; `src/models/hydro_state.py`, which
calls storage canonical, is updated in #187. Diagnosed, never assimilated directly: D; u(z)
interpolated from MF6 layer heads (hydrostatic only as a declared within-layer fallback, because
recharge areas under till carry strong downward gradients); θ(z) from LSM and UZF water content;
σ′(z). No inner-loop parameter augmentation in the pilot (it would reuse the data PEST++ already
fitted).

### 3.8 Two estimation loops

| Loop | What it estimates | Method | Data |
|---|---|---|---|
| Outer, offline | static parameters (K, S_y, S_s, UZF, SFR and GHB conductance) | PEST++ IES with pyEMU; HSU zones + pilot points; prior ensemble from cited per-unit ranges | calibration-role wells, filtered baseflow at gauges, seasonal amplitude at recorders |
| Inner, cycling | states (heads, root-zone storage, SWE) | ensemble Kalman (LETKF or EnSRF) with MF6 advanced through modflowapi, paused and updated between stress periods | every sensor in §4 at its native support |

DA increments are booked per store as non-physical fluxes (Codex rule). The booked volume is
ΔV = V(h_a) − V(h_f), where V is MF6's own piecewise storage function summed over layers (S_y
over the unsaturated part of each convertible cell, S_s times saturated thickness), so an
increment that crosses a cell bottom or dries a cell is booked correctly. Any analysis water
table above the MF6 top is moved into LSM root-zone storage and booked on both stores. Every
clip (dry cell, negative SWE, root zone outside [θ_wp, θ_sat]·d_root) is its own booked increment.

**Data roles.** The #235 manifest gives each well-year exactly one role: PEST++ calibration,
filter assimilation, or held-out. Using one datum in both loops makes the posterior too narrow
by construction. PEST++ IES assumes no model error while the filter carries Q, so IES parameters
absorb some structural error; recorded, not solved.

**Localization** tapers with distance and hydrogeologic connectivity rather than zeroing across
layers or unconnected models: shared forcing correlates errors over ~12 km even where no flow
connects the cells. Vertical coupling within a column is kept. This is a declared approximation.

### 3.9 Conservation and acceptance

- MF6 reports a budget discrepancy each stress period. Its acceptance threshold is set by a
  solver-closure refinement test (tighten the closure; the discrepancy must shrink with it), not
  a fixed number.
- LSM ↔ MF6 exchange is an exact block sum in float64; tolerance = machine epsilon × cells summed.
- The whole-system ledger (#232) adds LSM stores, the MF6 budget, the exchange fluxes and DA
  increments, over a stated control volume and window.
- Skill against gauges and wells is reported separately from conservation. Missing physics can
  lower skill without breaking conservation.
- **Fitness for purpose.** Every skill report states the target per measurement target (water
  table vs screened-aquifer head) and per hydrogeologic domain, and the consumer it serves: the
  liquefaction screen needs seasonal-high D in liquefiable lowland units to the accuracy fixed by
  #270; landslides need perched pore pressure, which MF6 supplies only at k × 90 m (hollow-scale
  convergence stays #133).

### 3.10 What stays from the statistical pipeline

The Stage 1–3 GWL map (LightGBM baseline + kriging) becomes a benchmark that MF6 must beat on
held-out wells or the gap is reported, an initial head guess, and a structural member (#32).
Its open correctness bugs (#230 sign inversion, #186 variance back-transform) still matter and
stay in the queue.

## 4. Sensors and their observation operators

| Sensor | Kind | Native support | State observed | Operator (issue) |
|---|---|---|---|---|
| NWIS / Ecology wells, discrete | raw | point, screened interval, timestamp | H(x, z) of the screened layers | screen-to-layer weights; only water-table wells observe h_wt; raw timestamped measurements with an asynchronous operator, not the site-month medians in `nwis_gwlevels_domain_monthly.parquet` (or a monthly-mean operator with the median-mean gap in R) (#9) |
| Continuous groundwater recorders | raw | point, sub-daily | same | daily mean of the recorder (#235, #9) |
| USGS stream gauges | raw | basin outlet, daily | SFR reach outflow | total SFR outflow at the gauge reach in the filter; filtered baseflow (same filter as the observation) only in PEST++ and validation, because filtered series carry correlated errors; never mapped onto head (#237) |
| Soil probes (SNOTEL, USCRN, Rainier) | raw | point, 5/20/50 cm | root-zone θ profile | depth operator on the LSM profile (MF-16) |
| SNOTEL SWE | raw | point | SWE | elevation-aware point operator (existing calibration, #234) |
| SMAP L3/L4 | satellite | 9–36 km, 0–5 cm and root zone | surface / root-zone θ | footprint mean of 90 m θ, declared bias treatment, σ from the mission ubRMSE (MF-16) |
| NISAR soil moisture | satellite | 200 m | surface θ | 90 → 200 m aggregation (#197 ingest, MF-16 operator) |
| GRACE / GRACE-FO | satellite | ~300 km mascon | total water storage anomaly | context only, not validation: one mascon is larger than the domain, so its sum includes area the model does not cover (#29) |
| GNSS vertical | geodetic proxy | regional | surface load from TWS | elastic loading Green's function (#226); a hypothesis until per-basin sensitivity exceeds noise |
| InSAR / GNSS poroelastic | satellite / geodetic proxy | 30–90 m | aquifer-system compaction S_s·b·Δh | scoping first: is the signal above noise in Puget glacial aquifers? (MF-17) |
| Ambient-noise dv/v, DAS | geophysical proxy | station-pair footprint, band depth kernels | Vs(z) through σ′(z) and saturation | one forward hydromechanical operator on MF6 heads + LSM/UZF θ (#198; kernels #247, #251); never the inverted DTW from `dvv_coupling.invert_dvv`, which reuses the model baseline; non-overlapping stacks; AR(1) bias state for thermal and snow-load terms; operator coefficients in the parameter ensemble |
| Sentinel-2 surface water | satellite | 10–20 m | groundwater at or above the model top | seepage / saturated-extent check (#109) |

## 5. Pilot

**Recommendation for #269:** a groundwater model domain on the Enumclaw plateau that encloses
the whole Newaukum Creek basin (gauge 12108500, 79 km², 21 NWIS wells, 11 with ≥12 months),
bounded by the Green River and the White River as SFR boundaries with gauged specified inflows
(both are regulated). The Newaukum headwaters drain the foothills, so the domain either extends
into a bedrock HSU or takes a mountain-front flux; the decisive check is an overlay of the
12108500 basin on the DNR bedrock contact, then a no-flow vs mountain-front-flux sensitivity on
baseflow.
Reasons: the most wells of any gauged basin; a lowland glacial sequence that exercises the HSU
layering; the Osceola lahar cap (#264) makes most plateau wells semiconfined, a real test
of layer-aware operators. With 11 wells of ≥12 months the calibration is thin, so MF-03 adds
static levels at well completion as steady-state targets, and MF-10 runs a wells-blind control
(calibrate on the gauge alone, score the wells). Alternative: Clarks
Creek (12102078, 16 wells), spring-fed from the Puyallup valley wall. A published USGS model in
the pilot area, if one exists, is the benchmark and the starting framework (§8).

The Rainier hydromechanics sub-box stays second: no heads there, so it is the test of whether
gauges + dv/v + GNSS constrain basin storage without wells (MF-14).

## 6. Issue map

### 6.1 New issues

| Code | Title | Milestone | Priority | Hard blockers |
|---|---|---|---|---|
| MF-00 | [epic] Groundwater core: MODFLOW 6 + land surface + multi-sensor DA | A | – | – |
| MF-01 | MODFLOW 6 toolchain in pixi + CI smoke model | Software | P0 | none |
| MF-02 | Regional hydrostratigraphic framework on the 90 m grid | A | P1 | none |
| MF-03 | WA Ecology well reports: lithology and screen intervals | A | P1 | none |
| MF-04 | SFR network from NHDPlus HR + gauge reach mapping | A | P1 | MF-01 |
| MF-05 | Net withdrawals and return flows, or a bounded omission | A | P1 | none |
| MF-06 | LSM ↔ MF6 exchange: exact block aggregation, drainage out, seepage back | A | P1 | MF-01, #265 |
| MF-07 | Pilot MF6 builder and steady-state run | A | P1 | MF-01, MF-02, MF-04, #10, #265, #269 |
| MF-08 | Transient pilot: daily stress periods, UZF, spin-up | A | P1 | MF-06, MF-07, #70, #234 |
| MF-09 | Grid resolution and layering convergence study | A | P1 | MF-07 |
| MF-10 | PEST++ IES history-matching setup + fixture run | A | P1 | MF-08, #235 |
| MF-11 | Production pilot history match on Hyak | A | P1, needs-compute | MF-10 |
| MF-12 | Held-out validation of the calibrated pilot | A | P1 | MF-11, #236 |
| MF-13 | Multi-model MF6 with GWF–GWF exchanges for all watersheds | B | P1 | MF-09, MF-12 |
| MF-14 | Regional history match; mountain basins without wells | B | P1, needs-compute | MF-13 |
| MF-15 | MF6 ensemble runner over modflowapi | Applied math | P1 | MF-01, MF-06, #155 |
| MF-16 | Soil-moisture operators: probes, SMAP, NISAR | Applied math | P1 | #52 |
| MF-17 | Poroelastic deformation scoping (InSAR / GNSS vertical) | Applied math | P2 | MF-08 |
| MF-18 | Hydrostratigraphic framework realizations (geometry uncertainty) | A | P1 | MF-02, MF-03 |
| MF-19 | Lakes and reservoirs: LAK package with stage observations | B | P1 | MF-13 |
| MF-20 | ParFlow-CLM benchmark on the pilot (HydroFrame CONUS2 subset) | A | P2, needs-human-decision | MF-08 |

Milestone A = "Groundwater model: MODFLOW 6 hydrogeologic core". Milestone B = "Groundwater
model: scale-out to the western-Cascades watersheds".

### 6.2 Rewritten issues (scope changes, previous body archived under `<details>`)

| Issue | New scope | Hard blockers |
|---|---|---|
| #265 | Design record = §3 of this plan; PI approval removes `needs-human-decision` | none |
| #269 | Pilot groundwater domain + benchmark, recommendation §5 | none |
| #10 | Coastal GHB boundary data (MSL in NAVD88, shoreline cells, conductance prior) | none |
| #9 | Well head operator: screen interval → MF6 layer weights | MF-02, MF-03 |
| #232 | Whole-system ledger: (a) LSM stores now, (b) coupled LSM + MF6 + DA increments | none |
| #236 | Cal/val harness on MF6 outputs (basin-masked SFR flux, model-hydrograph BFI, layer-aware well sampling) | MF-01, #9 |
| #237 | Gauge operator on SFR reach outflow | MF-04 |
| #187 | Contract: MF6 per-layer heads on the MF6 grid + LSM stores at 90 m; per-store increments | #52, #265 |
| #188 | Cycling ensemble on MF6: (a) linear-Gaussian exact case then fixture OSSE, Q and diagnostics from day one; (b) pilot wells; (c) multi-sensor | MF-15, #187, #9, #235, MF-11 |
| #130 | Perched water above a low-K cap (Vashon till or Osceola lahar) as an MF6 layer; fall-shallow vs spring-deep test | MF-08, #235 |
| #174 | Upland root-zone lateral flow in colluvium (LSM), quickflow and recession test at 12097500 and 12115000 | #232 |
| #235 | Adds: one role per well-year (PEST++ / filter / held-out) | unchanged |

### 6.3 Superseded (labelled `superseded`, held; closing is the PI's call)

| Issue | Replaced by |
|---|---|
| #171 epic | MF-00 |
| #172 deep vadose store | UZF in MF-08 |
| #131 vadose transit lag | UZF kinematic wave, tested in MF-08 / MF-12 |
| #173 saturation-excess one-step fill | partition option B + MF-06 seepage return |
| #175 baseflow sink / BFI anchor | SFR exchange, MF-10 / MF-12 |
| #233 valley cells with no sink | SFR, DRN and seepage in MF-07 |
| #266 2-D Boussinesq aquifer | MF6 GWF (MF-07, MF-13) |
| #89 daily vs monthly drainage | MF6 runs daily only; monthly path retired |
| #137 S_y + held-out validation | MF-10, MF-11, MF-12 |
| #177 minor fixes (groundwater) | its live items went to #233 / #234; the rest are superseded |

### 6.4 Blocker re-pointing on otherwise unchanged issues

| Issue | Old blockers | New blockers |
|---|---|---|
| #198 | #172, #187, #247 | #187, #247 (body adds: forward operator only, coefficients in the ensemble) |
| #226 | #187, #189, #100, #172 | #187, #189, MF-08 |
| #225 | #172 | #232 |
| #176 | #172, #131, #198 | #232, #198 |
| #142 | #137, #9 | MF-12, #9 |
| #261 | #137 | MF-12 |
| #252 | #128, #130 | unchanged |
| #257 | #232 | MF-04 |
| #191 | (table only) #188 | #188, now in the body |

The hard-coded `BLOCKED_BY` table in `scripts/gaia_group_issues.py` is emptied: issue bodies are
the single dependency list (Codex rule). Before emptying, the table and the bodies were diffed;
the only table-only edge was #191 → #188, now written into #191.

## 7. Agent-runnability

- Every new issue is sized for one queue session (`GAIA_ISSUE_TIMEOUT` 5400 s, 40 files, 4000
  lines). Anything that needs an ensemble or a multi-hour MF6 run is split into a build-and-fixture
  issue (agent) and a production-run issue labelled `needs-compute`, which the grouper holds.
- CI never runs a real watershed model. MF-01 adds a synthetic MF6 fixture that runs in seconds;
  later issues test against it.
- New labels: `modflow` (topic, routes to the hydrogeologist and DA methodologist), `superseded`
  and `needs-compute` (both holds, read by the grouper).
- The grouper gains cycle detection: an issue on a dependency cycle is reported on stderr.

## 8. Relation to `docs/groundwater-physics-plan.md`

A separate proposal with that path was written on 2026-10-18 from the rainier3d exploration
(`Denolle-Lab/mt-rainier-digital-model`, branch `paper-review-fixes`, `8a8bb36`). It is untracked in
the working tree and not part of this PR; committing it is the PI's call. It keeps the store
model as the cycling/DA model and uses MODFLOW 6 as a steady-state IES prior and a candidate
lateral engine. The PI's 2026-10-18 instruction makes MODFLOW 6 the groundwater core instead, so
that central point is superseded. Adopted from it:

| Item | Where it lands |
|---|---|
| Package availability and versions checked 2026-10-16 (modflow6 6.8.1, flopy 3.11.0, modflowapi 1.0.1, xmipy 1.5.0, pestpp 5.2.27, pyemu 1.4.0, pywatershed 3.0.0, all conda-forge); pestpp includes GPL-3.0 parts, so it runs as an external program and is never vendored | MF-01 (re-verify at install) |
| Newton formulation for dry cells on steep ground | MF-07 |
| Representativeness error estimated from repeat-measured wells; single drilling-day levels spread 1973–2023 are not one steady state | MF-03, MF-10 |
| Extra Rainier gauges (Mineral, Mashel, Orting, Carbon, South Prairie, Huckleberry, Clearwater, White below Clearwater); glacier-fed basins down-weighted for baseflow until ice is a store | MF-13, MF-14 |
| ParFlow-CLM from the HydroFrame CONUS2 subset as the benchmark that carries suction (UZF has no matric potential), needing a HydroFrame PIN and a Hyak container | MF-20 (held: needs-human-decision) |
| Its warning that daily transient MF6 on ~1.6 M cells costs hours per member-year | MF-09 measures runtime per member-year at each k and projects the cost of an N = 50 filter; if unaffordable, the filter runs on watershed models one at a time or at larger k, decided then |
| A domain-wide steady-state IES at 270 m as an early water-table prior | recorded as an alternative ordering; this plan validates the pilot first and runs the domain-wide steady state as the first step of MF-13 |
| ACE2 / HiRO-ACE scenario forcing and the possible ACE2-precipitation correction in `fetch_earth2studio.py` | out of scope here; belongs with #71 |

## 9. References (verification pending)

To be filled from Crossref-verified records only; anything unverified is marked so and kept out
of `docs/references.bib`. Items: MODFLOW 6 GWF (Langevin et al. 2017), UZF and SFR documentation,
FloPy (Bakker et al. 2016), MODFLOW 6 BMI / modflowapi, PEST++ v5 and IES, pyEMU, GSFLOW
(Markstrom et al. 2008), Vaccaro et al. 1998 Puget Sound framework, any USGS model in the pilot
area, Haitjema & Mitchell-Bruker 2005 (already in `docs/references.bib`).

## 10. Questions for the reviewers

1. Is partition option B (MF6 top at the root base) physically sound for valley cells where the
   water table sits inside the root zone for months, and for hillslopes where it never does?
2. Is a lowland pilot on the Enumclaw plateau the right first test, given the lahar cap?
3. Is "UZF state advanced but not updated" an acceptable DA approximation, or does it bias the
   head update when the vadose zone is thick?
4. Can heads in mountain basins without wells be constrained at all by baseflow recession, dv/v
   and GNSS, and what is the decisive test (MF-14)?
5. Does Δ = k × 90 m nested in the ledger grid lose anything a DISV grid would keep?
