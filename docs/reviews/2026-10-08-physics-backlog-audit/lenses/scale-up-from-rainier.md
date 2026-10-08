# Lens: scale-up-from-rainier

# Can the soil-state twin scale up from the Mt Rainier prototype (rainier3d)?

Lens: computational hydrologist / digital-twin architect. Sources: rainier3d clone at d61305c (CZ module 6ad0fe7, 2026-10-03), twin origin/main at 435445f, issues.json, the 2026-09-28 leverage review (branch only), and queue_sim.jsonl. Probes were run under `wf/scale/` (bench_richards.py, bench_batched.py, bench_365.json). Every number marked "measured" comes from those probes on a 3.0 GHz Xeon W-2150B core. Numbers marked "estimated" are extrapolations.

## Verdict

Yes, but only as a library and an oracle, not as the cycling model. rainier3d gives the twin three things it lacks:

1. A physically consistent static critical-zone medium: layer depths, porosity, permeability and van Genuchten parameters from soil to fresh rock.
2. A working mass-conservative 1D Richards solver.
3. A depth-resolved hydromechanical chain: suction stress → σ′ with overburden → Hertz–Mindlin/soft-sand → Gassmann–Brie → Rayleigh dispersion.

It does not give a water budget. The paper says the model "holds no hydrological state" (rainier3d_paper.md:968; :55 "digital model rather than a digital twin"). The Richards columns have no lateral flow, ET, interception or snow (richards.py:8-11; cz.yaml:50-58).

Running 1D Richards on every 90 m cell × 50–100 members is affordable only in compiled or GPU code. Even then it would be physically worse than a calibrated store model for the cycled variables, because it has no lateral drainage and its parameters below 2 m are `m1_placeholder`. The right architecture has three tiers:

- Richards as the oracle, at sensor sites and over a hydrologic-response-unit (HRU) library.
- Reduced-order, mass-conserving stores as the cycling forecast model, with parameters fitted to the oracle.
- Lateral flow added as a Dupuit/kinematic hillslope sink everywhere on steep ground, with explicit 2D Dupuit groundwater where the product needs the water-table *pattern*.

## (a) Transferable infrastructure

| Component | Evidence | Transfer value |
|---|---|---|
| CZ medium builder `rainier3d.cz.medium.profile/boundaries` | medium.py:32-156. Closed-form and vectorised over columns. W-index Hill blend; σ_tot is the cumulative column weight (:95-102); suction stress χ=Se (:101; rockphysics.py:62-64). log-k blend (:136-149) | **High.** Recompute it at 90 m on twin inputs; do not resample the 250 m product. The static build is seconds to minutes for 2.96 M columns. It gives store capacities: root, vadose and drainable porosity from vG. That is exactly what #137 and #172 need |
| Rock-physics chain | rockphysics.py:31-74; synthetics.py (disba kernels and dispersion) | **High.** This is the operator #198 asks for. The twin's version uses a constant σ0 = 10 kPa and P_e = σ0 + Se·Pc with no overburden (dvv_coupling.py:48,89). rainier3d is BSD-3, compatible with the twin's MIT licence |
| Richards solver | richards.py:54-135. Celia modified Picard, ponding switch, mass ledger | **Medium.** Good oracle seed, but it has a defect (below) and no ET, lateral flow or snow |
| National and state inputs | POLARIS vG in 6 layers to 2 m (twin fetches only the 0–5 cm Ksat/clay/sand: fetch_gaia.py:59-61). Ecology well reports + WGS boreholes (hydromet/wells.py:1-6). MRMS hourly QPE (S29) | **High.** The twin has no Ecology or WGS ingest; S31 found 5,591 levels in the Rainier box alone versus the twin's 863 clean NWIS sites (qc_report.json) |
| Wells module | wells.py (single static levels and bedrock picks, no hydrographs) | Medium. Good for priors and the regolith-depth score, useless for dynamics |
| Release, SHA256 and products registry; REBUILD.md; `products.yaml` classification; bibliography registry | docs/products.md:5-14; products.json | Medium. Process value. The twin has partial equivalents |
| Config-driven domain with `assert_on_grid` | rainier3d config/domain.py:102-127 | Low. The twin already has its own (src/config/domain.py) |

## (b) Rainier-specific (does not scale)

- Edifice footprint and base, magma ellipsoid, crack-closure unit table with PNSN-calibrated multipliers (V0 ×1.40/1.47, P*, Vs) and the regional bias.
- Finn 2001 EM alteration (126 km² of edifice only), Packwood magnetics, IceBoost glacier set.
- DNR 1:100k unit crosswalk and the weathering factors per unit (cz.yaml:73-82, all placeholders).
- Paradise DAS, the Z5 nodes, the Dec 2025 AR event and the S24 mass-movement compilation.
- The rock end-member `rock_fn` needs the Rainier unit table (level.py:17-21). A western-WA version needs a regional lithology-to-rock-law crosswalk, which does not exist.

## (c) Missing in both

- Lateral subsurface flow. The 1D column only has a Dupuit sink on paper (critical_zone.md:90-93). The twin's interflow is instantaneous, with no store (#174).
- ET / root-water uptake in Richards.
- Snow and glacier input to the columns (critical_zone.md:212; rainier3d S34 treats all precipitation as rain).
- A dynamic water table in the Richards oracle. Its bottom boundary is fixed at the static Fan 2017 water table (34_cz_storm.py:53).
- Spin-up. S34 starts from a hydrostatic profile on the static water table (medium.py:86; 34_cz_storm.py:55), which is dry-biased for a December storm.
- Any calibration of regolith hydraulics. These are placeholders (cz.yaml:28-31; paper:505).
- Aquifer maps (paper:993).
- Continuous well hydrographs. The USGS site service returns **0** continuous (iv) groundwater sites in the Rainier box, the Newaukum box and the Clarks Creek box, against 1,685 / 881 / 446 sites with discrete levels.
- Soil-moisture probes away from the mountains. The twin has 5 SNOTEL soil stations, all montane (snotel_anchor.json). Their leave-one-station-out RMSE gets worse after anchoring, 0.092 → 0.118.
- An ensemble or EnKF anywhere.
- A factor-of-safety (FoS) implementation in either repo (soil_mechanics.py:64).

### Defect found in the Richards solver (probe-verified)

Specific storage is added to the capacity (richards.py:21,46) but not to θ(h) (:36-39). In saturated cells, `th − th0 ≡ 0`, so each Picard iteration acts as one more pseudo-time step instead of converging.

- **Free-drainage bottom with a saturated zone:** the solver never converges. With the water table at 10 m in a 30 m column, the head drifts 3.5 mm per iteration indefinitely, even at dt = 0.1 s. `run` raises at once because dt starts at its minimum (:111, :121).
- **Fixed-head bottom:** it converges only because the Dirichlet node anchors the saturated zone. Mass-balance error was 0.007 mm/yr (30 m column) and 0.74 mm/yr (150 m column).

This is a plausible cause of the 8 failed S34 sites ("saturated to the ground", cz.yaml:54), not yet verified. It must be fixed before the solver is used as an oracle with a dynamic water table: include S_s·h·θ/θ_s in θ(h).

### 1D-only physics fails under cycling (probe)

One year of synthetic PNW hourly rain (1,760 mm, no ET), fixed-head bottom at 10 m: the column stored +1,060 mm and sent 699 mm out the bottom. With no lateral sink, storage only accumulates. This is the same disease as the twin's valley cells, where `gw_recess` = 0 for HAND ≤ d0 (water_budget.py:193-197).

S34's "no runoff" result for a storm that produced real floods (critical_zone.md:210) says the same thing. In the PNW, storm runoff is saturation-excess plus subsurface stormflow, which a vertical column with a dry hydrostatic start cannot generate.

## Cost: order of magnitude

**Measured:**
- Serial rainier3d Richards: **0.028–0.031 s per column-day** (38–52 layers; 96 adaptive steps and 218 Picard iterations per day; 129 µs per iteration, overhead-bound).
- Batched NumPy Picard with a vectorised Thomas solve: **6–12 µs per column-iteration**.
- Twin store model (`coupled_water_budget`, daily): **0.16–0.23 µs per cell-day**.

**Estimated:**
- Compiled CPU (Numba/C, SIMD): 1–3 µs per iteration.
- GPU (JAX/H200): ~3 Mflop per column-day at about 5 TFLOP/s effective.
- All tiers assume ~250–300 iterations per column-day.

| per simulated year, N=100 members | 2.96 M cells (twin) | ~12 M cells (W. WA, ~100k km² bbox) |
|---|---|---|
| Richards, serial Python (measured rate) | ~9×10⁵ core-h | ~3.7×10⁶ core-h |
| Richards, batched NumPy (measured kernel) | ~7×10⁴ core-h | ~3×10⁵ core-h |
| Richards, compiled CPU (est.) | ~1.5×10⁴ core-h | ~6×10⁴ core-h |
| Richards, GPU/JAX (est., ±3×) | ~20 GPU-h | ~80 GPU-h |
| Store model, NumPy (measured) | **~6 core-h** | **~24 core-h** |

**Per daily cycle (N=100):**
- Serial Richards: ~2,500 core-h on the twin grid, about 2,500 cores to finish in 1 h.
- Compiled Richards: ~40 core-h.
- Store model: ~1 min.

**Multipliers** (any of these turns cost into a hard constraint):
- Spin-up of 3–10 years per member, because regolith stores have time constants of months to years.
- Calibration at 10²–10³ runs.
- State memory. A Richards ensemble state is 2.96 M × 100 × 38 × 8 B ≈ 90 GB per snapshot, versus ≈7 GB for six stores in float32.

With the store model, the LETKF analysis and I/O dominate the cost, not the model.

**The oracle is cheap:**
- ~1,500 sensor columns × 100 members × 365 days × 0.03 s ≈ 450 core-h/yr, even in serial Python.
- An HRU library (~10³ classes × 20 yr × 10 parameter draws) ≈ 1,200 core-h serial.

Conclusion: cost does not decide against Richards everywhere (compiled or GPU code makes it feasible). Physics and identifiability do. A 38–52-layer state per cell, with placeholder parameters, no lateral flow and bounded, regime-switching (saturated/unsaturated) non-Gaussian variables, gives an EnKF a much larger, worse-conditioned state without adding information the observations can constrain.

## Recommended architecture

1. **Static tier.** Build a 90 m CZ medium over the twin with `cz.medium`, using a regional rock end-member (or W=1 above a regolith-depth prior plus Ingebritsen–Manning below). Derive the store capacities from it:
   - root: θ_fc to θ_wp over SOLUS depth;
   - vadose: integral of θ_s − θ(h) to the water-table prior;
   - Sy: drainable porosity from vG.

   This retires Sy = 0.30 as a fudge (water_budget.py:62; #137).
2. **Oracle tier.** A fixed Richards solver (S_s storage, Feddes ET, snowmelt input from the twin's snow model, deep free-drainage bottom plus a Dupuit lateral sink K sinβ h/L, multi-year spin-up), run:
   - (i) at every assimilated sensor site, as the depth operator from storage to θ(z), u(z), σ′(z) and Vs(z), shared by dv/v (#198) and FoS (#128);
   - (ii) on an HRU library (soil vG class × regolith-depth class × slope × HAND × cover × elevation band; ~10³ occupied classes).

   Benchmark it against analytic infiltration solutions and openRE or Hydrus before trusting it.
3. **Cycling tier.** The #187 state [SWE, canopy, S_root, S_vadose/transit, S_gw, S_interflow] per 90 m cell. Calibrate per-HRU transfer parameters against oracle fluxes: recharge lag (#131), storage–discharge (#174/#175), ET partition. Then regionalise against gauges and wells, with held-out basins. The ensemble costs at most 10² core-h/yr.
4. **Lateral flow.** Hillslope drainage time τ ≈ n_e L/(K sinβ), with L = 100–300 m, K = 10⁻⁵–10⁻⁴ m/s, sinβ ≈ 0.2 (median slope 13.3°) and n_e = 0.1–0.2. That gives τ ≈ 6–350 days: event to seasonal. So:
   - A lateral store and sink are mandatory in every steep cell from day one.
   - Explicit 2D Dupuit groundwater (for example Landlab GroundwaterDupuitPercolator, µs per cell-step) is needed wherever convergence matters: valley water tables, hillslope pore pressure for FoS (#133).
   - 3D ParFlow stays at pilot scale as the lateral oracle. A 79 km² basin is ≈ 9,750 columns × 40 layers.

## Pilots

| | Rainier box | Rain-dominated lowland gauged basin (e.g., Newaukum Cr 12108500, 79 km², in twin; Clarks Cr 12102078, 70 km²) |
|---|---|---|
| Proves | **Hydromechanics.** CZ columns, DAS, nodes, permanent stations, 1,650 mass movements (351 dated Jan 2009), GNSS | **Budget closure.** No ice, little snow, a gauge, dense discrete wells (881 USGS sites in a box around Newaukum), gentler slopes where 1D plus groundwater is defensible, a ParFlow benchmark feasible |
| Weaknesses | Ice (97 km², 5.5 km³) and snow. 97.5% of wells are below 600 m (5,449/5,591, paper:999-1000), all single static levels. Edifice masked. No aquifer maps. Regolith 2–50 m unconstrained. Nodes and DAS were not recording in Dec 2025 (34_cz_storm.py:115-116). All dv/v is synthetic. **16.5% (~864 km²) of the box lies outside the twin grid** (south of ~46.6° N; probe with pyproj) | No soil-moisture probes in the twin and 0 continuous USGS wells. Few seismic or DAS sites (not verified). Possible Osceola lahar-cap confound (and opportunity) on the Enumclaw plateau (unverified) |

No single pilot does both. Run the lowland closure pilot first: it calibrates the store and HRU transfer against the Richards oracle and a ParFlow benchmark. Then the Rainier hydromechanics pilot on the in-grid sub-box (lower Nisqually/Paradise corridor and Carbon/Puyallup foothills), at the station and DAS sites, reusing the same stores and oracle. A foothill rain–snow basin that has a gauge, wells and seismic stations could partly bridge the two; it was not identified here.

## Issues #223–#228 versus the CZ module (6ad0fe7)

1. The leverage review is stale. Its claims that rainier3d "rock physics uses hydrostatic pressure and has no saturation term" and has "no soil moisture, groundwater state, dv/v" are now false: medium.py:86-125 and the S33/S34 synthetics show otherwise. It also says the box "sits inside the twin domain", which is false (16.5% is outside).
2. **#223** omits the most valuable new assets:
   - the `/cz` node (layer bases, porosity, log10 k, vG, W, saturation, σ′);
   - the S31 wells and boreholes;
   - S35.

   No release contains `/cz`: products-v1.0.0 predates it, and only viewer-data pre-releases carry it. The release policy after v1.0.0 drops resampled third-party fields (products.md:13-14). `/cz` sits on 250 m L1 columns (04_properties.py:39), not 100 m as critical_zone.md:69 says. The adapter should vendor `cz.medium` and recompute at 90 m rather than upsample. Its ice-volume check (2% of 5.50 km³) has to be done on the twin-grid intersection.
3. **#224** should benchmark the twin's bucket against the S34 Richards columns under the same MRMS forcing. Its caveat "14.6 m failure depth below the 2 m SOLUS cap" is now addressable with CZ columns to 150 m. storms-dec2025-v1 holds only domain-mean `rain.csv` plus the viewer bundle; gridded hourly QPE still needs `s29`.
4. **#225** points to `docs/storage-conservation-contract.md` and `tests/test_water_budget_conservation.py`, neither of which exists on main. The S1a/S1b branch is not on origin.
5. **#228** (epic) is excluded from GAIA batches entirely, so R6a–R6e never run unless they are split into issues. rainier3d's rock permeability has no alteration term (medium.py:159-163). R6a would be new in both repos.
6. **GAIA ordering is broken for this set.** `BLOCKED_BY` is hard-coded and has no entries for 223–228 (gaia_group_issues.py:86-103). The simulated queue dispatches:
   - #227 and #225 in batch 6;
   - #226 in batch 9, while #187 and #189 are held;
   - #223 only in batch 15;
   - #224 in batch 20.

   All of these contradict the "Blocked by" lines in the issue bodies and the rule that none goes ahead of #187/#198/#189→#188.
7. **Missing issues:** the Richards-oracle port and fix; the 90 m CZ static build; the HRU library and store-emulator calibration; pilot selection (needs-human-decision); a compute plan and gates; a link from #198 to rainier3d's σ′/kernel chain.

## Uncertainties

- GPU and compiled timings are estimates (no Numba or JAX was installed in the probe environment). The iterations per day come from one synthetic loam-over-drift column.
- 12 M cells assumes a ~100,000 km² bounding box. Land-only western WA is closer to ~8 M.
- The link between the Ss defect and the 8 S34 failures is a hypothesis.
- Newaukum's geology and its sensor inventory need checking.


## Claims (with adversarial verdict)

- **scale-up-from-rainier-1** [major] [partially] rainier3d's Richards solver adds specific storage to the capacity term but not to theta(h), so in saturated cells the modified-Picard iteration acts as a pseudo-time march and does not converge with a free-drainage bottom; it converges only when a fixed-head bottom anchors the saturated zone.
  - evidence: rainier3d src/rainier3d/cz/richards.py:21,36-39,46,68-69. Probe wf/scale: a 30 m column with WT at 10 m and free drainage gives Picard change ~3.5e-3 m per iteration indefinitely, even at dt=0.1 s; run() raises at once because dt starts at its minimum (:111,:121). The fixed-head case converges (mass-balance error 0.007 mm/yr at 30 m, 0.74 mm/yr at 150 m).
  - issues: New issue: port the Richards solver into the twin as an oracle, with a consistent Ss storage term (theta includes Ss*h*theta/theta_s), a robust step-failure policy and analytic benchmarks. Plausible cause of the 8 failed S34 sites; flag it upstream to rainier3d (read-only here).
  - verifier: The mechanism is real. richards.py:46 adds SS to the capacity but theta() (:36-39) stays at theta_s when h>=0, so in saturated cells the rhs at :69 reduces to dz*SS*h_iter/dt and each Picard iteration acts as a pseudo-time step. That part is confirmed. Rerunning p1.py (WT at 10 m inside 30 m, free drainage) fails at dt=0.1 s even with itmax=20000. But it converges at dt=10 s in 633 iterations and at dt=900 s in 17, so 'does not converge' is wrong: it fails at small dt, and run() fails because it starts at dt_min and raises at :121-122. The configuration is also artificial. S34 sets a fixed head whenever the WT lies inside the domain (scripts/34_cz_storm.py:53), so it never builds saturated-zone plus free drainage. The fixed head does not guarantee convergence either. p1b.py: a fixed-head column with WT at 1 m or 3 m fails at the minimum step under 2e-5 m/s rain. The '8 failed S34 sites' (critical_zone.md:210) are therefore more plausibly shallow-WT, saturated-to-surface fixed-head columns, not free drainage. Minor: the mass balance at :114/:133 uses theta without the Ss term.
- **scale-up-from-rainier-2** [major] [confirmed] Serial rainier3d Richards costs about 0.03 s per column-day (96 adaptive steps and 218 Picard iterations per day, 129 us per iteration). That is ~9e3 core-h per member-year on the 2.96 M-cell twin and ~9e5 core-h/yr for N=100.
  - evidence: wf/scale/bench_365.json: 0.0278 s/column-day (38 layers, 30 m) and 0.0306 (52 layers, 150 m) on a 3.0 GHz Xeon W-2150B, synthetic 1,760 mm/yr hourly rain. Arithmetic: 2.96e6*365*0.03/3600.
  - issues: Any issue proposing Richards on every cell (e.g., a future rewrite of #171/#172) must declare compiled/GPU code and a compute budget. Pure-Python Richards cycling is off the table.
  - verifier: Reproduced on the same Xeon W-2150B: 0.0278 s per column-day, 96.06 steps and 218.4 Picard iterations per day, 127 us per iteration. The twin grid is 2.96e6 cells (domain.py:121, 90 m). 2.96e6*365*0.03/3600 is about 9.0e3 core-h per member-year (8.35e3 at the measured rate), and about 9e5 for N=100. Caveats: 96 steps/day means dt sat at the 900 s cap almost all the time. The test was a synthetic, fixed-head, no-ET column. Saturated-to-surface columns that force dt toward 0.1 s would cost far more, so this is a lower bound.
- **scale-up-from-rainier-3** [minor] [not-checked (minor)] A batched NumPy Picard iteration costs 6-12 us per column-iteration (about 10x faster than serial). Compiled CPU is estimated at 1-3 us and GPU/JAX at ~20 GPU-h per year for N=100 on the twin grid, which puts full-grid Richards ensembles in the 1e4-1e5 core-h/yr range.
  - evidence: wf/scale/bench_batched.py: 6.20/11.77/12.20 us at B=1e3/1e4/5e4. The compiled and GPU numbers are flop-count estimates (no numba/jax installed).
  - issues: Compute-plan issue: report cost gates per tier. Richards is feasible at sensor sites and HRUs; full-grid only with GPU and a justified need.
- **scale-up-from-rainier-4** [minor] [not-checked (minor)] The twin's reduced-order store model costs about 0.2 us per cell-day, 4-5 orders of magnitude below Richards. An N=100 year on 2.96 M cells is ~6 core-h, so with stores the EnKF analysis and I/O, not the model, dominate the cycling cost.
  - evidence: Probe calling src/models/water_budget.py coupled_water_budget, daily: 0.160 us (1e5 cells) and 0.232 us (1e6 cells) per cell-day.
  - issues: #188 should budget for the LETKF analysis and ensemble I/O (~7 GB per cycle for 6 float32 stores x 100 members) rather than model integration.
- **scale-up-from-rainier-5** [major] [partially] A 1D vertical Richards column without a lateral sink accumulates storage without bound under PNW rain, so it cannot serve as the cycling forecast model. Lateral drainage (hillslope time n_e L/(K sin beta) ~ 6-350 days) is needed on the steep domain.
  - evidence: Probe: 1 yr with 1,760 mm rain and no ET stored +1,060 mm with 699 mm bottom outflow. S34 reports no runoff for the Dec 2025 flood storm (rainier3d docs/critical_zone.md:210). The twin's valley cells have the same defect (water_budget.py:193-197).
  - issues: #174/#175/#133: mandate a lateral store/sink in every steep cell. New issue for explicit 2D Dupuit groundwater where convergence matters. ParFlow only as a pilot-scale lateral oracle.
  - verifier: 'Without bound' is refuted by the agent's own probe. Rerunning p5.py over 4 years gives storage changes of +1060, +23.5, -36.2 and +75.4 mm, with bottom outflow of 1677-1958 mm/yr matching rain. Year 1 is the wetting of the hydrostatic initial profile, and the fixed-head bottom then acts as an unlimited sink. The twin's valley cells are not unbounded either: gw_recess=0 where HAND<=d0 (water_budget.py:193-197) and f_lat=0 on flat ground, but saturation excess rejects water the column cannot store (:223-236). The valid core is that a 1D column has no lateral redistribution, so its WT dynamics and the partition between drainage and runoff are wrong. The hillslope-timescale range is plausible to an order of magnitude but was not derived from domain parameters.
- **scale-up-from-rainier-6** [major] [confirmed] 16.5% (~864 km2) of the rainier3d box lies outside the twin's 90 m EPSG:5070 grid (south of ~46.6 N). The leverage review's claim that the twin domain contains the Rainier box is false.
  - evidence: pyproj probe: twin bounds (-2005000,2892000,-1864000,3062000) from src/config/domain.py versus rainier3d configs/domain.yaml bounds_utm [553000,5149000,623000,5224000]; 83.5% of 100 m points are inside. Leverage review README 'Its box sits inside the twin domain'.
  - issues: #223: clip explicitly and compute the ice-volume acceptance (5.50 km3 within 2%) on the intersection. #224: list which of the 15 gauges and S24 events fall outside.
  - verifier: pyproj probe (p6.py) of 100 m points over bounds_utm [553000,5149000,623000,5224000] (EPSG:32610) against DOMAIN bounds_5070 (-2005000,2892000,-1864000,3062000) (domain.py:121): 83.55% inside, 863.6 km2 outside. All the excluded points are south of the y0 edge, at lat 46.48-46.69 N. The leverage review README:19 'Its box sits inside the twin domain' is false.
- **scale-up-from-rainier-7** [major] [partially] Issues #223-#228 were written before the CZ module and miss its most transferable assets: the /cz node (layer bases, porosity, log10 k, vG, W, saturation, effective stress), S31 wells and boreholes, and S35. They also repeat stale statements that rainier3d has no saturation term and no dv/v.
  - evidence: #223 layer list (issues.json). Leverage review row 6 'rock physics uses hydrostatic pressure and has no saturation term'. Contradicted by rainier3d cz/medium.py:86-125, scripts/04_properties.py:38-39, scripts/33/34 (6ad0fe7, 2026-10-03).
  - issues: Edit #223 to add /cz, S31 and S35. Add a note to the leverage review that it is superseded. Edit #224 to use the CZ columns for FoS depth (the 14.6 m failure-depth caveat) and the S34 Richards runs as a bucket benchmark.
  - verifier: Confirmed: the #223 layer list omits /cz, S31 and S35. /cz exists (scripts/04_properties.py:38-39, cz/medium.py:86-125 with Se, suction stress, cumulative overburden, Gassmann-Brie), added in 6ad0fe7 on 2026-10-03, after the review's source commit d827cc3 (2026-09-26). Not supported: the stale statements about no saturation term and no dv/v are in the leverage review (README:17, :43 row 6), not in the bodies of #223-#228. They were also accurate at d827cc3, so they are stale, not wrong.
- **scale-up-from-rainier-8** [major] [confirmed] No rainier3d products release contains the critical-zone /cz node: products-v1.0.0 (2026-09-25) predates it and only viewer-data pre-releases carry it. Releases after v1.0.0 also drop resampled third-party fields.
  - evidence: rainier3d src/rainier3d/products.json (only products-v1.0.0 plus gnss-latest); gh release list (viewer-data-2026-10-05/06 pre-releases mention critical zone); docs/products.md:13-14; configs/products.yaml:9.
  - issues: #223 cannot be done from release assets alone. Either request a products-v1.1 with /cz (cross-repo) or vendor rainier3d.cz.medium (BSD-3) and recompute at 90 m. The second is preferred because /cz is on 250 m L1 columns.
  - verifier: products.json lists only products-v1.0.0 assets (plus gnss-latest). gh release list shows that /cz appears only in the viewer-data-2026-10-05 and -06 pre-releases. docs/products.md:13-14 and configs/products.yaml:1-10 say resampled third-party fields are dropped from the release after v1.0.0 and that /cz is a packaged node. There is no post-v1.0.0 products release yet, so the 'drop' applies to future releases. L1 dx is 250 m (domain.yaml m1 profile). Code license is BSD-3 (LICENSE, pyproject:10) and the twin is MIT, so they are compatible. Missed caveat: recomputing /cz needs the water-table input, which is excluded from the products for licensing reasons.
- **scale-up-from-rainier-9** [minor] [not-checked (minor)] rainier3d's critical-zone columns sit on the 250 m L1 grid, not one per 100 m cell as its design doc states, so resampling /cz to 90 m would invent resolution.
  - evidence: rainier3d scripts/04_properties.py:39 (cz.fine_dataset(geo['L1'])); configs/domain.yaml m1 L1 dx=250; docs/critical_zone.md:69 'One column per 100 m cell'.
  - issues: #223: recompute the CZ medium on twin 90 m inputs instead of upsampling.
- **scale-up-from-rainier-10** [critical] [confirmed] The GAIA grouper's hard-coded BLOCKED_BY has no entries for #223-#228. The simulated queue therefore dispatches #227 and #225 (batch 6) and #226 (batch 9) before their declared blocker #223 (batch 15), and #226 while #187/#189 are held, contradicting the issue bodies.
  - evidence: scripts/gaia_group_issues.py:86-103 and :181; queue_sim.jsonl lines 7, 10, 16, 21 (batches 6, 9, 15, 20); issue bodies of #224-#227 'Blocked by: #223' and #226 'Blocked by: #187 and #189'.
  - issues: Before launch, add 224/225/227 -> [223], 226 -> [187,189,223], 225 -> [S1a/S1b issue], 224 -> [223] (landslide part -> [128]) to BLOCKED_BY, or parse 'Blocked by' lines from issue bodies.
  - verifier: BLOCKED_BY (gaia_group_issues.py:86-103) has no entries for #223-#228. Holdback applies only through BLOCKED_BY (:181). queue_sim.jsonl puts #227 and #225 on line 7 (0-indexed batch 6), #226 on line 10 (batch 9), #223 on line 16 (batch 15) and #224 on line 21 (batch 20). queue_held.txt holds #187 and #189 while #226 is dispatched, contradicting #226's 'Blocked by: #187 (...) and #189'. #128 is open, which also blocks #224's landslide part. #228 is an epic, so it is skipped.
- **scale-up-from-rainier-11** [major] [confirmed] #225 tells agents to close under docs/storage-conservation-contract.md and extend tests/test_water_budget_conservation.py, but neither file exists on origin/main and the S1a/S1b branch is not on origin.
  - evidence: ls on origin/main checkout: both missing. git ls-remote shows no storage-conservation head. Leverage review says S1a/S1b is on work/storage-conservation-2026-09-10, unmerged.
  - issues: Hold #225 (needs-human-decision) or rewrite it against water_budget.py and the existing tests/test_water_budget.py.
  - verifier: Neither docs/storage-conservation-contract.md nor tests/test_water_budget_conservation.py exists in the origin/main checkout. Only tests/test_water_budget.py does. git ls-remote --heads origin (42 heads) and the gh branches API show no storage or conservation branch. The leverage review README:13 places S1a/S1b on the unmerged work/storage-conservation-2026-09-10.
- **scale-up-from-rainier-12** [minor] [not-checked (minor)] #228 is labelled epic, so the GAIA grouper excludes it. Its sub-slices R6a-R6e have no issues of their own and will never be dispatched.
  - evidence: scripts/gaia_group_issues.py:178-179 (epics skipped); #228 labels include 'epic'; queue_sim.jsonl has no #228.
  - issues: Split R6b, R6c and R6d into separate issues (R6a stays needs-human-decision). Note that rainier3d rock permeability has no alteration term (cz/medium.py:159-163), so R6a is new in both repos.
- **scale-up-from-rainier-13** [major] [partially] rainier3d already implements the depth-resolved hydromechanical forward chain #198 asks for (vG Se -> Lu-Godt-Wu suction stress -> sigma' with cumulative overburden -> soft-sand/Hertz-Mindlin -> Gassmann-Brie -> disba Rayleigh dispersion and kernels). The twin uses a constant 10 kPa overburden.
  - evidence: rainier3d cz/medium.py:94-125, cz/rockphysics.py:31-74, cz/synthetics.py:16-45; twin src/models/dvv_coupling.py:48 (SIGMA0=10 kPa), :89 (P_e = SIGMA0 + Se*Pc).
  - issues: Edit #198 to vendor or reuse rainier3d.cz.rockphysics/medium/synthetics (BSD-3 into MIT) as the shared operator and to add overburden-dependent sigma'.
  - verifier: The rainier3d chain exists: rockphysics.py vg_se:56, suction_stress chi=Se:62, hertz_mindlin/soft_sand:31-42, brie:67, gassmann:72; medium.py:96-104 cumulative sig_tot minus u; synthetics.py disba phase_velocity:16 and PhaseSensitivity kernels:31-45. The twin has SIGMA0=10 kPa at dvv_coupling.py:48 and P_e=SIGMA0+Se*Pc at :89. That is confirmed. But #198 already specifies P_e = sigma'_g(z) + chi*Pc, so 'add overburden-dependent sigma'' is not new. rainier3d also lacks the scanning hysteresis that #198 requires and has no inverse or DA path, so it covers only the forward half of what #198 asks for. 'Already implements what #198 asks' overstates it.
- **scale-up-from-rainier-14** [minor] [not-checked (minor)] S34 initialises every storm column from a hydrostatic profile on the static water table, with no spin-up. That dry-biases antecedent moisture, so the 'no runoff' result and the storm dv/v amplitudes are partly initial-condition artefacts.
  - evidence: rainier3d cz/medium.py:86 (h = Z - WT), scripts/34_cz_storm.py:55 (h0 = fine['head']), :84-87; cz.yaml:50-58. Probe: from hydrostatic start a column absorbed ~1 m of storage over a year.
  - issues: #224 and the oracle issue: require multi-month spin-up with ET before scoring storm response.
- **scale-up-from-rainier-15** [minor] [not-checked (minor)] rainier3d's storm dv/v numbers are internally inconsistent: about -2% at 40 Hz at the permanent stations (paper) versus -1.1 to -1.2% median (design doc).
  - evidence: rainier3d docs/paper/rainier3d_paper.md:513 versus docs/critical_zone.md:210.
  - issues: Do not import either number as a prior into twin dv/v issues (#30, #198) until reconciled.
- **scale-up-from-rainier-16** [major] [confirmed] The Rainier box cannot prove budget closure: 97.5% of its 5,591 well levels are below 600 m and all are single static levels; there are no continuous USGS groundwater sites in the box; ice covers 97 km2; snow is not separated from rain; the edifice is masked; and there are no aquifer maps.
  - evidence: rainier3d paper:995-1000 (5,591 wells, 142 at or above 600 m), :972 (ice), :993 (no aquifer maps); USGS site service bBox -122.30,46.50,-121.40,47.15: 0 iv / 1,685 discrete GW sites; critical_zone.md:212.
  - issues: New needs-human-decision pilot issue: the lowland gauged basin (Newaukum 12108500 or Clarks 12102078) for closure, the Rainier in-grid sub-box for hydromechanics.
  - verifier: Paper table (around :1000): 5,591 wells, 142 at or above 600 m (2.5%, so 97.5% below). Static or median levels are one value per well (S31 text). Ice is 97.3 km2 (:972). 'No aquifer maps exist for the park' (:993). critical_zone.md:212: snow not separated from rain. USGS site service rerun on bBox -122.30,46.50,-121.40,47.15: 0 iv, 0 dv, 1,685 discrete GW sites. The 15 S29 gauges do allow basin-scale P-Q-dS checks, so 'cannot prove closure' is a judgment, but a defensible one.
- **scale-up-from-rainier-17** [major] [confirmed] The candidate lowland closure pilots have no soil-moisture probes and no continuous USGS wells in the twin's data. The twin's in-situ soil moisture is 5 montane SNOTEL stations, and anchoring them worsens leave-one-station-out RMSE (0.092 to 0.118).
  - evidence: data/processed/snotel_anchor.json (n_stations 5, loso_rmse_raw 0.092, loso_rmse_anchored 0.118); USGS site service: 0 iv GW sites near Newaukum (881 discrete) and Clarks Cr (446 discrete); src/data/fetch_usgs_discharge.py:49-56.
  - issues: The pilot issue must include sourcing continuous wells (Ecology/King County) and soil probes, or instrumenting. #131's acceptance criterion ('validated against a continuous well hydrograph') cannot be met with current USGS data in these basins.
  - verifier: snotel_anchor.json: n_stations 5, loso_rmse_raw 0.0924, loso_rmse_anchored 0.1176. USGS iv and dv GW queries return 0 in four boxes around 12108500 (47.276,-122.060) and 12102078 (47.201,-122.342). Discrete counts depend on the box drawn. fetch_insitu_sm.py says SNOTEL is the only in-situ SM source in the v0.4 footprint. Readers for USCRN and ISMN exist but contribute no stations here. Ecology and King County continuous wells were not checked. The #131 acceptance criterion cannot be met from USGS alone.
- **scale-up-from-rainier-18** [minor] [not-checked (minor)] rainier3d's Washington Ecology well-report and WGS borehole ingest (S31) is a high-value, statewide transferable input the twin lacks. It yields ~6.5x more water levels in the Rainier box alone than the twin's clean NWIS sites in its whole domain, plus bedrock picks for regolith depth.
  - evidence: rainier3d src/rainier3d/hydromet/wells.py:1-6; paper:995-999 (5,591 levels, 23 bedrock picks); twin data/processed/qc_report.json clean_sites 863; no Ecology/WGS ingest in twin src (grep).
  - issues: New issue: port S31 wells/boreholes to the twin domain as a static water-table and regolith-depth prior and validation set (static levels only, not dynamics).
- **scale-up-from-rainier-19** [major] [partially] The recommended architecture is three tiers: a static 90 m CZ medium giving store capacities; a fixed Richards oracle (with Ss, ET, snowmelt, dynamic bottom and Dupuit sink) at ~1.5k sensor sites (~450 core-h/yr at N=100, serial) and over a ~1e3-class HRU library (~1.2e3 core-h); and reduced-order mass-conserving stores as the cycled EnKF model with HRU parameters calibrated to the oracle.
  - evidence: Cost arithmetic from the measured 0.03 s/column-day and 0.2 us/cell-day. Store state vector as in #187. Capacity gap from water_budget.py:62 (Sy=0.30) and #137/#172.
  - issues: New issues: (1) a 90 m CZ static build via rainier3d.cz.medium; (2) the Richards oracle port and fixes; (3) the HRU library and store-emulator calibration, blocked by #172/#131/#174 design and #187. Link them from #171 and #188.
  - verifier: Some of the arithmetic checks out: 1.5e3 sites*365*0.03 s*100/3600 is about 456 core-h, and Sy=0.30 is at water_budget.py:62. The HRU-library figure of about 1.2e3 core-h cannot be derived: 1e3 HRUs at 0.03 s per column-day is about 3 core-h per year, so the implied number of years or members is unstated. The 0.2 us per cell-day store cost and the count of about 1.5k sensor sites were not shown. The Richards oracle cost assumes the fixed-head benchmark, which claim 1's own findings undermine for shallow or wet columns. The three-tier design is reasonable but remains an opinion, not a verified finding.

## Verifier: missed problems

- Probe p1b shows the Richards step also fails at the minimum dt with a fixed-head bottom when WT is shallow (1-3 m) under intense rain. Together with S34 dt_s=[0.1,900] and picard_max=100 (configs/cz.yaml:54-56), this is the more likely cause of the 8 S34 failures. run() shrinks dt only after failure and never retries with a larger dt (richards.py:120-123), so any oracle port needs a different failure strategy, such as a variable switch or a full Ss in theta.
- A fixed-head bottom at the static Ma et al. water table acts as an unlimited, instantaneous sink and pins the WT. Rainier3d S34 columns therefore cannot produce WT rise, and the dv/v-from-saturation results in critical_zone.md:210 do not include water-table dynamics. Any Richards oracle used for #131/#174 needs a dynamic lower boundary.
- Licensing gap for recomputing /cz at 90 m: the CZ medium's head comes from the Ma et al. (2026) WTD, which is CC-BY-NC-ND, is not redistributed and is excluded from the products (products.json 'excluded: surface/water_table_depth'; paper groundwater row). That data also scores poorly against wells (Spearman 0.27, gridded water table 2.7 m deeper than observed at the median). Vendoring rainier3d.cz.medium into an MIT twin does not solve the input licence.
- #224's caveat 'S24 median failure depth 14.6 m (n=453), below the 2 m SOLUS cap' is garbled: 14.6 m is far deeper than the cap. Physically it means the S24 inventory is dominated by deep-seated failures that an infinite-slope FoS on a 1-2 m soil column cannot represent. Scoring ROC/AUC of #128 against it will measure the wrong mechanism unless the events are stratified by depth.
- Because 16.5% of the Rainier box lies outside the twin grid, which of the 15 S29 NWIS gauges (#224) and the IceBoost glaciers (#223's 5.50 km3 check, #227's 12082500 Nisqually basin) fall in the excluded strip south of 46.6 N needs to be checked. The Nisqually headwaters reach south toward that edge, so the glacier-melt check against 12082500 may need the basin clipped.
- Future rainier3d product releases will not package resampled third-party fields (products.md:13-14). #223's layer list relies on S19 Sentinel-2 LAI and GEDI PAI, so #223 should pin products-v1.0.0 or rebuild those layers from their sources.
