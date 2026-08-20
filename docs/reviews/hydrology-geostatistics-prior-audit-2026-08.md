# Hydrologic state definitions and spatial priors — audit, 2026-08-18

**Scope.** A scientific review of *what the twin's hydrologic states are*, *what its wells measure*,
and *what its spatial prior is a prior on* — reconciling the mathematics, the observation operators,
the covariance assumptions, the downstream hazard semantics, the documentation, the tests, the
bibliography, and the open issue graph.

**Standard applied.** Post-2000 peer-reviewed literature as primary evidence. Pre-2001 references
retained only where they are foundational mathematical or historical citations with no modern
replacement, and never to justify a numerical prior value. Every reference used here resolves, and its
title/authors/year/journal match its DOI metadata (§6).

**Reviewer stance.** Existing issue text was treated as a hypothesis, not as ground truth. Two issues
are found to be directionally right but stated too strongly (#163, #205), one to be right and
underspecified (#189), one to be right and needing a mechanical correction (#127), and one — #187 —
to be simply correct and worth defending against the temptation to replace it.

---

## 1. Executive summary

Five findings drove every change made.

1. **Five physical quantities were carried under three names.** `GWL`, "head", and `WTD`/`DTW` were
   used interchangeably for groundwater storage, water-table head, depth to water, screened-aquifer
   hydraulic head, and pore pressure. They are now defined once, in `src/models/hydro_state.py`, and
   the definitions propagate into the prior configuration, the observation semantics, and the hazard
   chapters.

2. **WTD anomaly and water-table-head anomaly are one random field, not two.** Since $z_s$ is
   time-invariant, $\Delta D = -\Delta h_{wt}$ exactly, so
   $\mathrm{Cov}(\Delta D) = \mathrm{Cov}(\Delta h_{wt})$. There is no separate $(\sigma, L, \nu)$ to
   fit for WTD. The prior registry deliberately contains **one** groundwater entry, and a guard
   function plus tests refuse two.

3. **The Matérn prior belongs on the residual, and the docs implied otherwise.** Absolute DTW is
   $D = z_s - h_{wt}$ and inherits the whole deterministic landscape; it is not a stationary Gaussian
   field over Puget Sound. The prior is now explicitly on $\delta h$ about the baseline, per the
   drift-plus-residual construction standard in modern groundwater geostatistics
   (Varouchakis et al. 2019, 2022).

4. **Four specific mathematical/statistical claims were wrong or overstated** and are corrected: the
   $\nu = 1/2$ exponential form, the microergodic parameter's convention-dependence, the blanket SPDE
   integer-$\nu$ claim, and the status of $\nu = 3/2$ as "physically established" for groundwater (it
   is a working hypothesis) and as appropriate for soil moisture (it is not — it was inherited from a
   shared default).

5. **Not every NWIS well observes the water table.** A well level is the hydraulic head of its
   *screened interval*. An explicit `measurement_target ∈ {water_table, aquifer_head, unknown}`
   semantic now gates the shallow point operator, and `unknown` is flagged rather than promoted.

**No production numerical value was changed.** $\nu$, $\sigma$, $L$ and the temporal $\tau$s are all
still what they were; what changed is that they are now separately configurable per state, explicitly
labelled by calibration status, and pointed at an experiment that would replace them.

---

## 2. The state definitions adopted

| symbol | quantity | status in the code |
|---|---|---|
| $z_s(x)$ | land-surface elevation | static input (3DEP DEM) |
| $S(x,t)$ | groundwater storage per unit area | **target** canonical evolving state (#187) — not implemented |
| $h_{wt}(x,t)$ | water-table head (phreatic surface, unconfined) | diagnosed; `water_table_head_from_storage` |
| $D(x,t) = z_s - h_{wt}$ | depth to water table (DTW/WTD) | what `gwl_dynamic.py` and `landlab_export.py` carry; first-class hazard product |
| $H(x,z,t) = z + p/(\rho_w g)$ | hydraulic head of a screened interval | what a well actually measures; no state carries it yet |
| $u(x,z,t)$ | pore-water pressure | what slope stability consumes; `pore_pressure_*` helpers, no consumer yet (#128) |

### 2.1 The invariant

$$\Delta D = -\Delta h_{wt}, \qquad \mathrm{Cov}(\Delta D(x),\Delta D(x')) = \mathrm{Cov}(\Delta h_{wt}(x),\Delta h_{wt}(x')).$$

Enforced by `assert_anomaly_covariance_identity()` and four tests. This is why `PRIOR_HYPERPARAMETERS`
has one groundwater key and a test asserts no `wtd`/`dtw` key exists.

### 2.2 Storage-first is the target; a head anomaly is what runs

**#187 is correct and is kept.** The cycling forecast state should be storage-based, with head, DTW and
pore pressure diagnosed. This audit does **not** propose an independently evolving head field.

But the documentation must not pretend the target is implemented. The honest statement, now written
into `04-assimilation.qmd`:

- **current reduced assimilation variable:** water-table-head anomaly (equivalently, up to sign, the
  DTW anomaly `gwl_dynamic.py` kriges) in a *snapshot* BLUE;
- **target cycling state:** storage, with head → DTW → pore pressure diagnosed from it.

`water_table_head_from_storage()` implements the first diagnostic arrow with an explicit $S_y$ and
first-order propagation of $\sigma_{S_y}$ into the diagnosed head (relative error in head = relative
error in $S_y$), and refuses a *confined storativity*, which would inflate the "water table" by three
to five orders of magnitude. The parameter itself remains #137/#171/#172 work — and note that today's
`SPECIFIC_YIELD = 0.30` sits at the top of the plausible range, which #137 already flags.

### 2.3 WTD stays a first-class product; pore pressure is the landslide variable

- **Liquefaction:** WTD is a genuine predictor, not a proxy. Zhu, Baise & Thompson (2017) take modeled
  water-table depth as an explicit input to the updated global geospatial liquefaction model. The
  **seasonal-high** DTW is the relevant epoch. #139/#141/#142 are correct as written; #142 gains a
  calibration constraint (§5).
- **Landslides:** the mechanically relevant variable is pore pressure / effective stress at the failure
  surface (Bogaard & Greco 2016). DTW converts to it only under a *named* assumption — hydrostatic, or
  slope-parallel with its $\cos^2\beta$ reduction — and neither holds during transient infiltration,
  where excess pore pressure can be generated without regional water-table movement (Pelascini et al.
  2022). Hence two separately named functions and deliberately **no** generic
  `pore_pressure_from_head`.
- **#130 is strengthened, not weakened:** shallow perched/transient saturation, the regional phreatic
  table, and deeper confined head are three distinct water bodies, and it is usually the first that
  triggers a shallow failure while the well network mostly samples the second.

---

## 3. Corrections to specific documented claims

Each row was checked in both the prose and the code. "Code was already right" matters: it distinguishes
a documentation error from a modelling error.

| # | Claim as it stood | Verdict | Fix |
|---|---|---|---|
| 1 | $\nu=1/2$ gives $\rho = e^{-\sqrt2\,r/L}$ (`04:152`) | **Wrong.** Under the $\sqrt{2\nu}$ convention $\sqrt{2\nu}=1$ at $\nu=1/2$, so $\rho = e^{-r/L}$ | Prose corrected; `matern_correlation` was **already correct**; a test now pins $\rho_{1/2}=e^{-r/L}$ and rejects the $\sqrt2$ form |
| 2 | $\nu=3/2$ is *physically established* for groundwater | **Overstated.** The log-$K$→head filtering argument is *directional* — it brackets $\nu$ away from $1/2$ and from $C^\infty$; it does not select $3/2$ over $1$ or $2$ | Restated as **"physically plausible central working hypothesis, requiring residual-based calibration"**; `status="working_hypothesis"`; candidates $\{1.0, 1.5, 2.0\}$ with $0.5$ as a rough comparison |
| 3 | The same $\nu=3/2$ is used for soil moisture | **Unsupported.** Vereecken et al. (2014) describe rougher, strongly state/scale/support/depth/season-dependent structure. Minasny & McBratney (2005) find low smoothness for measured **soil properties** — evidence about soil variables, *not* a determination for monthly Puget Sound soil moisture | Decoupled: separate registry entry, `status="inherited_default"`, candidates $\{0.5,1.0,1.5\}$, $0.5$–$1$ as the literature-motivated region. **Value unchanged** so no product moves; changing it is a separate, reported scientific change |
| 4 | $\sigma$ and $L$ are "physical inputs, not fits" (`05:180`) | **Too strong.** They are prior hyperparameters | Reclassified; $L_\text{GWL}=12$ km / $L_\text{SM}=8$ km labelled **provisional**; the *ordering* $L_\text{GWL}>L_\text{SM}$ is the defensible part |
| 5 | Microergodic parameter is $\sigma^2/L^{2\nu}$ | **Convention-dependent**, drops $(2\nu)^\nu$; wrong as soon as $\nu$ varies, and its units depend on $\nu$ so it is not comparable across a $\nu$ profile | Rewritten as $\sigma^2\kappa^{2\nu}$, $\kappa=\sqrt{2\nu}/L$; `microergodic_parameter()` added with a ridge-invariance test |
| 6 | "There is no sparse GMRF precision at $\nu=3/2$" — SPDE cannot represent it | **False as stated.** True of the *classical local* construction (integer $\alpha$); Bolin & Kirchner (2020) give rational approximations at general smoothness | Split into two claims: the specific prototyped `SparseMaternPrior` does change $\nu=1.5\to1$ (a model change, and a confound in any benchmark against it); the SPDE literature does not forbid general $\nu$. **Not** an instruction to build a rational SPDE |
| 7 | NWIS wells "observe the state the twin carries… no physical model stands between sensor and state" | **Conditional, not general** | Gated on `measurement_target == water_table`; §4 |
| 8 | WTD and head anomalies need separate prior covariances | **Never true** | One registry entry; guard + tests |
| 9 | WTD is the landslide variable | **Imprecise** | Pore pressure is; DTW is an upstream derived input under stated assumptions (§2.3) |
| 10 | `resolution()` = spatial resolution | **Conflation** | Renamed `variance_reduction_ratio()` (alias kept); averaging kernel, effective width, and DFS added; a test builds the trap (two data with $R>0.9$ at one cell whose averaging widths differ >10×) |

Two further corrections found during the audit, not on the original list:

| # | Claim | Verdict | Fix |
|---|---|---|---|
| 11 | `03a:271`: $h(x,t) = \overline{\mathrm{DTW}}(x) + \Delta h(x,t) + r(x,t)$ | **Mixed variables** — head on the left, depth in the baseline; they differ by sign and datum | Rewritten in $D$ throughout, with the head-space equivalent and the conversion stated |
| 12 | `matern_correlation` docstring: "$\nu=0.5$ is the rough, once-differentiable-in-expectation exponential/OU form" | **Wrong regularity.** $\nu=1/2$ is *nowhere* mean-square differentiable | Corrected; general statement $\lceil\nu\rceil-1$ times differentiable |

---

## 4. Observation semantics: what a well measures (#189)

A water level in a well is $H = z + p/(\rho_w g)$ for the **screened interval**. It equals $h_{wt}$ only
when that interval brackets the phreatic surface of an unconfined aquifer.

**Audited fields.** `src/data/qc_nwis.py` previously captured `well_depth_va`, `alt_datum_cd` and
`aqfr_cd` (the last unused downstream). It now also carries `hole_depth_va`, `nat_aqfr_cd`,
**`aqfr_type_cd`** (the GWSI confined/unconfined domain — the single most directly relevant attribute,
previously dropped), and the **`openings_top_va`/`openings_bot_va`** screened interval, all converted to
metres, plus a site-level `is_flowing` flag.

**Classifier.** `well_hydrostratigraphy.measurement_target()` applies evidence most-direct-first:

1. **flowing/artesian** — disqualifies `water_table`; asserts `aquifer_head` only when corroborated by
   a confined code or depth, otherwise `unknown`. (A flowing well is *either* artesian-confined *or* a
   water table that has reached the surface in a valley bottom; the status code alone cannot tell
   them apart, and claiming otherwise would be a different error.)
2. **`aqfr_type_cd`** — `C`/`M`/`X` → `aquifer_head`. A *shallow* well in a confined-coded unit is
   `aquifer_head`: the code beats the depth proxy.
3. **screened interval** — a screen topping out in the shallow zone → `water_table`; a screen at or
   below the deep threshold → `aquifer_head`.
4. **total depth** — the fallback proxy, and the only widely populated attribute.

Anything undecidable — including the grey band between the shallow and deep thresholds — is
**`unknown`, flagged, never promoted**.

**Enforcement.** `observability.water_table_point_footprint()` raises for `aquifer_head` and `unknown`.
A test drives the full path: a shallow well in a confined unit is classified `aquifer_head` and then
refused the operator.

**Correction to the NWIS status-code handling.** The flowing flag uses only code `F`. Codes `E`
("recently flowing nearby") and `G` ("nearby recently flowing") describe a *neighbouring* well and are
not evidence about this one; including them would disqualify good water-table wells for their
neighbours' behaviour.

**Relation to #46.** The existing `classify_well_hydro()` depth-only screen is retained unchanged — it
still feeds the Stage-1 baseline — but it answers a different question (which hydrostratigraphic unit)
and is now documented as the coarser filter it always was.

---

## 5. The prior calibration experiment (#192)

`src/models/prior_calibration.py` + `scripts/calibrate_spatial_prior.py` implement the smallest
reproducible analysis that would replace the status labels with estimates.

**Design.** Out-of-fold residuals only, never the raw field. Wells screened by observation semantic
first. For each candidate $\nu$, REML with the overall scale profiled out analytically, multi-start
Nelder–Mead over $(\log L, \operatorname{logit}\alpha)$, so **every $\nu$ carries its own re-estimated
$(\sigma, L, \tau^2)$**. Scoring by leave-one-spatial-block-out: predictive log score, CRPS, RMSE,
90%/50% coverage, and standardized-residual mean/sd. Optional stratification by hydrogeologic domain
or by season. Artifact schema `gaia/spatial-prior-calibration/1` carries state, transform, candidate
$\nu$, fitted $\sigma$/$L$/nugget, REML objective, microergodic value, CV metrics, sample count,
support/depth definition, season, domain, and the exact range convention.

**Has it been run on real data? No — the residuals do not exist in this repository.** The committed
well fixture is synthetic and four sites deep; the real NWIS pull is gitignored. Reporting a
"calibration" from that fixture would be fabrication, so the demo mode refuses to write an artifact.

**What has been verified** (`--self-test`, 220 points over a 120 km domain, truth
$\sigma=0.6$, $L=15$ km, $\nu=1.5$, nugget $0.02$):

| ν | fitted σ | fitted L (km) | nugget | −2 REML | holdout log score | CRPS | cov₉₀ |
|---|---|---|---|---|---|---|---|
| 0.5 | 0.606 | 29.1 | 0.0007 | 87.02 | −0.494 | 0.224 | 0.86 |
| 1.0 | 0.564 | 16.8 | 0.0113 | 77.05 | −0.482 | 0.221 | 0.89 |
| **1.5** (truth) | 0.543 | 13.8 | 0.0150 | **75.41** | −0.474 | 0.220 | 0.90 |
| 2.0 | 0.531 | 12.4 | 0.0166 | 75.45 | **−0.470** | 0.219 | 0.90 |

Four results matter:

1. **Recovery is good at the true $\nu$:** $\sigma$ within 9%, $L$ within 8%, the microergodic
   combination within 6%; holdout coverage 0.90 at nominal 90%, standardized-residual sd 0.97.
2. **The $\nu$ profile is flat.** The four candidates span 0.025 nats of holdout log score; the winner
   leads the runner-up by 0.004 nats and is *not* the truth. On a network this size $\nu$ will not be
   determined, and the deliverable is a profile plus a sensitivity statement, not a number. This is
   the expected consequence of the identifiability limit, reported rather than hidden.
3. **Freezing $\sigma$ and $L$ while sweeping $\nu$ would have been meaningless.** Refitting moves the
   range from 29.1 km at $\nu=0.5$ to 12.4 km at $\nu=2$ for *one and the same field* — a factor of
   2.3 — far larger than the 0.054 maximum correlation difference that a fixed-parameter comparison
   would report.
4. **The negative control works.** Adding a deterministic drift (a topography stand-in) to the same
   residuals and fitting as if raw returns $\sigma = 2.03$ (true 0.6, a 3.4× inflation) and
   $L = 45.6$ km (true 15, a 3.0× inflation) — the
   drift is absorbed as spurious long-range "covariance". This is precisely what fitting a variogram to
   a raw domain-wide DTW map would do.

**To run it for real:** produce a table of spatially held-out water-table residuals
(`x_km`, `y_km`, `residual`, optional `domain`/`season`) from the baseline's block-CV fold predictions,
restricted to `measurement_target == water_table` sites, and pass `--residuals` with a `--support`
string. The same for SNOTEL/USCRN $\theta$ residuals, stratified wet/dry.

---

## 6. Bibliography

All 98 DOI-bearing entries resolve and — new in this cycle — their **title, first-author family name
and year match the Crossref record**. `scripts/check_doi_integrity.py --metadata` is the gate; run it
before any release that touches `references.bib` (#158).

**Verified and used in this audit** (all post-2000, all cited for claims they actually support):

| key | citation | used for |
|---|---|---|
| `zhang2004inconsistent` | Zhang (2004), *JASA*, `10.1198/016214504000000241` | $\sigma$/range not separately consistently estimable; microergodic combination |
| `guttorp2006matern` | Guttorp & Gneiting (2006), *Biometrika*, `10.1093/biomet/93.4.989` | Matérn history/naming |
| `minasny2005matern` | Minasny & McBratney (2005), *Geoderma*, `10.1016/j.geoderma.2005.04.003` | REML fitting of full Matérn; low smoothness **for measured soil properties** — explicitly not for monthly soil moisture |
| `lindgren2011explicit` | Lindgren, Rue & Lindström (2011), *JRSS-B*, `10.1111/j.1467-9868.2011.00777.x` | SPDE/GMRF; the $\sqrt{8\nu}$ range convention |
| `bolin2020rational` | Bolin & Kirchner (2020), *JCGS*, `10.1080/10618600.2019.1665537` | rational SPDE at general smoothness — the correction to claim 6 |
| `haitjema2005subdued` | Haitjema & Mitchell-Bruker (2005), *Groundwater*, `10.1111/j.1745-6584.2005.00090.x` | water table follows topography only conditionally; drainage divide ≠ groundwater divide |
| `fan2013global` | Fan, Li & Miguez-Macho (2013), *Science*, `10.1126/science.1229881` | global WTD regression (already cited in 03a) |
| `varouchakis2019spatiotemporal` | Varouchakis, Theodoridou & Karatzas (2019), *J. Hydrol.*, `10.1016/j.jhydrol.2019.05.055` | Bayesian spatiotemporal GWL with a physical-background drift |
| `varouchakis2022complex` | Varouchakis, Guardiola-Albert & Karatzas (2022), *WRR*, `10.1029/2021WR029988` | GWL geostatistics in complex hydrogeology |
| `ryu2005footprint` | Ryu & Famiglietti (2005), *WRR*, `10.1029/2004WR003835` | soil-moisture marginal PDF changes with wetness; Gaussian/beta validity regimes |
| `vereecken2014soilmoisture` | Vereecken et al. (2014), *J. Hydrol.*, `10.1016/j.jhydrol.2013.11.061` | scale/state dependence of soil-moisture spatial structure |
| `pacheco2005time` | Pacheco & Snieder (2005), *JASA*, `10.1121/1.2000827` | coda sensitivity kernel (already cited in 05) |
| `clements2018tracking` | Clements & Denolle (2018), *GRL*, `10.1029/2018GL077706` | dv/v tracks groundwater |
| `zhang2023oklahoma` | Zhang et al. (2023), *GRL*, `10.1029/2023GL103419` | ambient noise ↔ terrestrial water storage |
| `zhang2025oklahomamapping` | Zhang et al. (2025), *GRL*, `10.1029/2025GL115201` | spatiotemporal near-surface velocity for groundwater |
| `lu2025deepsoilmoisture` | Lu et al. (2025), *GRL*, `10.1029/2025GL117302` | deep soil moisture from ambient noise |
| `feng2026utah` | Feng et al. (2026), *JGR Solid Earth*, `10.1029/2024JB030689` | decadal near-surface velocity ↔ hydrology |
| `thompson2007vscorrelation` | Thompson, Baise & Kayen (2007), *SDEE*, `10.1016/j.soildyn.2006.05.004` | shallow $V_S$ spatial correlation, SF Bay |
| `thomson2020canterbury` | Thomson et al. (2020), *SDEE*, `10.1016/j.soildyn.2019.105834` | shallow $V_S$ spatial correlation, Canterbury |
| `zhu2017geospatial` | Zhu, Baise & Thompson (2017), *BSSA*, `10.1785/0120160198` | modeled WTD as a geospatial-liquefaction predictor |
| `bogaard2016landslidehydrology` | Bogaard & Greco (2016), *WIREs Water*, `10.1002/wat2.1126` | landslide hydrology → pore pressure |
| `pelascini2022hillslope` | Pelascini et al. (2022), *NHESS*, `10.5194/nhess-22-3125-2022` | excess pore pressure without water-table movement |

**Pre-2001 entries retained, and why.** `whittle1954stationary`, `matern1960spatial` (family origin);
`handcock1993bayesian`, `stein1999interpolation` (the statistical treatment of $\nu$ and infill
prediction); `mizell1982spectral`, `gelhar1993stochastic`, `dagan1989flow` (the spectral log-$K$→head
filtering result — a mathematical derivation with no modern replacement, and note it is now cited
*only* for the directional smoothness argument, never for a numerical $\nu$); `biot1941general`,
`brutsaert1977recession`, `beven1979physically`, `koolparker1987` (foundational mechanics/hydrology).
`western2002scaling` is retained for scaling context only and is explicitly no longer used to support a
smoothness value.

**Two provenance fixes already in the working tree, confirmed:** `cuthbert2019global` had the author
list of a different Cuthbert et al. (2019) paper; `vereecken2014soilmoisture` had the author list of a
different Vereecken et al. paper; `mizell1982spectral` had a paraphrased title. All three corrected
against Crossref and annotated inline.

**Nothing was removed.** Three entries legitimately have no Crossref record (a USGS data release and
two arXiv preprints) and are skipped, not failed, by the checker.

---

## 7. Issue-by-issue audit

Format per issue: **assumption → still correct? → terminology → code implied → acceptance-criterion
change → dependency change → verdict** (unchanged / amend / partly superseded / split).

### #187 — Canonical probabilistic state contract · **UNCHANGED, defend it**
- **Assumption:** primary state should be storage-based; head/DTW/θ/saturation/recharge/pore pressure
  derived rather than updated as independent copies.
- **Correct?** Yes, and this audit explicitly declines to replace it with an evolving head field.
- **Terminology:** the contract should name the derived quantities *distinctly* — `h_wt`, `D`, `H`
  (screened-interval hydraulic head) and `u` are four things, and the current text's "head, DTW, theta,
  saturation, recharge, and pore-pressure quantities" reads as one undifferentiated list.
- **Code implied:** none beyond `src/models/hydro_state.py`, which supplies the conversion algebra the
  contract will need.
- **Acceptance addition:** *"The schema distinguishes water-table head $h_{wt}$, depth to water
  $D = z_s - h_{wt}$, screened-interval hydraulic head $H$, and pore pressure $u$ as separate derived
  quantities with separate units and support; and a round-trip test asserts
  $\Delta D = -\Delta h_{wt}$ so the two cannot drift apart in storage."*
- **Dependencies:** unchanged.

### #189 — Ground-sensor observation records · **AMEND (strengthen)**
- **Assumption:** one time-aware observation record with support, QC, covariance metadata and an
  assimilation/validation role. Task list already includes "implement screened-well operators".
- **Correct?** Yes but underspecified: it treats the screened-well operator as an *operator* problem
  when it is first a *classification* problem. Without a per-site semantic there is nothing to select
  the operator on.
- **Terminology:** add `measurement_target ∈ {water_table, aquifer_head, unknown}` to the record schema
  alongside depth/support.
- **Code implied:** landed in part — `measurement_target()`, `water_table_observations()`,
  `measurement_target_summary()`, the `qc_nwis` metadata capture, and the gated
  `water_table_point_footprint()`. Remaining: the aquifer-head *operator* itself.
- **Acceptance additions:** *"Every well observation carries an explicit `measurement_target`; a
  confined/deep/unknown record cannot be routed through the shallow water-table point operator (an
  automated test asserts the refusal); and the count of sites in each class is reported in the QC
  report."*
- **Dependency:** no longer only "builds on #9/#46" — #46's depth-only screen is a *fallback* inside a
  richer classifier.

### #142 — Seasonal-high DTW in liquefiable units · **AMEND**
- **Assumption:** calibrate DTW against shallow-screened wells inside young alluvium/fill; sub-metre
  accuracy there; replace TOPMODEL in coastal/confined; propagate the DTW pdf into the GLM.
- **Correct?** Yes — and it is already the most nearly right of the hazard issues, since it says
  "shallow-screened".
- **Terminology:** make "shallow-screened" operational rather than adjectival.
- **Acceptance addition:** *"The calibration set is restricted to `measurement_target == water_table`
  sites; confined or unknown-target heads are excluded from the DTW truth set and the exclusion count
  is reported. Accuracy is reported for the liquefiable lowland separately, not inherited from the
  pooled block-CV score."*
- **Note:** the target here is a *seasonal-high* quantile of DTW, which is a tail statistic — a
  calibrated mean with honest σ does not guarantee a calibrated 10th percentile, and the acceptance
  criteria should say which is being scored.

### #139 / #141 — Liquefaction GLM epic and MVP · **UNCHANGED, add the citation**
- **Assumption:** drive a published geospatial liquefaction GLM with Vs30, the twin's modeled
  seasonal-high DTW, and scenario PGV.
- **Correct?** Yes. Zhu, Baise & Thompson (2017) explicitly use modeled water-table depth as a
  predictor, so "the term static GLMs only approximate" is accurate and now citable.
- **Terminology:** cite `@zhu2017geospatial` (already in `references.bib`, DOI verified) rather than
  "Zhu et al. 2017 / Maurer geospatial model" as prose.
- **Acceptance:** unchanged. The existing "sensitivity showing dynamic DTW changes the map vs a
  static-DTW baseline" is exactly the right test.

### #127 — LandLab landslide handoff epic · **AMEND**
- **Assumption:** infinite-slope FS driven by the twin's antecedent saturation / perched head for fall
  shallow failures and the seasonal-high water table for spring deep-seated.
- **Correct?** The FS equation as written already contains $\gamma_w h_w$ — i.e. it already consumes a
  pressure head, not a DTW. Good. What is missing is the statement that the conversion DTW → $h_w$
  carries an assumption.
- **Terminology:** state that slope stability consumes **pore pressure / effective stress**, and that
  DTW is an upstream proxy under an explicit hydrologic closure (hydrostatic vs slope-parallel:
  $\cos^2\beta$, a 25% difference at 30°).
- **Code implied:** `pore_pressure_hydrostatic_below_water_table()` and `pore_pressure_slope_parallel()`
  exist and are separately named; #128 should consume one of them by name rather than inlining
  $\gamma_w h_w$.
- **Acceptance addition:** *"The pore-pressure closure used by the FS calculation is named explicitly
  in code and in metadata (hydrostatic | slope-parallel | transient), and a test shows the FS field
  differs measurably between the hydrostatic and slope-parallel closures on a steep pilot cell."*

### #130 — Two subsurface stores · **AMEND (strengthen)**
- **Assumption:** one head anomaly on one linear reservoir collapses two failure regimes; add a
  transient shallow/perched store distinct from the deep GWL store.
- **Correct?** Yes, and this audit strengthens it: the two stores are not merely fast/slow, they are
  **different water bodies with different observation semantics**.
- **Terminology:** three-way, not two-way — (a) shallow perched / transient saturation and interflow,
  (b) the regional phreatic water table $h_{wt}$, (c) deeper confined/semiconfined hydraulic head $H$.
  The well network mostly observes (b), sometimes (c), and almost never (a) — which is why the shallow
  store will be weakly observed and needs to say so.
- **Acceptance addition:** *"The two stores are named as distinct physical water bodies (perched/
  transient vs regional phreatic), not as fast/slow components of one head; and the issue records which
  observation stream, if any, constrains the shallow store."*

### #137 / #171 / #172 — Specific yield, vadose store, storage account · **AMEND**
- **Assumption:** $S_y = 0.30$ is near porosity and does three inconsistent jobs; the vadose gap is
  massless; the 3-knob closure is exactly determined and reported as validation.
- **Correct?** Yes on all three.
- **Terminology:** the storage-to-head conversion is the first arrow of #187's diagnostic chain, so
  $S_y$ is not just a water-budget parameter — it *scales the entire diagnosed head anomaly*, and its
  uncertainty is a first-order term in the DTW uncertainty budget, not a calibration detail.
- **Code implied:** `water_table_head_from_storage(..., specific_yield_sigma=...)` returns
  $\sigma_{\Delta h} = |\Delta h|\,\sigma_{S_y}/S_y$; the water budget does not yet propagate it.
- **Acceptance addition (#137):** *"$\sigma_{S_y}$ is estimated alongside $S_y$ and propagated into the
  diagnosed head/DTW uncertainty budget as an explicit component, using the same
  storage→head conversion the state contract uses."*
- **Note:** `SPECIFIC_YIELD_RANGE = (0.005, 0.6)` in `hydro_state.py` is a *guard against the
  storativity trap*, not a physical bound endorsement; #137's "bound $S_y$ to a physical range" should
  set the tighter, defensible range.

### #163 — Prior structure: scalable AND terrain-aware · **AMEND (materially)**
- **Assumption:** replace the dense isotropic squared-exponential with "a Matérn ($\nu\sim1/2$–$3/2$),
  terrain-aware/nonstationary or SPDE-precision (GMRF) prior — which is *simultaneously* the scalable
  representation and the physically right correlation structure."
- **Correct?** Half. The Matérn switch and the anti-leakage masking landed and were right. Three things
  in the framing are now wrong or unsafe:
  1. **It fuses two decisions.** "Simultaneously the scalable representation and the physically right
     correlation structure" is exactly the coupling this audit rejects: the classical local GMRF
     construction forces integer $\nu$, so adopting it *as the scalability fix* silently changes the
     statistical model. The statistical model and the numerical backend must be chosen separately.
  2. **It does not say what the prior is on.** It should say: a Matérn prior on the **residual/anomaly**
     about the deterministic baseline, with **state-specific** smoothness.
  3. **"terrain-aware"** overstates what `region_id` is (see below).
- **Terminology:** rewrite the objective as *"a residual/anomaly Matérn prior with state-specific
  smoothness, configurable barriers, and a numerical representation that does not dictate $\nu$."*
- **Acceptance additions:** *"Groundwater and soil moisture carry independently configurable $\nu$
  (asserted by test). The prior is documented as being on the baseline residual, not the absolute
  field. Any sparse/SPDE representation adopted for scalability reports whether it changes $\nu$, and
  a benchmark against it treats a changed $\nu$ as a confound rather than a rounding."*
- **Dependency:** split the scalability half cleanly to #154 (below).

### #163/#188/#192 — the `region_id` zero-correlation rule · **AMEND**
- **Assumption:** $C_{ij} = 0$ if `region_id[i] != region_id[j]`, described as "terrain-aware" and as
  fixing cells that "do not hydraulically communicate".
- **Correct?** As an anti-leakage/localization heuristic, yes and it is worth keeping. As
  hydrogeology, no: a surface drainage divide is not necessarily a groundwater divide, groundwater
  crosses topographic basin boundaries depending on aquifer geometry and gradient, and whether the
  water table follows topography at all is conditional (Haitjema & Mitchell-Bruker 2005). A hard zero
  is an infinitely strong statement about a usually-partial boundary.
- **Terminology:** call it a **hydrographic localization / barrier approximation**. `barrier_id` is now
  an accepted alias of `region_id` in `GaussianPrior` (both populated, a contradictory pair raises), and
  the docstring states the status. A full rename is *proposed, not executed*, because every call site
  and the #188 particle-localization design use `region_id`.
- **Code implied:** prefer **hydrogeologic domain** labels (`src/features/hydrogeologic_domains.py`)
  over drainage basins; allow a *soft* connectivity weight in place of a 0/1 mask.
- **Acceptance addition (#192):** *"Localization labels are hydrogeologic-domain based where available;
  the zero-correlation rule is documented as an approximation, and the cross-boundary leakage test
  distinguishes 'the barrier works' from 'the barrier is physically correct'."*

### #154 — Dense covariance scalability wall · **UNCHANGED, keep it separate**
- **Assumption:** adopt a scalable formulation so `C @ G.T` is $n_\text{obs}$ kernel evaluations, not a
  dense matrix; or state plainly that the product is demo-resolution.
- **Correct?** Yes, and the required quantities are exactly $\mathrm{diag}(B)$, $BG^\top$, $GBG^\top$ —
  none of which needs a dense $B$.
- **The one thing to hold:** this issue must **not** be allowed to select the statistical model. Direct
  kernel evaluation, FFT, SPDE precision, and ensemble covariance are interchangeable backends for one
  $(\sigma, L, \nu, \text{barriers})$; the benchmark in
  `docs/reviews/prior-operator-benchmark.md` already shows a candidate backend changing $\nu$, and that
  difference must be reported as a model change.
- **Acceptance addition:** *"The chosen backend is benchmarked at the SAME $(\sigma, L, \nu)$ as the
  reference, or the $\nu$ change is reported as a separate, quantified term in the error budget."*

### #192 — Estimate and diagnose B/Q/R · **AMEND (make the experiment concrete)**
- **Assumption:** "estimate spatial/domain-dependent localization and prior correlation scales from
  held-out residuals/variograms." Directionally right and already says *held-out residuals*.
- **Correct?** Yes; it is the closest existing issue to this audit's §5. What it lacks is the *shape* of
  the experiment, and without that "estimate from residuals/variograms" can still be satisfied by
  fitting one variogram at a fixed $\nu$.
- **Acceptance additions:** *"(a) residuals are out-of-fold and spatially blocked, never in-sample;
  (b) the report is a **profile over $\nu$** with $\sigma$, $L$ and nugget **re-estimated at each**,
  not a single fit; (c) the REML/profile objective is reported, not only the argmax; (d) spatial
  holdout predictive log score, CRPS, RMSE, interval coverage and standardized residuals are reported
  per candidate; (e) results are stratified by hydrogeologic domain, and for soil moisture by wet/dry
  season, where $n$ permits; (f) the output is a version-controlled machine-readable artifact carrying
  the exact range convention; (g) the docs cite the artifact rather than hardcoding values."*
- **Code implied:** landed as `src/models/prior_calibration.py` and
  `scripts/calibrate_spatial_prior.py`; what remains is producing the residual tables.
- **Also:** add a note that fitting a variogram to the raw domain-wide water-table or soil-moisture map
  is explicitly **not** an acceptable substitute, with the negative control from §5 as the reason.

### #198 — One depth-resolved hydromechanical operator · **AMEND**
- **Assumption:** forward and inverse must use the same physics; represent $V_s(z,t)$ with a static
  reference profile plus a state-driven perturbation and predict each band through its depth kernel.
- **Correct?** Yes, and this audit adds a covariance-side reading of the same requirement: because
  dv/v is an **operator on the hydrologic state**, its predicted covariance must follow as
  $HBH^\top + R$, not from an independent spatial prior on dv/v.
- **Terminology:** the saturated branch must say **which head**. For the shallow band, $\Delta h$ is a
  water-table-head change and the pore-pressure response is hydrostatic below a moving phreatic
  surface; in a confined interval the same physics applies to that interval's hydraulic head $H$, which
  can move metres with no water-table movement. $k_{sat}$ is calibrated against shallow water-table
  variation, so applying it to a deep-aquifer head signal is an extrapolation.
- **Acceptance additions:** *"The operator states which head/pressure variable each depth band responds
  to. dv/v carries no independent spatial prior; its predicted covariance is derived from the
  hydrologic/mechanical ensemble through the forward operator plus observation/model error. The docs do
  not present $k_{sat}\Delta h$ / $S_\theta\Delta\theta$ as first-principles physics — they are a local
  linearization and a temporary fidelity mode."*

### #205 — Regime-switching τ · **AMEND (status, not scope)**
- **Assumption:** a single scalar τ per state; a wet/dry-conditional τ is the principled extension,
  gated on an innovation-heteroscedasticity diagnostic.
- **Correct?** The scoping and the gate are right. What is missing is that **the current values are
  themselves uncalibrated**: 5 d and 120 d are order-of-magnitude readings, not measured properties of
  the Puget Sound subsurface, and a water-table τ depends on specific yield and drainage geometry that
  vary across the domain by more than the gap between them.
- **Terminology:** "provisional hyperparameters", estimated from the autocovariance of the twin's own
  residuals — not "the water table integrates months" stated as fact.
- **Code implied:** landed as a status comment on `TEMPORAL_TAU_DAYS`.
- **Acceptance addition:** *"Before (or alongside) any regime switching, report an estimate of the
  single τ per state from residual autocovariance, with its uncertainty; a switching model is only
  justified if the regime-conditional τs differ by more than that uncertainty."*

### #204 — Book/twin rewrite epic · **AMEND (add the vocabulary to the notation unification)**
- **Assumption:** one unified state-vector notation and one forecast/analysis superscript convention
  throughout; per-chapter implemented/demonstrated/planned status boxes.
- **Correct?** Yes, and this audit supplies content it needs.
- **Acceptance additions:** *"The unified notation includes the hydrologic state vocabulary
  ($S$, $h_{wt}$, $D$, $H$, $u$) with $D = z_s - h_{wt}$ stated once; 'GWL' is retired from prose as an
  unqualified term. Status labels distinguish `implemented` / `demonstrated` / `planned` **and**
  `uncalibrated assumption` — a value in use with no estimate behind it is not 'implemented science'."*

### #158 — DOI integrity in CI · **AMEND (raise the bar)**
- **Assumption:** CI resolves every DOI and fails on a miss.
- **Correct?** Necessary but not sufficient — and the repo has actually suffered the failure a
  resolution-only check cannot see: a real, resolvable DOI attached to the wrong paper (three such
  cases, now fixed).
- **Code implied:** `--metadata` mode added to `scripts/check_doi_integrity.py`, comparing title,
  first-author family name and year against Crossref with a ±1-year tolerance for online-first.
- **Acceptance addition:** *"CI runs the metadata comparison, not only resolution, and fails on a
  title/author/year mismatch. Entries with no Crossref record (data releases, preprints) are skipped
  explicitly and listed in the report rather than silently passing."*
- **Release gate:** this literature update should not merge without a green `--metadata` run.
  Current status: **98 entries, 0 mismatches, 3 skipped (no Crossref record).**

### #188 — Cycling localized ensemble nowcast · **AMEND (minor)**
- Add: localization labels should be hydrogeologic-domain based, and the barrier mask's approximate
  status recorded in the analysis metadata (see the `region_id` entry above).

### #176 — Hysteresis into the dynamics · **UNCHANGED**
- Consistent with this audit: hysteresis is a storage process, and implementing it only in the velocity
  map decorates the observable without changing the water. Nothing here changes it.

### #32, #71, #18, #160, #193, #195, #131, #172 — **UNCHANGED**
- **#32** (GWL forcing/method ensemble): the "GWL dynamic anomaly" it ensembles is the DTW anomaly;
  worth naming it as such, but nothing scientific changes.
- **#71** (AI QPF → antecedent state): unaffected.
- **#18** (epic): its table lists "Groundwater level" as a state — cosmetically it should read
  "groundwater storage → water-table head → DTW", but the epic is a routing document.
- **#160** (DA estimator correctness epic): its description of the prior as "dense stationary-isotropic
  squared-exponential" is now stale (it is Matérn); worth a one-line update.
- **#193**, **#195**: consistent; #195's "wells: screened point/depth support" already anticipates §4.
- **#131**, **#172**: unaffected by the terminology work; they are mass-balance issues.

### Issues whose present acceptance criteria would now encode the wrong science

1. **#163** — "Matérn (ν∼1/2–3/2), terrain-aware/nonstationary **or** SPDE-precision (GMRF) prior —
   which is *simultaneously* the scalable representation and the physically right correlation
   structure." Satisfying this as written by adopting the local GMRF would silently move $\nu$ to an
   integer while being recorded as a scalability win. **Highest-priority edit.**
2. **#192** — "estimate … prior correlation scales from held-out residuals/**variograms**" is
   satisfiable by one variogram fit at a fixed $\nu$, which is the shortcut §5 shows to be wrong.
3. **#142** — "calibrate DTW against shallow-screened wells" is satisfiable by a depth filter that
   admits a shallow well in a confined unit.
4. **#127/#128** — an FS implementation could satisfy the epic while hard-coding a hydrostatic closure
   with no record that it did so.
5. **#205** — "a single scalar correlation time per state" implicitly treats 5 d / 120 d as known.

---

## 8. Code paths that still conflate the quantities

Honest list of what the audit did **not** fix.

| path | conflation | why not fixed here |
|---|---|---|
| `src/models/water_budget.py` | one head anomaly, one linear reservoir, one recession — the perched/regional/confined distinction is absent; `SPECIFIC_YIELD = 0.30` does three jobs | this is #130/#137/#171/#172's substance; changing it moves calibrated products |
| `src/models/gwl_dynamic.py` | function named `gwl_dynamic_90m`, computes DTW; kriges a DTW anomaly and calls it "GWL". Correct arithmetic, ambiguous name | rename is churn across notebooks/artifacts; documented instead |
| artifact names `gwl_dtw.zarr`, `gwl_wte.zarr`, `gwl_kriging_std.zarr`, `nwis_gwlevels_monthly.parquet` | `gwl_` prefix is a legacy label; the *contents* are correctly distinguished (`dtw_m` vs `wte_m`) | renaming published artifacts breaks consumers; low risk since the variable names inside are unambiguous |
| `TEMPORAL_TAU_DAYS["gwl"]`, `ObsStream.states = ("gwl",)` | `"gwl"` as a state key means the water-table-head anomaly | key is indexed by notebooks and `effective_observability`; `STATE_LABELS` added as a crosswalk to the unambiguous name rather than a breaking rename |
| `src/models/soil_mechanics.py` | `MechanicsInputs.water_table_depth` annotated `[pore pressure]`; the module is a scaffold that raises | #128 owns it; the comment is now wrong in a way that matters, and the pore-pressure helpers exist to fix it |
| `src/io/landlab_export.py` | ships `water_table__depth`; LandLab forms its own wetness internally, so the pore-pressure closure is implicit and unrecorded | export contract is shared with `landslide-data-prep`; flagged in #127 |
| `src/models/interpolate_residuals.py`, `interpolate_anomalies.py`, `pilot_temporal.py` | krige in WTE or DTW space per module; both are correct and mutually consistent, but no single module states which is canonical | superseded by #187's state contract |
| `GaussianPrior` | carries no **nugget**; the calibration harness estimates one | reconciling them is real work — the nugget changes $\mathrm{diag}(B)$ and therefore every variance-reduction map |
| `src/data/qc_nwis.py` | drops NGVD29 sites outright rather than applying VERTCON; datum handling is coarse | pre-existing, documented, out of scope |

---

## 9. Unresolved empirical questions

1. **What are $(\sigma, L, \nu)$ for the water-table-head residual over Puget Sound?** Unknown. The
   experiment exists; the out-of-fold residual table does not. Expect the $\nu$ profile to be flat.
2. **What are they for soil moisture, and do they change with wetness state?** Unknown, and Vereecken
   et al. (2014) predict they do — so a single stationary $(\sigma, L, \nu)$ may be the wrong object
   regardless of its fitted values.
3. **Does the Gaussian anomaly approximation hold for soil moisture near saturation and near residual
   water content?** Untested. Ryu & Famiglietti (2005) say the marginal shape changes with wetness. The
   test is whether the posterior keeps its mass inside the physical bounds; the logit-of-effective-
   saturation transform is documented as the fallback, not adopted.
4. **Is the drainage-basin barrier defensible anywhere in this domain?** Unknown. It needs a
   hydrogeologic check per boundary, or replacement by a soft connectivity weight.
5. **How many NWIS sites in the domain actually classify as `water_table`?** Unknown until the
   classifier runs on the real pull — `aqfr_type_cd` and screened intervals are sparsely populated in
   NWIS, so the `unknown` class may be large. If it is, that is a finding about the observing system,
   not a bug in the classifier.
6. **What is $\sigma_{S_y}$, and how much of the DTW uncertainty budget does it carry?** Unknown; #137.
7. **What are the true temporal $\tau$s, and are they regime-dependent?** Unknown; #205, #194.
8. **Do the per-instrument $\sigma$ values trace to any instrument spec?** No — #189's added task says
   so explicitly, and two mutually inconsistent placeholder sets are still in the repo.

---

## 10. What was changed, in one list

**New code:** `src/models/hydro_state.py` (state vocabulary, conversions, invariant guard),
`src/models/prior_calibration.py` (REML profile + spatial-block CV + artifact),
`scripts/calibrate_spatial_prior.py` (CLI + self-test).

**Changed code:** `src/models/observability.py` (general-$\nu$ Matérn; `RANGE_CONVENTION`;
`convert_matern_range`; `microergodic_parameter`; `PRIOR_HYPERPARAMETERS`/`NU_CANDIDATES`/
`prior_for_state`; `barrier_id` alias; `variance_reduction_ratio` + `resolution` alias;
`averaging_kernel`; `resolution_width_km`; `degrees_of_freedom_for_signal`;
`water_table_point_footprint`; `STATE_LABELS`; τ status), `src/features/well_hydrostratigraphy.py`
(`measurement_target` and friends), `src/data/qc_nwis.py` (screen/aquifer-type/flowing capture and
semantics), `src/data/fetch_vs30.py` (static-$V_S$ geostatistics note).

**Changed docs:** `04-assimilation.qmd` (new state section; rewritten prior section; dv/v-as-operator
callout; well-semantics gating), `05-state-evaluation.qmd` (variance-reduction terminology; hyperparameter
status; barrier status; wells row), `03a-physics-hydrology.qmd` (notation), `03b-physics-hydromechanics.qmd`
(which head; static-$V_S$ callout), `07-hazard-integration.qmd` (pore pressure vs DTW; liquefaction WTD).

**Tests added:** `tests/test_hydro_state.py` (10 new), `tests/test_prior_calibration.py` (8 new), plus
12 new in `tests/test_observability.py` and 6 new in `tests/test_well_hydrostratigraphy.py` — 36 new
tests. The CI gate (`pixi run test`) goes 149 → 185 passing; a full root `pytest -q`, which also picks
up the launcher tests, goes 163 → 199.

**Bibliography:** 22 verified post-2000 entries in use for this audit; 0 metadata mismatches across all
98 DOI-bearing entries; nothing invented, nothing removed.

---

## 11. Appendix — proposed issue edits, ranked, with patch text

**Applied 2026-08-19.** All 13 blocks are now on GitHub: ranks 2-13 as comments (16 comments, since
rank 4 posts to both #127 and #128 and rank 13 splits across #188, #160, #18 and #32), and rank 1 as a
body replacement on #163 — with the original body archived as a comment on that issue first, so
nothing was overwritten without a record. The text below is retained as the source of those edits.

Ranking is by *risk that the issue as written leads someone to do the wrong thing*, not by effort.

---

### Rank 1 · #163 — body replacement (highest risk: would silently change ν while recording a scalability win)

> **Replace the body with:**
>
> Two faults were originally identified in one object (`GaussianPrior`): (i) the dense `(n,n)` `C` is
> infeasible at 90 m; (ii) a single isotropic length leaks constraint across drainage divides, and the
> $C^\infty$ squared-exponential imposes implausibly smooth fields.
>
> The Matérn switch and the `region_id` masking have **landed**. What remains needs restating, because
> the original framing fused two decisions that must stay separate.
>
> **Objective (revised):** a **residual/anomaly** Matérn prior with **state-specific smoothness**,
> **configurable barriers**, and a numerical representation that **does not dictate ν**.
>
> Three corrections to the original text:
>
> 1. **The prior is on the residual, not the field.** Absolute DTW is $D = z_s - h_{wt}$ and carries the
>    whole deterministic landscape; it is not a stationary Gaussian Matérn field over Puget Sound. The
>    prior belongs on $\delta h$ about the baseline (the standard drift-plus-residual construction —
>    Varouchakis et al. 2019, 2022).
> 2. **Groundwater and soil moisture must not share ν.** One `GaussianPrior` default governed both.
>    ν=3/2 is a *working hypothesis* for the water-table-head anomaly (the log-K→head filtering argument
>    is directional only, and does not select 3/2 over 1 or 2) and is *unsupported* for soil moisture,
>    which the literature describes as rougher and strongly state/scale/support/depth/season dependent
>    (Vereecken et al. 2014). Minasny & McBratney (2005)'s low smoothness is for measured **soil
>    properties**, not monthly soil moisture.
> 3. **"Simultaneously the scalable representation and the physically right correlation structure" is
>    the coupling to reject.** The classical *local* GMRF/SPDE construction exists only for integer α,
>    hence integer ν, so adopting it as the scalability fix silently changes the statistical model —
>    and the prototype benchmarked in `docs/reviews/prior-operator-benchmark.md` does exactly that
>    (ν=1.5→1). Rational SPDE methods reach general smoothness (Bolin & Kirchner 2020), so this is a
>    *choice*, not a constraint. The statistical model is selected on physical/statistical grounds;
>    the backend then serves it. Scalability is #154.
>
> **Also:** `region_id` is a **hydrographic localization / barrier approximation**, not an exact
> physical covariance boundary — a surface drainage divide is not necessarily a groundwater divide
> (Haitjema & Mitchell-Bruker 2005). Prefer hydrogeologic-domain labels
> (`src/features/hydrogeologic_domains.py`); consider a soft connectivity weight instead of a 0/1 mask.
> `barrier_id` now exists as an alias; a full rename is proposed, not done.
>
> **Acceptance:**
> - [ ] Groundwater and soil moisture carry independently configurable ν (asserted by test). *(landed)*
> - [ ] The prior is documented as being on the baseline residual. *(landed)*
> - [ ] Any sparse/SPDE representation adopted for scalability **reports whether it changes ν**, and
>       any benchmark against it treats a changed ν as a confound, not a rounding.
> - [ ] The barrier mask's approximate status is recorded in analysis metadata.
>
> Context: `docs/reviews/hydrology-geostatistics-prior-audit-2026-08.md` §3, §7.

---

### Rank 2 · #192 — comment (the acceptance criteria are satisfiable by the wrong experiment)

> The task "estimate spatial/domain-dependent localization and prior correlation scales from held-out
> residuals/variograms" is right in direction but satisfiable by a single variogram fit at a fixed ν,
> which is the shortcut that produces a wrong answer. Proposing these acceptance criteria:
>
> - [ ] Residuals are **out-of-fold and spatially blocked**, never in-sample. Fitting a variogram to the
>       raw domain-wide water-table or soil-moisture map is explicitly **not** an acceptable substitute:
>       in a controlled test, adding a deterministic drift to a known residual field inflated the fitted
>       σ by 3.4× and the fitted range by 3.0× relative to the truth.
> - [ ] The report is a **profile over ν** with σ, L **and nugget re-estimated at each candidate** — not
>       one fit, and not a sweep at frozen (σ, L). Refitting moves the fitted range by a factor of 2.3
>       across ν∈{0.5,2} for one and the same field, far larger than the kernel-shape difference at
>       fixed parameters.
> - [ ] The REML/profile objective is reported, not only the argmax.
> - [ ] Per candidate: spatial-holdout predictive log score, CRPS, RMSE, 90%/50% interval coverage, and
>       standardized-residual mean/sd.
> - [ ] Stratified by hydrogeologic domain, and for soil moisture by wet/dry season, where n permits.
> - [ ] Water-table residuals are restricted to `measurement_target == water_table` sites (#189).
> - [ ] Output is a version-controlled machine-readable artifact recording state, transform, candidate ν,
>       fitted σ/L/nugget, objective, CV metrics, n, support/depth definition, season/domain, and the
>       **exact range convention**; `04-assimilation.qmd` and `05-state-evaluation.qmd` cite the artifact
>       rather than hardcoding values.
> - [ ] Under fixed-domain asymptotics σ and L are not separately identifiable (Zhang 2004); the report
>       states the microergodic combination σ²κ^(2ν), κ=√(2ν)/L, and does not present σ and L as
>       independently calibrated.
>
> Implementation has landed as `src/models/prior_calibration.py` and
> `scripts/calibrate_spatial_prior.py` (with a `--self-test` recovery study). **It has not been run on
> real data** — the out-of-fold residual tables do not exist in the repo. Expect the ν profile to be
> flat: in the synthetic recovery run, four candidates spanned 0.025 nats of holdout log score on 220
> points.

---

### Rank 3 · #142 — comment (a depth filter would satisfy "shallow-screened" while admitting confined heads)

> "Calibrate DTW against shallow-screened wells inside young alluvium/fill" is the right target, but a
> depth-only filter satisfies it while admitting a *shallow well in a confined unit*, whose level is a
> potentiometric head, not a water table. Proposing:
>
> - [ ] The calibration set is restricted to sites with `measurement_target == water_table`
>       (`src/features/well_hydrostratigraphy.py`, #189). Confined, artesian and `unknown` targets are
>       excluded from the DTW truth set and the exclusion counts are reported.
> - [ ] Accuracy is reported **for the liquefiable lowland separately**, not inherited from the pooled
>       block-CV score.
> - [ ] The scored quantity is stated: the target is a **seasonal-high** (tail) quantile of DTW, and a
>       calibrated mean with an honest σ does not imply a calibrated 10th percentile. Report coverage of
>       the tail statistic that the GLM actually consumes.
>
> Supporting: the geospatial liquefaction model uses *modeled water-table depth* as an explicit
> predictor (Zhu, Baise & Thompson 2017, `10.1785/0120160198`), so DTW here is a first-class input, not
> a proxy — which is exactly why its truth set has to be the right population.

---

### Rank 4 · #127 (and #128) — comment (an FS implementation could hard-code a hydrologic closure invisibly)

> The FS expression in this epic already consumes a pressure head ($\gamma_w h_w$), which is correct.
> What is missing is that **DTW → $h_w$ carries an assumption**, and the assumptions are not equivalent:
>
> - hydrostatic: $u(z) = \rho_w g (h_{wt} - z)$
> - slope-parallel (what an infinite-slope FS implicitly assumes): $u(z) = \rho_w g (h_{wt}-z)\cos^2\beta$
>   — 25% smaller at 30°
> - transient infiltration: neither; excess pore pressure can be generated at a failure surface with no
>   regional water-table movement (Pelascini et al. 2022, `10.5194/nhess-22-3125-2022`)
>
> The mechanically fundamental variable is pore pressure / effective stress at the failure surface
> (Bogaard & Greco 2016, `10.1002/wat2.1126`); DTW is an upstream derived input under a stated closure.
>
> `src/models/hydro_state.py` now provides `pore_pressure_hydrostatic_below_water_table()` and
> `pore_pressure_slope_parallel()` as **separately named** functions, and deliberately no generic
> `pore_pressure_from_head` — a generic helper lets a slope-stability caller inherit a hydrologic
> condition it never chose.
>
> Proposed acceptance addition for #128: *the pore-pressure closure is named explicitly in code and in
> output metadata (hydrostatic | slope-parallel | transient), and a test shows the FS field differs
> measurably between the hydrostatic and slope-parallel closures on a steep pilot cell.*

---

### Rank 5 · #189 — comment (right, underspecified: classification precedes the operator)

> This issue treats the screened-well operator as an operator problem. It is first a **classification**
> problem: without a per-site semantic there is nothing for the operator selection to key on. A well
> level is the hydraulic head $H = z + p/(\rho_w g)$ of its *screened interval*, and equals the
> water-table head only when that interval brackets the phreatic surface of an unconfined aquifer.
>
> Proposed schema addition: `measurement_target ∈ {water_table, aquifer_head, unknown}`, alongside
> depth/support, assigned most-direct-evidence-first from flowing status → `aqfr_type_cd` → screened
> interval (`openings_top_va`/`openings_bot_va`) → total depth as fallback. `unknown` is a **flag, never
> a default promotion**.
>
> Proposed acceptance additions:
> - [ ] Every well observation carries an explicit `measurement_target`.
> - [ ] A confined / deep / unknown record **cannot** be routed through the shallow water-table point
>       operator; an automated test asserts the refusal.
> - [ ] The count of sites in each class is reported in the QC report.
>
> Landed so far: the classifier, the conservative `water_table_observations()` screen, the
> `qc_nwis` capture of `aqfr_type_cd` / screened interval / national aquifer code / flowing flag, and
> `observability.water_table_point_footprint()` which raises for non-`water_table` targets. **Still
> open: the aquifer-head operator itself** — a deep or confined well is often a valuable observation and
> should get a depth/aquifer operator or its own hydraulic-head diagnostic, not be discarded.
>
> One correction to the NWIS handling: only status code `F` is evidence about *this* well. Codes `E`
> ("recently flowing nearby") and `G` ("nearby recently flowing") describe a neighbouring well.
>
> Dependency note: #46's depth-only screen becomes the *fallback* inside this classifier, not the
> mechanism.

---

### Rank 6 · #187 — comment (correct; make the derived vocabulary explicit)

> Keeping the storage-first contract exactly as proposed — this is the right architecture and should not
> be replaced by an independently evolving head field.
>
> One tightening: "head, DTW, theta, saturation, recharge, and pore-pressure quantities should be
> derived consistently" reads as one undifferentiated list, and four of those are distinct objects that
> have been conflated elsewhere in the repo:
>
> - $S$ — groundwater storage (the canonical evolving state)
> - $h_{wt}$ — water-table head, phreatic surface of an unconfined aquifer
> - $D = z_s - h_{wt}$ — depth to water table
> - $H = z + p/(\rho_w g)$ — hydraulic head of a *screened interval* (what a well measures; ≠ $h_{wt}$)
> - $u$ — pore-water pressure (what slope stability consumes)
>
> Proposed acceptance addition: *the schema distinguishes these as separate derived quantities with
> separate units and support, and a round-trip test asserts $\Delta D = -\Delta h_{wt}$ so the two cannot
> drift apart in storage.* (They have identical covariance — there is no separate prior to fit for WTD.)
>
> Vocabulary and conversions are in `src/models/hydro_state.py`, including the storage→head step with
> $\sigma_{S_y}$ propagation, which refuses a confined storativity.

---

### Rank 7 · #130 — comment (strengthen: three water bodies, not two speeds)

> Agreeing with this issue and proposing it be stated more strongly. The two stores are not merely
> fast and slow components of one head — they are **different water bodies with different observation
> semantics**. Three, in fact:
>
> 1. shallow **perched / transient** saturation and interflow — flashy, the fall shallow-failure control;
> 2. the regional **phreatic water table** $h_{wt}$ — lagged, the spring deep-seated control;
> 3. deeper **confined / semiconfined hydraulic head** $H$ — a potentiometric surface, not a water table.
>
> The consequence for observability is the part worth recording: the NWIS network mostly samples (2),
> sometimes (3), and almost never (1). So the shallow store will be weakly observed, and the issue
> should say so rather than leaving a reader to assume the wells constrain it.
>
> Proposed acceptance addition: *the stores are named as distinct physical water bodies (perched/
> transient vs regional phreatic), not as fast/slow components of one head, and the issue records which
> observation stream, if any, constrains the shallow store.*

---

### Rank 8 · #205 — comment (the current τ values are themselves uncalibrated)

> The scoping and the diagnostic gate here are right. One addition: the issue implicitly treats the
> **current** values as known. They are not — 5 d and 120 d are order-of-magnitude readings, and a
> water-table τ depends on specific yield and drainage geometry that vary across this domain by more
> than the gap between the two numbers.
>
> `TEMPORAL_TAU_DAYS` is now commented as **provisional hyperparameters, not universal physical
> constants**.
>
> Proposed acceptance addition: *before (or alongside) any regime switching, report an estimate of the
> single τ per state from the residual autocovariance, with its uncertainty. A switching model is only
> justified if the regime-conditional τs differ by more than that uncertainty* — otherwise the switch is
> fitting noise, which is the same failure mode the diagnostic gate exists to prevent.

---

### Rank 9 · #154 — comment (keep the solver from choosing the science)

> Nothing wrong here; one guardrail. The required quantities are $\mathrm{diag}(B)$, $BG^\top$ and
> $GBG^\top$ — none needs a dense $B$ — and direct kernel evaluation, FFT, SPDE precision and ensemble
> covariance are interchangeable **backends for one statistical model**.
>
> The risk is that solving this issue selects the model. `docs/reviews/prior-operator-benchmark.md`
> already benchmarks a candidate backend that runs at ν=1 against a production model at ν=1.5.
>
> Proposed acceptance addition: *the chosen backend is benchmarked at the SAME (σ, L, ν) as the
> reference, or the ν change is reported as a separate, quantified term in the error budget rather than
> folded into the approximation error.*

---

### Rank 10 · #198 — comment (say which head; and dv/v carries no independent prior)

> Two additions to the required state convention.
>
> **Which head.** The saturated branch must name the variable. For the shallow band the coda samples,
> $\Delta h$ is a change in the **water-table head** (equivalently, up to sign, in depth to water), and
> the pore-pressure response is hydrostatic below a moving phreatic surface. In a confined or
> semiconfined interval the same physics applies to *that interval's* hydraulic head, which can move
> metres with no water-table movement. $k_{sat}$ is calibrated against shallow water-table variation, so
> applying it to a deep-aquifer head signal is an extrapolation, not a conversion.
>
> **The covariance side of "one operator".** dv/v is an **observation operator on the hydrologic state**,
> not a state with its own spatial prior. Assigning it an independent Matérn prior would double-count
> structure the hydrologic states already carry. Its predicted covariance must follow as $HBH^\top + R$.
> Ambient-noise dv/v is genuinely sensitive to hydrology (Clements & Denolle 2018; Zhang et al. 2023,
> 2025; Lu et al. 2025; Feng et al. 2026) *and* mixes soil moisture, groundwater/pore pressure, loading,
> temperature and depth-dependent elastic response — which is a statement about an operator, not a state.
>
> Proposed acceptance additions: *the operator states which head/pressure variable each depth band
> responds to; dv/v carries no independent spatial prior; and the docs do not present
> $k_{sat}\Delta h$ / $S_\theta\Delta\theta$ as first-principles physics — they are a local linearization
> and a temporary fidelity mode.*

---

### Rank 11 · #158 — comment (resolution is not enough; metadata matching is the actual gate)

> Resolution-only checking cannot catch the failure this file has actually suffered: a **real,
> resolvable DOI attached to the wrong paper**. Three such cases were found and fixed
> (`cuthbert2019global` and `vereecken2014soilmoisture` carried other papers' author lists;
> `mizell1982spectral` carried a paraphrased title).
>
> `scripts/check_doi_integrity.py --metadata` now queries Crossref and compares title, first-author
> family name and year (±1 year for online-first).
>
> Proposed acceptance addition: *CI runs the metadata comparison, not only resolution, and fails on a
> title/author/year mismatch. Entries with no Crossref record (data releases, preprints) are skipped
> explicitly and listed in the report rather than silently passing.*
>
> Current status: **98 entries, 0 metadata mismatches, 3 skipped (no Crossref record)**. This should be
> the release gate for any literature update.

---

### Rank 12 · #204 — comment (vocabulary belongs in the notation unification)

> Two additions for the unified-notation criterion:
>
> - The hydrologic state vocabulary ($S$, $h_{wt}$, $D$, $H$, $u$) with $D = z_s - h_{wt}$ stated once,
>   and **"GWL" retired from prose as an unqualified term** — it has meant storage, head, and depth to
>   water in different chapters of the same book.
> - The status boxes need a fourth label beyond implemented / demonstrated / planned:
>   **`uncalibrated assumption`**. A parameter in production use with no estimate behind it (ν, σ, L, the
>   temporal τs) is not "implemented science", and the current three labels have no place to put it.

---

### Rank 13 · #188, #160, #18, #32 — minor comments

> **#188:** localization labels should be hydrogeologic-domain based where available, and the barrier
> mask's approximate status recorded in the analysis metadata (see #163).
>
> **#160:** the epic description says the prior is a "dense stationary-isotropic squared-exponential".
> Stale — it is Matérn (ν=3/2) with optional barrier masking as of #163. The dense/isotropic criticisms
> still stand; the squared-exponential one does not.
>
> **#18:** the state table's "Groundwater level" row would read more accurately as
> "groundwater storage → water-table head → depth to water". Cosmetic for a routing epic.
>
> **#32:** the "GWL dynamic anomaly" being ensembled is specifically the **DTW anomaly**; worth naming,
> nothing scientific changes.
