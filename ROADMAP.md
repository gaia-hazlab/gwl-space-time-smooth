# Roadmap — GAIA Digital Twin of Soil

The durable plan. **This file, plus the linked GitHub issues, is the source of truth** — not any
agent's context. If a session loses its memory, start here.

Everything below is measured, not asserted. Where a number appears, it came from data, and the
command that produced it is named.

---

## Where we actually are

| component | status |
|---|---|
| Static layers (terrain, soils, Vs30) at 90 m | **done** — Puget-lowland strip only |
| Vs30 from the SVM (Grant, Wirth & Stone 2025) | **done**, staged as Zarr on Kopah |
| Daily water budget (θ, water table, Vs) | **done** — monthly path preserved bit-for-bit |
| Saturated-area runoff + lateral interflow + river/baseflow sink | **done** — see caveat below |
| Petrophysical coupling (water → Vs, Hertz–Mindlin) | **done** — not a fitted correlation |
| Zarr staging on Kopah (gaia-cli conventions) | **done** |
| Observed forcing (PRISM daily), state (NWIS wells), flux (USGS gauges) | **done**, Fall–Winter 2025-26 |
| FuXi 15-day AI forecast adapter | **written, never run on a GPU** |
| **Water-table magnitude** | **FAILS validation** — see below |

### The one thing that is wrong, stated plainly

The **θ / dv/v half of the twin looks right**; the **water-table half does not**.

| | model | observed |
|---|---|---|
| quickflow (Newaukum Ck) | 328 mm | 278 mm ✓ |
| **baseflow** | **0 mm** | **344 mm** |
| **baseflow index** | **0.00** | **0.55** |
| Nov→Dec water-table rise | **+3.24 m** | **+0.12 m** (median, 1205 paired wells) |

Interflow works. **The river sink discharges nothing** — 438 mm of recharge is retained instead of
returning to the streams. That is the entire remaining error, and it is now *measured per basin*
rather than guessed.

Do not present a water-table forecast until this closes.

---

## The plan, in order

### v0.4 — Domain extension: western Cascades ([milestone](../../milestone/3)) ← **NOW**

**Why:** the gauged basins are not in our modelled domain. Measured overlap with the current static
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

| | issue | note |
|---|---|---|
| D1 | [#92](../../issues/92) Freeze the domain grid | do first; one definition, no drifting bbox copies |
| D2 | [#93](../../issues/93) 3DEP terrain (HAND/slope/TWI/flow-acc) | **long pole**; ~300 M cells at 10 m — must be tiled |
| D3 | [#94](../../issues/94) SOLUS soils + Saxton-Rawls envelope | mountain soils are thin — root depth should stop being a global 1 m |
| D4 | [#95](../../issues/95) Vs30 from the SVM Kopah Zarr | **nearly free** — the Zarr already covers all Cascadia |
| D5 | [#96](../../issues/96) Baseline water table (RF + kriging) | **wells are in the lowlands** — the headwater table will be an *extrapolation*; mask it |
| D6 | [#97](../../issues/97) Acceptance: ≥5 basins fully inside | measure it; the current domain was *assumed* adequate |
| D7 | [#98](../../issues/98) Recalibrate the flux partition | **closes #88 and #90** |

### v0.5 — Eastern Cascades: Stehekin ([milestone](../../milestone/4))

Deliberately separate: **not a bigger bbox, different hydrology.** East of the crest it is
rain-shadowed and **snowmelt-dominated** (spring/summer peak, not the western autumn/winter rain
peak). FuXi's 0.25° grid **cannot resolve the crest**, so orographic downscaling stops being a nicety
and becomes a blocker. Prerequisite: v0.4 calibrated. [#99](../../issues/99)

### v0.3 — Vs30 densification ([milestone](../../milestone/2)) — *paused*

SVM is 200 m native; on the 90 m grid it is an upsample carrying no new information, making Vs30 the
**coarsest static layer** and the binding constraint on liquefaction. Paused by user until the
water-budget work lands. [#81–#86](../../issues/81)

---

## Open physics debts (blocking the water table)

| issue | what | why it matters |
|---|---|---|
| [#87](../../issues/87) | **No unsaturated travel-time lag** | **The dominant control.** With a ~20 m water table, December's recharge *does not arrive in December*. The wells show rain peaking Nov–Dec but the table peaking in **April** — a 4-month lag an instantaneous-recharge model **cannot** produce at any parameter setting. |
| [#88](../../issues/88) | Water table 8–26× too high | Now measured as a *discharge* failure, not a recharge one |
| [#90](../../issues/90) | Model BFI 0.00 vs observed 0.55 | The river sink retains what it should discharge |
| [#89](../../issues/89) | **Daily and monthly drain 4.7× differently** | A monthly calibration is **invalid** for the daily mode we forecast in. This already produced one false "perfect fit". |
| [#57](../../issues/57) | No infiltration-excess runoff | Needs sub-daily rain — and we currently *discard* FuXi's native 6-hourly steps |
| [#91](../../issues/91) | Domain does not cover the gauged basins | superseded by v0.4 |
| [#55](../../issues/55) | Runoff routing → hydrograph | **LandLab's job by design.** We generate the source term; we do not route. |

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

---

## Compute

- **FuXi needs a GPU.** 9.4 GB of weights, 60 six-hourly steps. GraphCast's `jax[cuda13]` will not
  even install on arm64. Run on **Hyak Tillicum (H200)** via SkyPilot: `deploy/tillicum-fuxi.yaml`.
  Slurm nodes **do not autostop** and `time` is a hard kill — size it for the whole init sweep.
- **Kopah** (`s3://gaia/soil-twin/...`) is the staging layer. SkyPilot `file_mounts` **do not work**
  with Kopah's custom endpoint — write with the S3 API.
- The soil physics is pure numpy and runs anywhere. The forecast Zarr is the interface between the
  GPU and the physics; nothing is copied by hand.
