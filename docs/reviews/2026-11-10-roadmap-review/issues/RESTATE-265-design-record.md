**Restated 2026-11-11 after the roadmap review (#319; record `docs/reviews/2026-11-10-roadmap-review/`).** The 2026-10-18 record stated the MODFLOW 6 core. Two reviews since then (2026-11-07 soil-state ladder, epic #296; 2026-11-10 roadmap review, epic #319) turned several of its statements into open questions with tests, and added forcing, mechanics, outputs and compute, which it did not cover. This restatement separates what PI approval fixes from what stays a proposal. The previous scope is archived below.

**PI direction on record:** 2026-10-18, MODFLOW 6 replaces the store model below the root zone, watershed-specific models, water table and soil moisture in the state, assimilation of raw, proxy and satellite observations. 2026-11-10, wildfire susceptibility is a fourth hazard consumer; flood work integrates the National Water Prediction Service, modular. 2026-11-11, forecast forcing could be HRRR, or ACE2 with the Stage IV downscaler.

## Purpose
One approved record of the architecture every issue builds on: the soil-state model as a whole, not only its groundwater core.

## A. Fixed by approval of this record

| # | Element | Statement |
|---|---|---|
| A1 | Components | A 90 m land-surface model (snow, canopy, root zone) over MODFLOW 6 groundwater flow (GWF), unsaturated-zone flow (UZF) and streamflow routing (SFR). The legacy store-model groundwater and the reinitialising forecast are not reused as state. |
| A2 | One owner per store | One snow model, one root-zone bucket, one water ledger (#232) that books model fluxes and assimilation increments separately. |
| A3 | Grid | Structured grid in EPSG:5070, cells of k x 90 m nested exactly in the 90 m ledger grid; k chosen by the convergence study (#283), not asserted. |
| A4 | Layers | By hydrostratigraphic unit; geometry uncertainty as framework realizations conditioned on well logs (#276, #277, #292). Fill, peat, tideflat and deltaic deposits are separate units. |
| A5 | Boundaries | Puget Sound general-head boundary (#10); two-way stream exchange (#278); seepage and drains at the model top; regulated rivers as gauged inflows; lakes (#293); exchanges between watershed models (#287); tested divides and bottom depth; pumping and return flows or a bounded omission (#279). |
| A6 | Watershed models | One groundwater model per watershed in a single simulation; a model domain encloses its gauge basin and is not clipped to it. |
| A7 | Time | Daily stress periods on the PRISM 12-12 UTC day; warm-up rule; hindcast from water year 2001. |
| A8 | Two estimation loops | Static parameters offline by iterative ensemble smoother (PEST++ IES, #284, #285); states by a cycling ensemble Kalman filter through modflowapi (#289, #188, #306). No datum serves both: one role per well-year and per gauge-year (#235). |
| A9 | Posterior object | The member set. Marginal sigma is a derived export, never the analysis product. |
| A10 | Observations | Only forward operators at native support enter the filter, never inverted retrievals; depth to water, pore pressure, effective stress and water content profiles are diagnosed, not assimilated. |
| A11 | Coupling | Hydrology drives mechanics, one way. The validity bound and the mask where it fails are recorded in #338. |
| A12 | Hazard products | Static susceptibility or antecedent state until a consumer is executed and validated on events. Four consumers: landslide (#127), liquefaction (#139), flood (#199), wildfire (#347). |
| A13 | Pilot first | Nothing is scaled to the western-Cascades domain before the pilot is calibrated and validated on held-out data (#286). The pilot domain is decision #269. |

## B. Open, each decided by a named test or decision (approval of this record does not settle them)

| # | Question | Decided by |
|---|---|---|
| B1 | Root-zone and MODFLOW partition: model top at the root base (option B) or at land surface (option A) | column test against a Richards reference, #302 |
| B2 | Capillary replenishment of the root zone and allocation of residual potential evapotranspiration | decision #307, on #302 evidence |
| B3 | Cycling by pause and resume or by cold restart; whether UZF water content joins the state | #303, decision #308 |
| B4 | Which snow model and which root-zone bucket survive | decision #309 |
| B5 | Role of the Hydrostate Richards kernel: reference column and library, or regional back end | decision #310 |
| B6 | Constrained analysis update versus clip-and-book | #304 |
| B7 | Filter variant, ensemble size, localization radius, vertical and cross-variable rules, treatment of a basin-integral observation, time convention for sub-daily data | specification and scale test, #322 |
| B8 | Error budget of the forecast step: additive head and boundary error, land-surface parameters, geometry realizations in members | #323 |
| B9 | Which proxies and satellite streams are admitted, and their bias treatment | admission contract #324; snow water equivalent operator #326 |
| B10 | Storm-time shallow-landslide triggering: a claim, with an hourly event-mode pressure column, or a non-claim | decision #341 |
| B11 | Forecast forcing by lead range: HRRR for 0 to 48 h; ACE2 with the Stage IV downscaler beyond; the baseline each is scored against | decision #333 |
| B12 | Whether a learned emulator is needed to afford the ensemble | measured budget #320, then decision #321 |
| B13 | Seasonal-high definition and decision-threshold probabilities | decision #346 |
| B14 | Whether wildfire stays a claim | value gate #349 |
| B15 | Whether the twin's antecedent state adds flood skill over the National Water Model | experiment #340 |

## C. Added since 2026-10-18 (in scope of the design, owned elsewhere)

- **Forcing.** Hindcast: PRISM daily with lapse-rate temperature (#263); wind, humidity, vapour-pressure deficit and radiation (#331); hourly precipitation (#332). Forecast variables beyond precipitation (#334).
- **Mechanics as state products.** Pore pressure u(z,t) and effective stress sigma'(z,t) from layer heads on (member, time, depth, y, x) (#336); suction-stress closure (#337); Vs(z,t) behind the hydromechanical operator (#250, #198).
- **Structure.** Geotechnical parameters per hydrostratigraphic unit, carried with the geometry realization (#342); upland regolith thickness with provenance (#343).
- **Retrospective product.** A smoother reanalysis for seasonal-high depth to water and event hindcasts, kept out of issue-time-frozen evaluations (#325).
- **Outputs.** One versioned hazard-facing schema with member, lead time, depth or layer, support and provenance (#335); change of support with its variance (#345).
- **Verification.** Ensemble scores in code (#344); numeric thresholds on the filter issues (spread/RMSE 0.8 to 1.2; 90 % coverage within 0.05); multi-event, issue-time-frozen evaluation (#305) with recorded events (#328).
- **Flood reference.** National Water Model adapter as baseline and optional routing back end (#339).

## Non-claims
Flood inundation extent on the 90 m grid; deep-seated landslide displacement and runout; site-scale liquefaction triggering; dead-fuel and live-fuel moisture; soil temperature and frozen ground; preferential flow. Each stays a non-claim unless an issue with a validation gate says otherwise.

## Acceptance
- PI approval of section A, recorded by removing `needs-human-decision` from this issue.
- Approval leaves every row of section B open; an issue that implements a section B item before its deciding test or decision is out of order.

## Hard blockers
Blocked by: none.

## Advisory follow-ups
Plan text: `docs/reviews/2026-10-18-modflow-groundwater-core/plan.md` (PR #273), sections 3 to 5, read with the amendments of 2026-11-09 (#296) and 2026-11-11 (#319). Where the plan asserts option B, "UZF advanced but not updated", or a localization taper, section B above governs.
