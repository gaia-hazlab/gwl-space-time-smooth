# Roadmap — GAIA Digital Twin of Soil

The durable plan. **This file, plus the linked GitHub issues, is the source of truth** — not any
agent's context. If a session loses its memory, start here.

Everything below is measured, not asserted. Where a number appears, it came from data, and the
command that produced it is named.

---

## Where we actually are

| component | status |
|---|---|
| Static layers (terrain, soils, Vs30) at 90 m | **done** — **western Cascades**, 2.96 M cells (v0.4) |
| Vs30 from the SVM (Grant, Wirth & Stone 2025) | **done**, staged as Zarr on Kopah |
| Daily water budget (θ, water table, Vs) | **done** — monthly path preserved bit-for-bit |
| Saturated-area runoff + lateral interflow + river/baseflow sink | **done** — see caveat below |
| Petrophysical coupling (water → Vs, Hertz–Mindlin) | **done** — not a fitted correlation |
| Zarr staging on Kopah (gaia-cli conventions) | **done** |
| Observed forcing (PRISM daily), state (NWIS wells), flux (USGS gauges) | **done**, Fall–Winter 2025-26 |
| FuXi 15-day AI forecast adapter | **written, never run on a GPU** |
| Snow module (degree-day) | **done** — calibrated against 30 SNOTEL SWE stations |
| **Water-table magnitude + phase** | **PASSES** — see below |

### The water budget now closes against the observations

v0.4 fixed it. The model is calibrated in **daily** mode against **gauges** (fluxes) and **wells**
(state), with the snow clock on:

| | model | observed |
|---|---|---|
| **baseflow index** | **0.52** | 0.47 (Lyne–Hollick, 6 gauges) |
| **runoff coefficient Q/P** | **0.71** | 0.57–0.73 (per-basin closure) |
| **seasonal amplitude** | **1.02 m** | 1.06 m (26,816 shallow-well obs) |
| water-table peak month | 5 | 4 |
| *before v0.4* | *BFI 0.00, Q/P 0.96, Nov→Dec rise **+3.24 m*** | *(obs +0.12 m)* |

Each parameter is pinned by a **different** observation — `S_y` ← amplitude, `k_aniso` ← Q/P,
`recharge_ref` ← BFI — so it is a constrained fit, not curve-fitting.

**Two of the "errors" were mine, not the model's**, and both are worth remembering:

1. **"Model BFI = 0.00" was largely an accounting artefact.** `WaterBudget` recorded recharge, runoff
   and interflow but had **no baseflow field**: the river sink removed head and the flux was never
   *recorded*. Scored properly, the *uncalibrated* model already had BFI 0.22.
2. **The first calibration objective omitted the amplitude**, so `specific_yield` was unconstrained,
   drifted to the grid edge, and gave a 5.4 m seasonal swing. Fluxes right, storage wrong.

**Honest residuals:** the fitted `Ka = 2` is *below* the 10–100 literature range for forest-soil
anisotropy (flagged in code). And the peak is one month **late** — note the direction: an unsaturated
travel-time lag (#87) would make it **worse**, which independently confirms #87 was correctly demoted.

---

## The plan, in order

### v0.4 — Domain extension: western Cascades ([milestone](../../milestone/3)) — **DONE**

**Why (two reasons, both measured):**

**(a) The recharge clock is snowmelt, and we have no snow.** Snowmelt release peaks in **April**; the
observed water table peaks in **April**. The current lowland domain is rain-dominated, so the snow
module never fires and the model cannot produce the observed phase at *any* parameter setting. Putting
the Cascades in the domain is the fix ([#100](../../issues/100)).

**(b) The gauged basins are not in our modelled domain.** Measured overlap with the current static
footprint:

| Nisqually | Puyallup | Green | Skykomish | Cedar | Snoqualmie | **Newaukum Ck** |
|---|---|---|---|---|---|---|
| 0% | 0% | 0% | 0% | 1.8% | 17.3% | **100%** |

Exactly **one** gauged basin (79 km²) is inside. And it is a *lowland* creek — while interflow
(`f_lat = Ka·tanβ/(1+Ka·tanβ)`) is **most active on steep ground**. So the only basin we can model is
the one least able to constrain the parameter that matters. Calibrating there would be self-deception.

**Target grid:** bbox `-123.0, 46.6, -121.0, 48.2` (EPSG:4326) → EPSG:5070, 90 m,
≈1670 × 1980 = **~3.3 M cells** (2.8–3.6× current). Covers the **Puyallup and Nisqually headwaters
(Mt Rainier)**, Green, Cedar, Snoqualmie, Skykomish.

| | issue | outcome |
|---|---|---|
| D1 | [#92](../../issues/92) Freeze the grid | ✅ 1567×1890 = **2.96 M cells**. Defined in **EPSG:5070, not lat/lon** — Albers is conic, and defining it in lat/lon inflated the grid to 5.1 M and failed to round-trip the legacy one. 7 drifting bbox copies converged. `assert_on_grid()` **raises** on legacy products. |
| D2 | [#93](../../issues/93) 3DEP terrain | ✅ **Download tiled; routing global** (flow crosses seams). Old HAND was a Python double loop (~1e11 ops here) → **pointer doubling, 831× faster**, r=0.9996. Slope median 2.6° → **13.3°**. |
| D3 | [#94](../../issues/94) SOLUS soils | ✅ Old source **dead**; moved to the authoritative NRCS release. **Root depth is no longer a global 1 m** (steep 1.05 m, flat 1.49 m). Real organic matter, not a 2.5% constant. |
| D4 | [#95](../../issues/95) Vs30 | ✅ 3.7 s from the Kopah Zarr. Surface-referencing **verified over high relief**. Valley 378 → ridge 528 m/s. |
| D5 | [#96](../../issues/96) Baseline water table | ✅ **The RF would have put a 75 m water table on Cascade ridges.** Applicability-domain mask (covariate space, not distance) flags 44% of the domain; TOPMODEL prior blended in where wells cannot speak. |
| D6 | [#97](../../issues/97) Basin coverage | ✅ **All 8 gauged basins 100% inside** (was 1) — met at D1. |
| D8 | [#100](../../issues/100) Snow clock | ✅ Calibrated on **30 SNOTEL SWE stations**. Objective had to be **melt-out timing, not RMSE** — RMSE picked a melt factor so slow the pack lingered to June and pushed melt to May. |
| D7 | [#98](../../issues/98) Flux calibration | ✅ **Closes #88 and #90.** BFI 0.52/0.47, Q/P 0.71, amplitude 1.02/1.06 m. |

### v0.5 — Eastern Cascades: Stehekin ([milestone](../../milestone/4)) ← **NEXT**

Deliberately separate: **not a bigger bbox, different hydrology.** East of the crest it is
rain-shadowed and **snowmelt-dominated** (spring/summer peak, not the western autumn/winter rain
peak). FuXi's 0.25° grid **cannot resolve the crest**, so orographic downscaling stops being a nicety
and becomes a blocker. Prerequisite: v0.4 calibrated. [#99](../../issues/99)

### v0.3 — Vs30 densification ([milestone](../../milestone/2)) — *paused*

SVM is 200 m native; on the 90 m grid it is an upsample carrying no new information, making Vs30 the
**coarsest static layer** and the binding constraint on liquefaction. Paused by user until the
water-budget work lands. [#81–#86](../../issues/81)

### v0.6 — Memory & disturbance ([milestone](../../milestone/5)) ← **STARTED**

The soil state is **memoryless exactly where the interesting physics lives.** Two processes are absent:
**(1) capillary hysteresis** — the retention curve is single-valued, so drying and wetting are
reciprocal when they are not (the source of soil-moisture memory, [Shi et al. 2026 *Science*,
agroseismology](https://doi.org/10.1126/science.aec0970) — the Denolle-lab DAS paper); **(2)
landscape disturbance** — earthquakes/liquefaction, landslides, wildfire, and **farming (tillage)**
alter the hydromechanical response over weeks-to-years, and today they appear only as downstream
hazard *consumers*, never as inputs that perturb the soil state. **dv/v is the shared observable**, so
the real problem is **attribution** across three timescales.

| issue | what |
|---|---|
| [#119](../../issues/119) | **[epic]** Soil-state memory and landscape disturbance |
| [#120](../../issues/120) | Capillary hysteresis (Kool–Parker scanning curves) — [doi:10.1029/WR023i001p00105](https://doi.org/10.1029/WR023i001p00105) |
| [#121](../../issues/121) | Coseismic damage + **log-linear healing** dv/v state — [Illien 2025](https://doi.org/10.1038/s41467-025-57151-8), [Wang 2021](https://doi.org/10.1038/s41467-021-21418-7) |
| [#122](../../issues/122) | Surface disturbance: wildfire / **agricultural** / landslide |
| [#123](../../issues/123) | dv/v **attribution** — augment the BLUE (generalize [Illien 2022](https://doi.org/10.1029/2021JB023402)) |
| [#124](../../issues/124) | Disturbance event catalog on the data plane (ShakeMap, MTBS, landslide, liquefaction) |
| [#125](../../issues/125) | Report chapter: Memory & disturbance |

**Multi-scale principle:** each process is a state variable with its **own relaxation timescale**
(operator-split); disturbances are **patchy fields at native scale** reprojected through the existing
forward-operator data plane. The timescale + footprint separation is what makes attribution possible.

---

## Open physics debts (blocking the water table)

| issue | what | status |
|---|---|---|
| ~~#88 / #90~~ | Water table 8–26× too high; BFI 0.00 | ✅ **CLOSED by D7.** BFI 0.52 vs 0.47; amplitude 1.02 vs 1.06 m. |
| [#87](../../issues/87) | Unsaturated travel-time lag | **DEMOTED, and now doubly so.** I first blamed the 4-month lag on vadose transit; it is **snowmelt**. And the calibrated model peaks one month **late**, so a vadose lag would make it *worse*. |
| [#89](../../issues/89) | **Daily and monthly drain 4.7× differently** | Open. A monthly calibration is **invalid** for the daily mode we forecast in — it already produced one false "perfect fit". D7 was done in daily mode. |
| [#57](../../issues/57) | No infiltration-excess runoff | Open. Needs sub-daily rain — and we still *discard* FuXi's native 6-hourly steps. |
| [#55](../../issues/55) | Runoff routing → hydrograph | **LandLab's job by design.** We generate the source term; we do not route. |
| ~~#91~~ | Domain misses the gauged basins | ✅ superseded by v0.4 |

---

## Traps this project has already hit (do not re-learn these)

1. **`GraphCastOperational` emits `tp06` as literal zeros.** It does not predict rain at all. It is
   also the obvious pick (0.25°, "operational"). Selecting it silently forecasts a **drought** with no
   error raised. `assert_precipitation_is_real()` refuses it by name. **Use FuXi.**
2. **Silent fallbacks lie.** A staged-but-broken SVM netCDF once shipped a Wald-Allen slope proxy
   *labelled as SVM*. Staged-but-broken must now **fail loudly**; not-staged may fall back.
3. **Monthly ≠ daily.** The rate parameters are per-month; driving them with mm/day drains the column
   ~30× too fast, and the legacy `drain_frac=0.6/month` implies an unphysical ~33-day drainage
   timescale.
4. **Wells are not a random sample.** They sit in valleys. Compare the model *at the well locations*,
   never the domain mean.
5. **Q > P is not a mass violation** — it means you averaged precipitation over the wrong area.
6. **A perfect fit can be right for the wrong reason.** The monthly calibration reproduced the well
   seasonal cycle *exactly* by under-draining, compensating for missing physics.
7. **Do not attribute a lag to diffusion before checking the reservoir.** The 4-month rain→water-table
   lag was blamed on unsaturated travel time; it is **snowmelt**. Always ask *what is storing the
   water* before inventing a transport delay.
8. **Check that the flux is even RECORDED before calling it zero.** "Model BFI = 0.00" was largely an
   accounting artefact: the river sink removed head but the flux was never written to an output field.
9. **A calibration objective must contain every quantity whose parameter you claim to constrain.**
   Omitting the water-table amplitude left `specific_yield` free; it drifted to the grid edge and gave
   a 5.4 m seasonal swing with the fluxes still looking right.
10. **A domain mean can erase the physics.** Driving the budget with the domain-mean temperature formed
    **no snow at all** — the mean of a cold mountain and a warm lowland is ~7 °C. The elevation
    dependence *is* the mechanism.
11. **Fit the quantity the physics needs, not the convenient one.** Calibrating snow on SWE *RMSE*
    (dominated by accumulation) chose a melt factor so slow the pack lingered into June. Fitting
    **melt-out timing** recovered the April peak.

---

## Compute

- **FuXi needs a GPU.** 9.4 GB of weights, 60 six-hourly steps. GraphCast's `jax[cuda13]` will not
  even install on arm64. Run on **Hyak Tillicum (H200)** via SkyPilot: `deploy/tillicum-fuxi.yaml`.
  Slurm nodes **do not autostop** and `time` is a hard kill — size it for the whole init sweep.
- **Kopah** (`s3://gaia/soil-twin/...`) is the staging layer. SkyPilot `file_mounts` **do not work**
  with Kopah's custom endpoint — write with the S3 API.
- The soil physics is pure numpy and runs anywhere. The forecast Zarr is the interface between the
  GPU and the physics; nothing is copied by hand.
