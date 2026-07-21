# Review: sensor uncertainty, covariance, and space-time resolution in the probabilistic twin

**Date:** 2026-07-21
**Scope:** evaluation of the plan to develop a probabilistic digital twin that assimilates
heterogeneous-in-space-and-time observations in the nowcast/forecast, focused on (1) per-sensor
measurement uncertainty, (2) cross-sensor covariance, (3) temporal error, (4) how spatial and temporal
resolution should be exposed as user inputs, and (5) how the soil state is updated from sensors that
report at different times.

This grounds the evaluation in what is actually implemented (`src/models/observability.py`,
`src/models/dvv.py`, `src/models/anchor.py`, `docs/twin/04-assimilation.qmd`,
`docs/twin/01-input-data.qmd`) plus the known gaps recorded in
[`docs/probabilistic-nowcast-forecast-roadmap.md`](../probabilistic-nowcast-forecast-roadmap.md) and
[`ROADMAP.md`](../../ROADMAP.md).

---

## 1) Is sensor error quantified, per measurement, with a distribution?

Partially, and unevenly across sensors — and less consistently than a first pass suggests. Every stream
is declared as an `ObsStream` in `observability.py:238` with a `noise` field (an observation-error
**variance**), but its own docstring (line 230) says this is "in units of the prior variance" — i.e.
these are **design-catalog values for the resolution/observability analysis tool**, not calibrated
physical instrument specs.

| Measurement | Error representation in code | Distribution assumed | Where quantified |
|---|---|---|---|
| NWIS well (GWL) | `qc_nwis.py` assigns **no sigma anywhere** — only descriptive QC stats (`std_wte_m`) and gap flags. Catalog `noise=0.02` in `observability.py:239`. A *different*, hardcoded `WELL_VAR = 0.15**2` (m) appears only in the demo script `notebooks/make_twin_gif.py:49` | Gaussian (implicit in BLUE) | Two independently-invented, mutually inconsistent numbers; neither traced to USGS reading precision or datum uncertainty |
| SNOTEL/SCAN θ | `fetch_snotel.py` does only physical-range QC (0–60) and frozen-soil masking; **no sensor error assigned**. Catalog `noise=0.03`; demo notebook uses a separate `SM_VAR = 0.03**2` | Gaussian | `observability.py:240`; `make_twin_gif.py:52` — not sourced from a probe accuracy spec |
| USCRN θ | Same pattern as SNOTEL — `fetch_uscrn.py` has no error assignment | Gaussian | `observability.py:241` |
| Seismic dv/v | **Structured, ensemble-derived**: Weaver/Clarke coherence bound per configuration + a swept processing ensemble (coda window, reference epoch) combined by the law of total variance into `Cd = temporal_error_covariance(corr_length_days=3.0) + methodological_covariance()` | Gaussian, but genuinely **correlated in time** (not a scalar) | `dvv.py:222–281`; depth-aggregation explicitly avoids a √N shrink because "the depth nodes are prior-correlated" (`dvv.py:332–336`) |
| SMAP (retrieval) | Catalog `noise=0.10`, flagged `is_measurement=False` (a model/retrieval error, not instrument error) — but also flagged **`employed=False`**: no `blue_update` call site anywhere in the repo actually passes SMAP data | Gaussian (stated); real SMAP retrieval error is closer to skewed/lognormal near saturation — not modeled | `observability.py:243`; `fetch_smap.py` has only range QC (0–1), no ubRMSE (~0.04 m³/m³) anywhere |
| USGS gauge (discharge, basin flux) | `fetch_usgs_discharge.py` has **no rating-curve error treatment** at all — Lyne–Hollick baseflow separation has no propagated uncertainty. Catalog `noise=0.05` (basin-integral footprint) | Gaussian | `observability.py:251` — a flat placeholder, not derived from discharge- and stage-dependent rating-curve uncertainty |
| `anchor.residual_anchor` (generic point) | `obs_sigma=0.02` default, physical units, caller-supplied | Gaussian | `anchor.py:20` |

**Verdict.** dv/v is the only stream with a principled, ensemble-derived, temporally-correlated error
model. NWIS, SNOTEL/SCAN, USCRN, SMAP, and USGS discharge have **no uncertainty quantification in their
fetch/QC code at all** — sigma values exist only as small, mutually inconsistent, undocumented
placeholders split across a demo notebook (`make_twin_gif.py`) and a separate observability-design
catalog (`observability.py`). There is no YAML/JSON obs-error schema anywhere in the repo (confirmed: no
config file under `src/config/` besides `domain.py`, which only defines bounding boxes). This is
precisely the gap [#189](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/189) ("operational
observation records, operators, QC, datum age, R blocks") is scoped to close, and non-Gaussian error
(SMAP's bounded/skewed retrieval error, Sentinel's binary wet/dry classification error) is correctly
deferred in `04-assimilation.qmd` to a dynamic-Bayesian-network escalation, gated on a diagnosed
miscalibration rather than built preemptively.

---

## 2) How does cross-sensor covariance show up?

Three mechanisms, at three different levels of maturity:

- **Spatial covariance of the state itself** — a Matérn prior `B` (`observability.py:86`), `nu=1.5`
  chosen deliberately over the smoother squared-exponential because real hydraulic-head fields have
  kinks at drainage divides and lithologic contacts. Terrain-aware masking (`region_id`) zeroes
  correlation across hydrologic-unit boundaries. This is real and is the mechanism by which one sensor's
  information reaches unobserved cells.
- **Within-sensor structured covariance** — only dv/v has this (`dvv.py`'s dense `Cd`, see §1).
- **Cross-sensor observation covariance (off-diagonal `R` between *different* instruments)** —
  **absent, and more precisely absent than a first pass suggests.** `blue_update` and `resolution` both
  build `R` as `np.diag(nv)` (`observability.py:441`, `:397`). Tracing all five call sites of
  `blue_update` in the repo (`make_twin_gif.py:197,213`; `make_checkerboard_test.py:138`;
  `test_observability.py:273,282`) confirms every one passes a scalar or a per-observation **diagonal**
  `noise_var` — none passes a dense matrix. That means dv/v's own carefully-built dense `Cd` (§1) is
  **computed and then never actually reaches the estimator**: the one sensor with genuine structured
  covariance still gets diagonal-`R` treatment in practice. This is a sharper finding than "cross-sensor
  correlation is unmodeled" — it is a working covariance model that is built and then discarded before
  the update.

Practical consequence: co-located sensors sharing a bias (a well and a SNOTEL probe responding to the
same storm; two SMAP pixels sharing a retrieval-model bias) are currently treated as independent
evidence, which **overstates posterior confidence** — the more dangerous failure mode for a hazard
product, since it understates uncertainty exactly where sensors cluster. The roadmap already names this
("Observation error is diagonal in `blue_update`, even though dv/v and retrieval errors can be
correlated") and assigns it to [#187](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/187)/
[#192](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/192); it is correctly triaged, not an
oversight nobody noticed.

---

## 3) What is the temporal error, and how is it handled?

This is the strongest part of the design. Each state is modeled as a stationary Ornstein–Uhlenbeck
process with its own correlation time `τ` (`TEMPORAL_TAU_DAYS = {"soil_moisture": 5.0, "gwl": 120.0}`,
`observability.py:138`), and a lagged datum enters the estimator on two axes derived from that model
(`lagged_observation`, `observability.py:183`):

- the operator gain **shrinks** to `ρ·g` with `ρ = exp(−Δt/τ)` — a stale reading is *weak* evidence about
  the current state, not full-strength evidence merely carrying more noise;
- the effective noise **grows** by a drift term `σ_m²(1−ρ²)` — uncertainty accrued while the state
  evolved, unobserved, over `Δt`.

The code's own docstring records a prior, wrong version of this treatment (inflate `σ²` by
`1/exp(−Δt/2τ)`, leave gain at unit, borrowing a factor of 2 from the unrelated spatial
squared-exponential kernel) and documents the fix in place rather than silently overwriting it — a good
sign for the project's rigor. The one real limitation: `τ` is a **single scalar per state, everywhere
and always**. Recession behaves differently wet vs. dry, and recharge is threshold-like; `04-assimilation.qmd`
itself names this as the first trigger condition for a regime-switching model, with a concrete diagnostic
(check whether the innovation sequence `d − Gm_b` is heteroscedastic conditioned on wet/dry state). That
is the right way to gate the added complexity — build it when the diagnostic fires, not preemptively.

---

## 4) Proposed user-input design for spatial and temporal resolution

The twin already has the primitives to make this a real dial rather than a cosmetic one, because
resolution is *computed*, not assumed.

**Spatial resolution.** Do not let the user request "give me 90 m" as a data-generation setting — native
resolution is capped by the coarsest input that matters for the state in question (SOLUS 100 m, SMAP
9 km, dv/v coda-kernel width). What the user should set is a **query resolution**, honored against the
existing `resolution()`/`information_gain()` machinery: request a grid, and the twin returns, per cell,
both the value and the fraction of prior variance actually removed there (`R(x)`) — so a 90 m raster over
the volcanic uplands (44% outside the applicability domain per `ROADMAP.md`) comes back explicitly
flagged as prior-reversion, not a falsely confident 90 m answer. This generalizes the existing
"confidence mask, not fixed radius" principle from `04-assimilation.qmd` into a first-class output.

**Temporal resolution.** Symmetric logic via `temporal_resolution(revisit_days, τ)`: requesting daily
nowcast values for soil moisture (τ≈5 d) is well-posed; the same daily granularity for GWL (τ≈120 d) is
cosmetic precision the sensors cannot back. I'd expose two linked controls, not one:

1. the state(s) of interest (GWL / soil moisture / dv/v-derived mechanical state — each has a different
   `τ`), and
2. desired update cadence —

and have the twin echo back `temporal_resolution()` and `effective_observability()` for the actual
instrument mix at the requested cadence, so the user sees, e.g., "at daily cadence, dv/v/probes carry
this, SMAP aliases the storm" instead of a falsely uniform-looking raster.

**Gap.** Neither control currently drives an actual re-solve at query time — `resolution()`/
`blue_update()` are analysis tools today, not yet wired to a request API. That is implementation work,
not a design flaw; the math the API would call already exists.

---

## 5) How is the soil state updated when sensors report at different times?

Answered directly by `lagged_observation` + `blue_update`, and it is the same machinery as §3: every
observation — continuous seismic, 15-minute gauge, hourly probe, 2–3 day SMAP, 12-day NISAR — enters the
*same* analysis at the *same* instant, each with its own `Δt` since last valid reading, producing its own
`(ρ·g, effective noise)` pair. There is no separate multi-rate scheduler; heterogeneity in reporting time
collapses into heterogeneity in `Δt` per row of `G`/`R`, solved once.

`04-assimilation.qmd` is explicit that this is currently an **approximation** to true sequential
filtering (a chained forecast → analysis → forecast Kalman recursion) rather than the recursion itself:
Rung-2 TFN dynamics is written as the linear forecast step and `blue_update` as the analysis step, but
they are not yet chained in production. That chaining, plus the EnKF generalization needed once the
nonlinear ParFlow-ML Rung-3 emulator enters the loop, is exactly what
[#188](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/188)/
[#191](https://github.com/gaia-hazlab/gwl-space-time-smooth/issues/191) are scoped to build.

---

## Overall assessment

The theoretical scaffolding — observation operators by native support, OU-based temporal discounting,
Matérn terrain-aware spatial covariance, dv/v's genuine processing-ensemble covariance — is more
sophisticated than most operational hydrologic DA systems at this maturity, and the project's own
documents (`04-assimilation.qmd`, the roadmap) are honest about which pieces remain placeholders.
Nothing in this review contradicts that self-assessment; it sharpens it in two ways:

1. **The per-sensor sigma problem is not "missing," it is "inconsistent."** Two independently-invented
   placeholder values exist per sensor (one in `observability.py`'s design catalog, one in
   `make_twin_gif.py`'s demo constants), neither traced to a real instrument spec (USGS reading
   precision, SNOTEL/USCRN probe accuracy, SMAP's published ubRMSE, USGS rating-curve error). Fix:
   source one physical, documented sigma per sensor and retire the duplicate constants.
2. **dv/v's covariance is built but orphaned.** The one sensor with a genuinely structured, temporally
   correlated error model (`dvv.py`'s `Cd`) is never actually passed into `blue_update`'s `noise_var`
   argument at any of its five call sites — every call uses a diagonal instead. Fix: wire the already-
   computed `Cd` through to the estimator before trusting any posterior variance that involves dv/v.

Priority order before calling this pipeline "probabilistic-nowcast-ready": (1) wire dv/v's existing dense
`Cd` into `blue_update`, (2) reconcile the mismatched placeholder sigmas into one sourced, physical-units
error config, (3) chain forecast → analysis → forecast into an actual recursive filter, (4) extend the
per-state scalar `τ` to a regime-switching form only if/when the innovation-heteroscedasticity diagnostic
fires.
