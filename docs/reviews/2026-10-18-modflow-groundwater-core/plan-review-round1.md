# Plan review, round 1 (2026-10-18)

Reviewers: `twin-hydrogeologist` and `twin-da-methodologist` (read-only personas,
`.claude/agents/`), on `plan.md` as first drafted. Neither reran anything; both read the plan and
`src/models/*.py` on branch `plan/modflow-groundwater-core`.

**Verdicts:** hydrogeologist approve-with-edits; DA methodologist approve-with-edits. No block.
Every item below was adopted; the disposition column names where. Revision 1 of `plan.md`
carries the changes.

## Hydrogeologist

| # | Concern | Severity | Decisive test (reviewer) | Disposition |
|---|---|---|---|---|
| H1 | Option B in valley cells: the LSM is a single-layer bucket (`soil_moisture.py`) with no saturation profile, and upward flux exists only as seepage above the MF6 top. A table 0–2 m below the root base feeds no capillary rise or riparian ET. | should-fix | 1-D valley column with the table crossing the root base, options A and B vs a Richards reference: head continuous, D within 0.1 m, upward flux agrees. | Plan §3.1; MF-06: explicit D rule inside the root zone, UZF groundwater ET with extinction depth below the root base, both fluxes in the #232 ledger; the column test goes to #267. |
| H2 | Upland stormflow moves laterally in colluvium inside the root zone; mapping #174 to #130 loses it. | should-fix | Quickflow fraction and recession at 12097500 and 12115000 with and without lateral root-zone flow. | #174 kept open, rescoped to upland root-zone lateral flow; removed from the superseded list. |
| H3 | Pilot domain bounded at the foothills bedrock contact contradicts "enclose the gauge basin"; no mountain-front boundary; Green and White rivers are regulated. | blocking for MF-07 | Overlay the 12108500 basin on the DNR bedrock contact; extend into a bedrock HSU or apply a mountain-front flux and test sensitivity. | Plan §3.4 mountain-front row, §5 rewritten; #269 and MF-07 carry the test and regulated-river inflows from gauges. |
| H4 | UZF advanced but not updated: where transit time exceeds the cycle, the un-updated wave undoes the head increment; a head reset can move the table through UZF water. | should-fix | OSSE in a 30 m drift-upland column, head-only vs head+UZF update. | #188 (a): transit-time threshold for augmenting UZF; ledger closure across table movement. |
| H5 | Mountain heads: recession constrains drainable storage and diffusivity, not K and S_y separately; GNSS basin loads sub-mm. | should-fix | pyEMU Schur data worth per data type; wells-blind calibration of the pilot then score the wells. | MF-14 reframed: product is basin storage with uncertainty; MF-10 adds the wells-blind control. |
| H6 | DIS vs DISV: a 90·2ⁿ quadtree also nests; coarse DIS loses narrow valley alluvium and canyon seepage. | advisory | — | MF-09: valley-width criterion, SFR gain/loss per reach metric, XT3D at refinement interfaces. |
| H7 | u(z) hydrostatic below the table fails under till where vertical gradients are strong. | should-fix | Nested piezometers: u(z) from h_wt vs from layer heads, >1 m head difference falsifies. | Plan §3.7: u(z) interpolated from layer heads. |
| H8 | No issue owns framework geometry uncertainty. | should-fix | K-only vs K+geometry ensembles, held-out coverage. | New MF-18. |
| H9 | Lakes and reservoirs missing (Lake Washington, Sammamish, Tapps, Kapowsin, kettle lakes). | should-fix for milestone B | Heads near a lake with and without LAK vs stage gauges. | New MF-19. |
| H10 | Return flows (septic, irrigation). | advisory | Bound from county septic records. | MF-05 widened to net withdrawals and return flows. |
| H11 | Perched-layer mechanics. | should-fix | 1-D column vs Richards for perched head and leakage. | #130: NPF `VARIABLECV DEWATERED` + `PERCHED`, low-K cap = Vashon till or Osceola lahar. |
| H12 | Thin calibration data (11 wells ≥12 months). | advisory | Linear data worth of added targets. | MF-03 also ingests static levels at completion as steady-state targets with a drilling-date noise term. |
| H13 | No stated accuracy or consumer. | should-fix | Valley DTW error budget vs decision threshold. | Plan §3.9 fitness-for-purpose paragraph; MF-12 reports against it. |

Reviewer source: USGS WRIR 92-4098 (Woodward et al. 1995, southwestern King County), cited for
glacial sediments up to 670 m thick; reviewer did not verify that it covers the Enumclaw plateau.

## DA methodologist

| # | Concern | Severity | Decisive test (reviewer) | Disposition |
|---|---|---|---|---|
| B1 | S·A·Δh is wrong when Δh crosses a cell bottom or the MF6 top; under option B water above the root base belongs to the LSM. `hydro_state.py` still calls storage canonical. | blocking (#187) | Single-column fixture: increments across a layer bottom and the top, then a zero-flux period; MF6 storage term equals booked ΔV to closure. | Plan §3.8; #187 and MF-15: ΔV = V(h_a) − V(h_f) from MF6's piecewise storage, excess above the top moved to the LSM, every clip booked; heads prognostic. |
| B2 | Dissipative model: spread collapses within a recession time without Q. | blocking (#188) | Linear-Gaussian confined case: EnKF (N = 500) matches the exact Kalman mean and covariance each cycle. | #188 (a): exact case first, Q from day one (AR(1) forcing, IES posterior, inflation), diagnostics from day one. |
| B3 | Double use: IES and the filter on the same wells and years; inner-loop parameter augmentation repeats it. | blocking (#235, #188) | Held-out coverage with and without overlap. | #235 manifest gives each well-year one role; augmentation dropped for the pilot; #188 (b) blocked by #235 and MF-11. |
| B4 | `nwis_gwlevels_domain_monthly.parquet` holds site-month medians, not samples. | blocking (#9, #188 b) | On recorders, (monthly median − assigned-day value) vs R. | #9 and #188: raw timestamped measurements with asynchronous operator, or a monthly-mean operator with the median-mean gap in R. |
| S1 | Identifiability: K–recharge trade-off; dv/v sees Δh only through a fixed k_sat; GNSS basin loading likely below noise (reviewer's elastic half-space estimate ~0.1 mm vs 1–3 mm daily noise). | should-fix | FOSM data worth per parameter; MF-14 OSSE with DFS per sensor. | MF-10 data worth; #198 coefficients in the ensemble; GNSS stays a hypothesis until #226 shows sensitivity. |
| S2 | `dvv_coupling.invert_dvv` retrieves DTW using a model baseline and calls it independent. | should-fix | — | #198: forward operator only in the filter, anomaly against the same reference window, AR(1) bias state. |
| S3 | Correlated errors in overlapping dv/v stacks, filtered baseflow, rating curves, static representativeness. | should-fix | Lag-1 innovation autocorrelation per stream. | #188: non-overlapping stacks, gauges as total SFR outflow in the filter, per-well offsets in IES only. |
| S4 | Same as H4. | should-fix | OSSE with truth differing in the last 60 days of infiltration. | #188 (a). |
| S5 | Hard localization zeros across layers and unconnected models ignore shared-forcing covariance (L ≈ 12 km). | should-fix | N = 1000, two unconnected models with correlated forcing. | Plan §3.8: taper, keep vertical coupling, declared approximation. |
| A1 | GRACE mascon larger than the domain. | advisory | — | Plan §4: context only, not validation. |
| A2 | IES assumes no model error; the filter carries Q. | advisory | — | Recorded in §3.8. |
