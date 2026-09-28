# What the rainier3d atlas can give the soil twin

Date: 2026-09-28. Branch: `docs/rainier3d-leverage-2026-09-28` (off `origin/main`).

## Provenance

| Item | Value |
|---|---|
| Source repo | Denolle-Lab/mt-rainier-virtual-3d-model, published as `mt-rainier-digital-model`, package `rainier3d` |
| Code read | branch `terrain-geometry`, commit d827cc3 (2026-09-26). An agent checked with `git rev-list origin/main..<branch>` that every feature branch is merged into rainier3d `main` |
| Products | GitHub release `products-v1.0.0` (CC-BY 4.0, `SHA256SUMS`); `hydrothermal-alteration-em-v1`; weekly `gnss-latest` |
| Verification | Read only. Nothing was rerun. Numbers are quoted from `docs/paper/rainier3d_paper.md` and `docs/*.md` in that tree. The alteration and GNSS statements were checked directly against `docs/alteration.md` and `docs/gnss_strain.md` |
| Twin state | `western-cascades-v0.4`, EPSG:5070, 90 m (`src/config/domain.py`). Storage-conservation work (S1a/S1b) is on `work/storage-conservation-2026-09-10`, not merged |

## Verdict

rainier3d is a static digital model, not a twin. It has no soil moisture, groundwater state, dv/v or InSAR.

Its box sits inside the twin domain:

| | Projection | Extent | Grid |
|---|---|---|---|
| rainier3d | EPSG:32610 | 70 × 75 km, 46.50–47.15° N | 100 m surface grid |
| Twin | EPSG:5070 | contains the rainier3d box | 90 m |

The twin already covers the Carbon, White, Puyallup and upper Nisqually gauges. It masks the edifice as `volcanic_deep` (`src/features/hydrogeologic_domains.py:22-24`). Neither repo references the other.

What transfers falls into three groups:

- **Event and hazard observations.** These address the twin's largest validation gap.
- **Static structure.** Canopy, ice, terrain, alteration.
- **Hydromechanical observables.** GNSS seasonal loading, the Longmire tiltmeters, and node and DAS geometry.

## Products ranked by the twin gap they close

| # | rainier3d product | Twin gap | Use in twin | Caveat |
|---|---|---|---|---|
| 1 | S24 mass movements, `outputs/mass_movements/events.gpkg`: 1,650 events, crowns on 1 m 3DEP, `depth_m` (median 14.6 m, n = 453), 351 dated to the January 2009 storm | `soil_mechanics_fs_90m.tif` and `_pfail_90m.tif` have no producer in the repo; `estimate_mechanics` raises `NotImplementedError` | Labelled targets for a Rainier-box susceptibility score; January 2009 as an event hindcast | No trigger field. A 14.6 m failure depth puts the slip surface in regolith or deposit, below the 2 m SOLUS cap |
| 2 | S29 December 2025 atmospheric river, `data/processed/events/dec2025_ar.zarr`: MRMS 1 h QPE at 1 km, 15 NWIS gauges, 3 seismic virtual gauges (NSE of log Q 0.75–0.95) | Audit S5: gauges have no flux operator. Event-based validation is missing. Orographic forcing is unchecked | Event-scale runoff-partition test; PRISM vs MRMS by elevation (MRMS: 169 mm below 500 m, 547 mm above 3000 m); virtual gauges for ungauged headwaters | File not on disk; rebuild with `pixi run s29` in rainier3d |
| 3 | S18 GNSS, `gnss/strain_grid.nc` (5 km): annual areal-strain amplitude (median 15 nanostrain) and peak day; `gnss/daily.parquet` | Audit S11: GRACE labelled as groundwater. No total-water-storage (TWS) constraint. Loading is a dv/v confounder (`docs/twin/04-assimilation.qmd:578`) | Elastic-loading operator: twin TWS → vertical displacement, compared with PANGA vertical series; loading correction for dv/v | 5 km horizontal strain is a weak loading target. 22 of 203 sites are flagged, including the snow-affected edifice sites |
| 4 | S19 canopy, `surface_canopy.zarr`: lidar canopy height and cover (10 m), Sentinel-2 LAI, GEDI PAI and biomass | No canopy interception anywhere in `src/` | Gash or Rutter interception store under the storage-conservation contract | Lidar CHM is `redistribute_derived: false`; publish only LAI/GEDI-derived products |
| 5 | S1 IceBoost v2 ice thickness (219 glaciers, 5.50 km³); S30 `terrain_geometry.zarr` (30 m slope, relief, valley depth, bedrock elevation) | No glacier mask or melt; Rainier gauges carry melt the budget cannot produce | Glacier mask and degree-day ice melt in `src/models/forecast.py`; terrain covariates for row 1 | IceBoost is thicker than GlaThiDa on Emmons (273 vs 185 m) and Winthrop (237 vs 98 m) |
| 6 | S4/S13 velocity model `model.zarr` L1 (Vp, Vs, ρ; 50 m vertical); 191 2025 nodes in the box; Paradise–Nisqually DAS (3,191 located channels with lithology) | #198 depth-resolved operator; #164, #168 3-D kernels | Local 1-D columns for dv/v sensitivity kernels at Rainier stations | rainier3d flags its top 300 m as unresolved; its rock physics uses hydrostatic pressure and has no saturation term |
| 7 | S22 EM, `alteration_finn2001.zarr`: apparent resistivity ρa at 33 kHz, 4737 Hz, 4341 Hz and 837 Hz, depth of investigation up to 150 m, alteration intensity `a`, apparent magnetization; 126 km² of surveyed edifice lava | Edifice masked; no permeability beyond Saxton–Rawls (#50) | Control on water pathways (next section) | Edifice only; wet moraine reads conductive; thresholds are `m1_placeholder` |
| 8 | UW.LON9 Longmire tiltmeters (3 Paroscientific units, 100 Hz, since 2024-08-20); station tables in `mt-rainier-smart-sensing/data/stations/` | No hydromechanical observable other than dv/v | Candidate pore-pressure and loading observation | Metadata only; needs ingest and a tilt forward model |
| 9 | Tooling: `configs/sources.yaml` licence tiers, `products.json` checksummed releases, bibliography registry (`pixi run bib` stops on an unresolved DOI) | Fabricated DOIs in the twin's `references.bib` (lane B1) | Port the bibliography and source registries | None |

**Excluded.**

- Edifice-load stress (`edifice_load.zarr`, 1–40 MPa, deep crust) and tectonic strain rates (about 17 nanostrain/yr). These are not soil-scale. The "geodetically informed stress model" transfers only through its seasonal GNSS component.
- Ma et al. 2026 water table (CC-BY-NC-ND, never published). The twin already uses HydroGEN (Ma 2025).

## Alteration as a control on water pathways

Hydrothermal alteration sets where water moves on the edifice. The rock it weakened also became clay-rich lahar deposits in the lowland, inside the twin domain.

The mechanisms below are hypotheses from the literature. Each citation must resolve through the bibliography registry before it enters a twin document.

1. **Edifice permeability and storage.** Argillic alteration (smectite, kaolinite) fills fractures in otherwise permeable lava. Altered zones become low-conductivity barriers with perched, near-saturated water above them. Fresh fractured lava drains fast and stores little. Sources to verify: Finn, Sisson & Deszcz-Pan (2001); John et al. (2008).
2. **Strength and pore pressure.** Wet clay-rich rock is weak, and perched water raises pore pressure. This is the published collapse mechanism for the Osceola and Electron events. Source to verify: Reid, Sisson & Brien (2001). Alteration therefore enters both the hydraulic and the mechanical inputs of the factor-of-safety path.
3. **Lowland lahar cap.** The Osceola deposit covers the Enumclaw plateau and the White and Puyallup valley floors. Hypothesis: clay-rich lahar deposits act as a low-permeability cap, giving poorly drained soils, perched water and confined heads in wells screened below them. Source to verify: Vallance & Scott (1997).
   - The twin's `data/processed/lithology_crosswalk.json` and `src/` have no lahar or mudflow entry, so these deposits fall into generic "unconsolidated". Checked by grep on 2026-09-28.
   - rainier3d keeps `lahar_deposits` as a unit (`configs/units.yaml:12`) and maps 466 flow polygons in S24 `flows.gpkg`: Osceola 79.7 km², Electron 18.8 km².
4. **Hydrothermal discharge.** Fumaroles, the Longmire and Ohanapecosh springs, and stream solute flux are a deep inflow the twin does not represent. This relates to the S1b "upgradient inflow" remaining-work item. Source to verify: Frank (1995). The volume is likely small for the budget, but useful as a tracer.

**The EM signal conflates clay and water.** Apparent resistivity drops with clay surface conduction and with pore-water saturation. rainier3d notes that wet moraine and valley fill read as altered (`docs/alteration.md:89`). Magnetics separate the two, because alteration destroys magnetite and wetting does not.

| ρa | Magnetization | Class |
|---|---|---|
| low | low | altered |
| low | normal | wet, unaltered |

The wet-unaltered class is a static near-surface saturation map from the 1996 survey. It is the only one on the edifice.

Limit: the terrain-correlated magnetization does not see buried west-flank alteration (1.56 A/m west vs 1.33 A/m east, `docs/alteration.md:88`).

**What alteration does not yet justify.** It does not justify a calibrated conductivity field or claims of perched tables on the edifice: there are no twin wells there, and the thresholds are placeholders. Until R6b and R6d pass their controls, alteration stays a domain split with prior parameters.

## Slices

Each slice follows the science-slice workflow on its own branch off `main`: `plan.md` → twin reviewer rounds → negative controls → record directory.

| Slice | Content | Verification | Controls |
|---|---|---|---|
| R1 (#223) | `src/data/fetch_rainier3d.py`: download release assets, check `SHA256SUMS`, reproject 2-D layers to the 90 m EPSG:5070 grid, `assert_on_grid()`, `source_commit` attribute | Ice volume on the 90 m grid within 2% of 5.50 km³ | – |
| R2 (#224) | Event hindcasts: December 2025 AR and January 2009 storm. Score discharge (15 gauges plus 3 virtual gauges), PRISM vs MRMS by elevation, landslide ROC/AUC | Record states whether each control is beaten | Time-shifted forcing; slope-only baseline (event median slope 27.9° vs 18.5° for the box) |
| R3 (#225) | Canopy interception store in `src/models/water_budget.py`, LAI-based capacity | Conservation and boundary tests pass with the store on and off | – |
| R4 (#226) | TWS → vertical displacement operator (disk-load elastic Green's function), registered in `STREAMS` in `src/models/observability.py` | Unit test against the analytic disk load; annual amplitude and phase compared at PANGA sites | Snow-flagged sites excluded |
| R5 (#227) | IceBoost glacier mask and degree-day ice melt | August–September discharge at 12082500 (Nisqually) and 12092000 (Puyallup) | – |
| R6a (#228) | Split `volcanic_deep` into fresh and altered edifice; log10 K = log10 K_fresh − Δ·a; Δ and K ranges as `working_hypothesis` priors | Twin-hydrogeologist review before any code | – |
| R6b | Clay vs water classifier from 33 kHz ρa and magnetization → `alteration_class` | Wet-unaltered cells concentrate on moraine, glacier margins and valley fill | North–south-flipped grid (rainier3d registration gave r = 0.08 flipped) |
| R6c | Lahar-cap class in the twin lithology crosswalk (`src/data/rasterize_geology.py`); links #46, #50 | Stage 1 residuals and Stage 2 amplitudes on vs off the cap, matched for HAND and slope, with a confidence interval | Randomly shifted cap polygons |
| R6d | S24 failure density in cells with a ≥ 0.5 vs slope- and relief-matched fresh cells | Density ratio with interval | Flipped alteration grid |
| R6e | Springs and fumaroles as fixed-inflow cells (deferred until the upgradient-inflow boundary exists) | – | – |

**Order.** None of these goes ahead of the P0 contracts (#187, #198) or the hydrology pilot (#189 → #188). The table is also in `ROADMAP.md`, and in each issue.

| Step | Slice | Condition |
|---|---|---|
| 1 | R1 | – |
| 2 | R6d, R6b | Existing data only. Decides whether alteration carries a signal worth modelling |
| 3 | R6c | – |
| 4 | R2, discharge part | – |
| 5 | R5 | – |
| 6 | R2, landslide part | After #128, the factor-of-safety implementation |
| 7 | R3 | After the S1a/S1b storage work reaches main |
| 8 | R4 | After #187 and #189 |
| 9 | R6a | After a twin-hydrogeologist review and the R6b/R6d outcomes |

Priorities: R1, R2 and R6 are P1. R3, R4 and R5 are P2.

**Later.**

- Local dv/v kernels (row 6), after #198 is designed. The saturation sensitivity `K_SAT` in `src/models/dvv_coupling.py` should then become domain-dependent.
- Tiltmeters (row 8).
- Porting the bibliography registry (row 9), in parallel with lane B1.
