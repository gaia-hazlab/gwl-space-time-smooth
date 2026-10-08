# Lens: geohydrology-budget

# Geohydrology and water-budget closure in the GAIA soil-state twin: hydrogeologist's assessment

Code is cited by file:line in the origin/main checkout (`scratchpad/main`, HEAD 435445f). I wrote and ran two probes, `scratchpad/wf/geohydro/probe_budget.py` (results are in `probe_budget_results.json`) and `probe_sy.py`. I only read the repos and GitHub; nothing was written to either.

## 1. What the model is today

`coupled_water_budget` (src/models/water_budget.py:119-284) runs one column per 90 m cell. Each column has two stores:

- **Root zone** S, between θ_wp·z and θ_sat·z, with z = SOLUS root depth.
- **Water-table head anomaly** h, a linear reservoir. Depth is wt = d0 − h.

Each step runs in this order:

1. Capillary rise is added to S (:215-219).
2. Saturation-excess "VSA" runoff = [input − 1000·S_y·wt]_+ (:229-231). Root-zone overflow is added to it (:236).
3. AET = min(PET, S − S_wp). There is no stress function (:238).
4. Drainage above field capacity, at e-folding τ = 2 d (daily mode) or 60 %/month (monthly mode), is split. Interflow f_lat = Ka·tanβ/(1 + Ka·tanβ) is removed from the system, and the remainder becomes recharge (:247-250).
5. h += R/S_y (:266).
6. Groundwater relaxes toward HAND with coefficient (R_ref/S_y)/[HAND − d0]_+ (:188-197, :269-273). Baseflow is recorded as S_y·drop (:278).

Outside this function:

- Snow is a separate degree-day pre-processor (forecast.py:105-131). SWE starts at zero and is neither returned nor carried between runs.
- The shipped 90 m θ product is a third model, `total_water_bucket` (soil_moisture.py:162-190). It returns no outflow fluxes.
- `topmodel_watertable` is a static prior.
- `accumulate_runoff` is a display weighting (water_budget.py:300-311).

There is **no cell-to-cell exchange of any kind**. Runoff, interflow and baseflow leave the domain in the step they are generated.

## 2. Reproducing the reported defects (my probe)

**Capillary rise creates water: reproduced.** I defined total water as S + 1000·S_y·(wt0 − wt) and compared it with the boundary fluxes (input − runoff − AET − interflow − baseflow).

- In one dry month (P = PET = 0, θ0 = θ_wp, wt0 = 0.5 m) the residual is **+22.50 mm created**, exactly the capillary flux. Divided by 30.44 that is 0.7392 mm/day, matching the 2026-09-10 audit's 0.7392331958 mm.
- Over 300 dry daily steps, creation for wt0 = 0.3/0.5/1.0/1.5/1.99/3.0 m is 209.8/187.6/128.3/65.3/1.3/0 mm. Each value equals Σcap to 3 decimals.
- Every non-capillary branch closes to ≤ 5e-5 mm (ridge/midslope/terrace cells). **The leak is exactly the missing groundwater debit and nothing else.**

The cause is that :217-219 credits S, while h changes only at :266 and :273.

**Valley-cell bug: reproduced. Issue #177 m5 misdescribes it.** Where HAND ≤ d0, gw_recess = 0 (:195-196), so there is no groundwater sink at all.

- With zero forcing for 10 years (monthly, HAND = 0, d0 = 0.5 m), the table rises from 0.48 m depth to **4.90 m above the land surface**. That is 1630 mm of created water, cycled through capillary rise → drainage → recharge, with zero baseflow. This is a perpetual-motion loop. The legacy branch with the same forcing creates 1406 mm.
- In a wet synthetic year (P = 1269 mm), the HAND = d0 and HAND = 0 valley cells sit at the surface (wt ≈ −0.025 m) and **create 290-297 mm/yr (≈23 % of P)**. Their baseflow is zero and BFI = 0.
- A terrace cell with HAND = 4 m < d0 = 6 m has no capillary rise and no sink. Its table rises 1.96 m in one year (587 mm of recharge stored with no exit) and keeps rising.

So the comment at :264 ("valley floors cannot rise at all") is false. The #177 m5 description ("frozen ... VSA caps rise") is wrong too: VSA stops infiltration, but capillary rise keeps feeding the table. This is a P0 conservation defect, not a P2 "verify the spatial bias" item. I did not have the domain rasters, so **the fraction of the 3.0 M cells with HAND ≤ d0 still needs to be computed**. It is likely large on Puget valley fill, where the twin's liquefaction and flood products matter most.

**The HAND sink mines baseline storage, and the calibration hides it (new finding).**

- In a cell at its baseline, drop = r_ref/S_y, so baseflow = R_ref = 3 mm/day exactly, whatever the recharge.
- The relaxation time is S_y·head0/R_ref: 50 d for head0 = 0.5 m, 2000 d for 20 m, 6000 d for 60 m.
- So on ridges, baseflow is effectively a prescribed ~1095 mm/yr drain.
- In the synthetic year, the ridge cell receives 339 mm of recharge but discharges 1072 mm of baseflow. It loses ~732 mm of groundwater storage (table −2.44 m), and Q = 1343 mm > P − AET = 611 mm. Midslope is −588 mm and toe −300 mm.
- The comment at :87 says ~1.6 mm/day, but the value at :88 is 3.0.

Modelled BFI is therefore largely a readout of R_ref and of storage depletion. The equilibrium head above drainage is head0·R̄/R_ref, which is unstable unless mean recharge is exactly 3 mm/day everywhere.

**Other leaks and inconsistencies:**

- `accumulate_runoff` turns 100 mm into 155 mm (+55 %, up to 2×).
- `total_water_bucket` (the shipped θ) receives 600 mm, drains 360 mm without reporting it, and deletes 70 mm at the clip in :188.
- A forecast launched over an existing snowpack melts 0 mm, because SWE starts at 0 (forecast.py:123).
- Two snow parameter sets coexist: soil_moisture.py:199-202 uses −1/3/0 °C and forecast.py:58-61 uses 0/4/1 °C.

## 3. Budget-term inventory for a Cascades + Puget lowland domain

| Term | Status on main | Comment |
|---|---|---|
| Rain / snow partition | Represented (forecast.py:118-120) | 4 km PRISM smears the rain-snow line (#100). No undercatch correction. |
| Snowpack SWE storage | **Outside the ledger** | Not in `WaterBudget`. Zero initial state, not carried between cycles. No rain-on-snow energy (#177 m1), no sublimation. |
| Glacier ice melt / ΔS_ice | Missing (#227) | Ice-loss baseflow in Nisqually, Carbon, White and Puyallup in Aug–Sep. Glacier basins can show Q/P > 1 in late summer. Needs its own negative storage term, not a source. |
| Canopy interception and evaporation; fog drip | Missing (#225) | Old-growth Douglas-fir interception loss is of order 20-25 % of gross rain (Link et al. 2004, Wind River; *verify*). Leaving it out over-supplies winter input. The calibration absorbs this through Ka and R_ref. Fog drip is minor here. |
| ET | Represented, crudely | Hargreaves-Samani PET (fetch_prism_daily.py:42-56; forecast.py:12 says Hamon). Hard cap min(PET, S − S_wp), no stress function, no snow-cover suppression, ET only from the root zone. |
| Infiltration excess | Missing (#57, #132) | Correct at a daily step, wrong for sub-daily and post-fire triggering. |
| Saturation excess | Represented but **double-counted** | Deficit S_y·wt includes root-zone pore space that :235-236 handles again. At wt = 5 m the deficit is 1500 mm, so VSA almost never fires (#173). |
| Interflow | Represented as an instantaneous loss | No store, no routing to downslope cells (#174, #133, #130). Ka = 2 is below the 10-100 literature range (:77-82). |
| Vadose transit (root base → table) | **Missing** | Recharge teleports to the table (#131, #87 duplicate, #172). |
| Recharge | Represented | Fraction 1 − f_lat of drainage. |
| Lateral groundwater flow | **Missing** | Each cell drains toward its own HAND datum. Water leaves the domain at once and is not delivered to the stream cell. No Dupuit/Boussinesq, no convergence, no regional flow paths. |
| Inter-basin and deep regional flow to Puget Sound; submarine groundwater discharge | Missing | #10 adds a sea-level boundary only as a soft prior for interpolation, not in the dynamics. |
| Stream-aquifer exchange | **One-way only** | to_river is clipped at 0 (:271), so streams can never lose water to the aquifer. Losing reaches on recessional outwash are not representable. |
| Seepage face / exfiltration | Missing | This is the root cause of the valley bug. A table above the surface must become return flow. |
| Pumping and irrigation return | Missing | Wells with a pumping qualifier are dropped as observations (download_nwis_domain.py:40) but there is no sink. Locally important in the lowland. |
| Confined (Qva) vs unconfined (Qvr) aquifers; till leakance | Missing (#46, #50) | One unconfined reservoir with one uniform S_y. |
| Hydrothermal inflow at Rainier | Missing (#228 R6e) | Probably negligible in volume (Frank 1995; *verify*). Useful as a tracer, not a budget term. |
| Channel storage and routing | Missing (#199-#202) | Gauges cannot be compared at native support without it. |

## 4. What "budget closure" must mean operationally

**Level 1: model ledger, per column and per step.** One water-equivalent storage vector:

x = [ice, SWE (ice and liquid), canopy, ponded, root zone, vadose transit, perched, unconfined aquifer, confined aquifer, channel]

Every internal transfer (capillary rise, recharge, leakage, exfiltration, lateral exchange) is debited from one store and credited to another. ΔΣx = boundary fluxes (P, ET components, outlet discharge, coastal/SGD, pumping, prescribed inter-basin and hydrothermal inflows) + logged DA increments (#187, #188). Gates:

- Residual ≤ 1e-6 mm per step in float64, accumulated in float64 even if fields are stored as float32.
- A zero-forcing test creates nothing, in every branch: legacy, HAND, valley, terrace, wt < 0, θ at its bounds.
- Daily and monthly runs agree under timestep refinement, or the monthly path is retired (#89).
- Every store is clipped by flux limiting, never by deleting water.

**Level 2: domain ledger.** Once lateral exchange exists, interior exchanges sum to zero over the grid. Only outlet, coast and boundary fluxes remain, and inter-basin boundary fluxes are explicit terms.

**Level 3: closure against independent data.** This is a skill metric, not an identity:

- Close P − ET − Q − ΔS over **water years (Oct–Sep)** on gauged basins that were **not used in calibration**.
- Q must be **routed** simulated discharge. BFI must come from applying the same Lyne-Hollick filter to the simulated hydrograph, not from the model's internal "baseflow" store.
- ΔS_snow comes from SNOTEL and a SWE reanalysis, ΔS_soil from probes, ΔS_gw = S_y·Δh at **screened unconfined wells only** (#9, #46).
- Realistic tolerances are limited by PRISM P in the Cascades, which is uncertain by roughly 10-30 % in orographic and snow terrain. Annual |Q_sim − Q_obs|/Q_obs ≤ 10-15 % at held-out gauges is a demanding but meaningful target. Event peaks need routing.
- GRACE cannot close this domain. 141 × 170 km ≈ 24,000 km² is well below GRACE's effective footprint of order 10⁵ km². GNSS loading (#226) is the right regional total-water-storage constraint, with snow and hydrology loading separated.

**What cannot close until topology changes:**

- Gauge budgets, until there is routing plus lateral groundwater.
- Lowland basins with losing streams, pumping, or inter-basin and Puget Sound outflow.
- Glacier basins, until ΔS_ice is a store.
- Any basin while valley-cell creation and baseline mining persist.

## 5. Circular calibration and validation

`notebooks/calibrate_fluxes.py:85-86` fits Ka, R_ref and S_y on a 5×4×6 grid against **all four** reported metrics: BFI, Q/P, amplitude and peak month. So every number in the docs/twin/03a-physics-hydrology.qmd:216-222 "closed against observations" table is a calibration target. None is a validation.

Further problems:

- The window is one ~10-month period (prism_daily_2025-09_2026-06; :44).
- Fluxes and rise are domain-mean over every sixth land cell (:45, :71-77). That contradicts 03a:229-234, which says comparisons use basin-own precipitation and are made at well locations.
- Model BFI is the store ratio, not a filtered hydrograph.
- There is no check that ΔS ≈ 0, so BFI can be bought with storage depletion (§2).
- S_y = 0.30 is above the Saxton-Rawls drainable porosity (θ_sat − θ_fc) of loam (0.18), silt loam (0.17), clay loam (0.12) and clay (0.09). It is plausible only for sandy loam to sand or clean outwash, and is implausible for till uplands (S_y ≈ 0.02-0.1).
- `notebooks/close_basin_budget.py:85-95` is stale: no snow, S_y = 0.10, Ka = 20, bf_mod hard-coded to 0, and an "observed residual" P − Q that ignores ET.
- #202 says "reuse D7 BFI/Q–P calibration", which repeats the circularity unless gauges are held out.

## 6. Is the issue set one coherent topology?

**No. It is a set of interacting patches** to one ~100-line loop, written by different reviewers (groundwater M1-M5 and C1-C3, landslide M2/M3, rainier3d leverage). Several groups target the same missing store:

- **Vadose/transit store:** #172, #131, #87 (duplicate), and #173's deficit fix all need it. #137's S_y separation and #176's hysteresis in the dynamics depend on it.
- **Perched/interflow store:** #174, #130 and #133.
- **Aquifer-stream boundary:** #175 (nonlinear recession), #10 (stream and coastal boundaries, but only for interpolation) and #177 m5 (valley). Nonlinear recession should *emerge* from lateral Boussinesq drainage, not be imposed.
- **Top-of-column stores:** #225, #227 and #100. #100 itself warns that it must precede calibration.

#187 already sketches a storage state [S_root, S_vadose, S_gw, SWE, S_interflow]. It omits ice, canopy, channel and confined-aquifer stores, and it defers the partition to #171/#172.

There is **no issue at all** for:

- lateral groundwater exchange;
- seepage-face exfiltration;
- two-way stream-aquifer exchange;
- pumping;
- carrying the SWE state across forecast cycles;
- a dynamic coastal boundary.

The routing pilot #200/#201 is held behind the ensemble forecast #191 (gaia_group_issues.py:104-106). So no routed hydrograph can exist to validate #137.

**The GAIA queue makes this worse:**

- Within a milestone, chunks follow reverse issue number (gaia_group_issues.py:212-219). Batch 6 = [#227, #225, #177, #176] therefore runs **before** batch 7 = [#175, #174, #173, #172] and batch 8 = [#137, #131].
- Glacier and canopy stores would be bolted onto a leaky ledger. #225 depends on an "S1a/S1b" branch, `work/storage-conservation-2026-09-10`, that I could not find in the origin or local refs.
- The prose "Blocked by: #223" in #225 and #227 is not parsed. Only the hard-coded BLOCKED_BY table at :86-107 is used.
- #89 (batch 36), #87 (batch 36) and #100 (batch 15) run *after* the #137 calibration (batch 8).
- #172-#175 land in **one** four-issue PR on the same function. This invites incoherent coupled edits.

**Recommended consolidation.** First a needs-human-decision design record (the #171 epic rewritten): the store topology, ledger, boundary types, and the adopt-or-build decision. Then these slices, in order:

1. Ledger and conservation harness, capillary debit, seepage-face exfiltration replacing the valley no-sink, retiring monthly or making it consistent (#89), one θ product (#52, #177 m2), deleting or relabelling `accumulate_runoff`.
2. SWE state carry plus #100, then #227 and #225.
3. Vadose transit store: #172 + #131 + #173, closing #87 as a duplicate. Use pressure-wave (kinematic) celerity, not particle travel time. At recharge flux ~1.5 mm/day and θ ~0.15, particle velocity is ~10 mm/day (years per 10 m), but head responds in weeks to months.
4. Perched/interflow store with D∞ routing: #174 + #130 + #133.
5. Aquifer: lateral Dupuit-Boussinesq, river-conductance two-way exchange, coastal Dirichlet, pumping. This also covers #175.
6. Deterministic routing pilot, decoupled from #191.
7. #137 held-out calibration on routed Q.
8. #176.

Add the matching BLOCKED_BY entries before launch.

## 7. Target store topology

**Per column (90 m):** glacier ice/firn (mask) → SWE (energy-aware, rain-on-snow) → canopy (Rutter/Gash with LAI capacity; interception evaporation is its own ET term) → ponded/infiltration partition (Green-Ampt at sub-daily intensity, plus saturation excess from the true deficit) → root zone (1-2 layers, ET with a stress function, K(θ) drainage from SOLUS/POLARIS) → deep vadose transit (thickness D − z_r, kinematic or Nash cascade, storage counted in the fillable deficit) → perched/interflow store on the soil-bedrock or till contact, routed downslope cell to cell (transmissivity × slope) to produce convergence head for factor of safety.

**On a hydrogeologic grid** (90 m for the shallow unconfined layer on hillslopes and valley fill; 270 m-1 km for deep units):

- unconfined aquifer (Qvr, alluvium, colluvium, weathered rock) with 2-D Boussinesq lateral flow;
- leakance through the Vashon till to a confined Qva / fractured bedrock layer;
- seepage-face exfiltration to the surface;
- river-conductance exchange with NHD channel cells, in both directions;
- coastal head at mean sea level;
- pumping sinks;
- prescribed inter-basin and hydrothermal inflows.

Channel routing (Muskingum-Cunge) carries flow to the gauges. Storage is the evolving state; head, DTW and pore pressure are diagnosed from it (hydro_state.py:158-204 already provides storage ↔ head with S_y bounds).

## 8. Build vs adopt or benchmark

- **DHSVM (PNNL).** What I'm sure of: it was built for PNW forested mountain catchments at 30-150 m; it has two-layer canopy interception, an energy-balance snow model, multi-layer unsaturated soil, cell-to-cell saturated subsurface flow with transmissivity decay, and road and channel networks; it has been widely run on Cascade and Puget basins. To verify: the maintenance state of the glacier variant (DHSVM-GDM). Limitation: no deep regional aquifer (impermeable bedrock base).
- **ParFlow-CLM.** Sure: integrated 3-D variably saturated flow, overland flow, regional groundwater, CLM snow and ET. At 90 m over 24,000 km² it is roughly 3 M columns × 10-20 layers, so HPC-feasible but dominated by the unknown 3-D K field. The repo uses the HydroGEN/Ma WTD only as a static prior (src/features/align_hydrogen.py, interpolate_baseline.py). To verify: the product's resolution and version (1 km CONUS2 simulation vs 30 m ML), its licence (rainier3d notes a CC-BY-NC-ND layer), and whether transient HydroGEN/CONUS2 outputs exist for WA.
- **tRIBS and PIHM/MM-PIHM.** Physically appropriate (TIN or finite-volume integrated surface-subsurface). Less PNW track record; the snow modules need checking.
- **mHM.** Strong for regionalised, multi-basin calibration (MPR), but conceptual and usually run at ≥ 1 km. It does not supply lateral groundwater at 90 m.
- **USGS GSFLOW/MODFLOW models** for Puget sub-areas (for example Kitsap and Chambers-Clover; *verify* the citations) and the NWM retrospective provide **independent** recharge, stream-leakage, pumping and Q benchmarks.

**Recommendation.** Keep the light Python model as the DA and ensemble emulator; that is the twin's distinctive value. Fix its ledger and adopt the topology above. **Benchmark it against DHSVM** on one or two pilot basins (Nisqually or Puyallup for glacier and snow; a lowland outwash basin for lateral groundwater and pumping), and against ParFlow/HydroGEN for steady-state WTD. Do not have GAIA agents invent lateral groundwater from scratch before a human makes this decision.


## Claims (with adversarial verdict)

- **geohydrology-budget-1** [critical] [confirmed] Capillary rise creates water: it is credited to the root zone but never debited from groundwater head; the ledger residual equals sum(cap_rise) exactly, and every other branch closes to <=5e-5 mm.
  - evidence: water_budget.py:217-219 credits S; h changes only at :266 and :273. Probe wf/geohydro/probe_budget.py: one dry month at wt0=0.5 m creates +22.50 mm (/30.44 = 0.7392 mm/day, matching the 2026-09-10 audit). 300 dry days creates 209.8/187.6/128.3/65.3/1.3/0 mm for wt0=0.3-3.0 m.
  - issues: #172 must carry a ledger test covering all branches and zero forcing, not just a one-line debit (the followup review found a 0.004 mm legacy residual after the debit). Fix the claims at water_budget.py:30-33 and 03a:83 that the budget is 'exact by construction'. Should run before #225/#227.
  - verifier: water_budget.py:217-219 adds cap_eff to S. h changes only at :266 (+rech/Sy) and :273 (-drop), so no debit. I re-ran the probe (copy in wf/verify-geohydrology-budget/probe_copy.py) and it reproduces the numbers: A gives 22.50 mm per dry month (= 0.7392 mm/day, matching soil-twin-audit-followup-2026-09-10.md:16). B gives 209.8/187.6/128.3/65.3/1.3/0 mm, and every residual equals sum(cap). Nit: the terrace residual is 5.27e-5, slightly above the claimed 5e-5. That is float32 output noise, not a leak. The 0.00404 mm residual left by the proposed one-line debit is recorded in soil-twin-operational-plan.md:44. The 'exact by construction' text is at water_budget.py:30 and 03a:83-84. Additional probe: a valley cell (HAND=0, d0=0.5 m, P=0, PET=1 mm/d, daily, 10 yr) keeps its table fixed at 0.5 m while it creates 2629 mm of capillary water and evaporates 2809 mm. Under realistic PET the leak therefore shows up as phantom ET, not as a visible table change. #172 already names the missing debit.
- **geohydrology-budget-2** [critical] [confirmed] Cells with HAND <= d0 have no groundwater sink. With zero forcing, the capillary->drainage->recharge loop raises a valley table 4.9 m ABOVE the land surface in 10 years, creating 1630 mm. In a wet year valley cells create 290-297 mm/yr (~23% of P) with BFI = 0. Terrace cells (HAND < d0) accumulate recharge without bound (+1.96 m/yr).
  - evidence: water_budget.py:193-196 (gw_recess=0 where head0<=1e-3) and :271 clip. Probe sections C, D, E. This refutes the comment at :264 ('valley floors cannot rise at all') and the #177 m5 description ('frozen').
  - issues: Take m5 out of #177 (P2) and make it a P0 bug: add a seepage-face exfiltration / return-flow sink and a stream-conductance boundary. Compute the fraction of the 3.0 M cells with HAND<=d0 from the domain rasters (not done here).
  - verifier: water_budget.py:193-196 sets gw_recess=0 wherever head0=clip(HAND-d0)<=1e-3. That makes drop=0 permanently, even after the table rises above HAND (to_river>0 times 0). Reproduced: D (zero forcing, monthly) moves wt from 0.48 m to -4.90 m and creates 1629.7 mm. C gives the valley cells 290/297 mm created (22.9%/23.4% of P=1269) with BFI 0. The terrace cell gains 587 mm of recharge, a 1.96 m rise, and has no sink at any head. The :264 comment and the #177 m5 word 'frozen' are both wrong. Caveat: the 4.9 m above-surface rise requires PET=0. With PET>0 the same leak feeds AET (see claim 1). The Sy storage law is also applied above the land surface, which is unphysical. The fraction of domain cells with HAND<=d0 was not computed: no rasters are available locally.
- **geohydrology-budget-3** [critical] [confirmed] The HAND river sink makes baseflow approximately R_ref = 3 mm/day in any cell at baseline, independent of recharge. Ridge and midslope cells therefore mine storage: a synthetic ridge cell gets 339 mm recharge but discharges 1072 mm baseflow (table -2.44 m, about -732 mm of storage, Q=1343 > P-AET=611).
  - evidence: water_budget.py:192-197 and :270-278. Analytically baseflow = R_ref*(to_river/head0), relaxation time = Sy*head0/R_ref (50 d at 0.5 m, 2000 d at 20 m). Probe section C. The comment at :87 says ~1.6 mm/day; the value at :88 is 3.0.
  - issues: #175 should state that BFI is a readout of R_ref plus storage depletion. Calibration must add a water-year dS~0 / drift constraint. Replace the anchor with lateral Boussinesq drainage to the stream cells.
  - verifier: Analytic check: at baseline d_now=d0, so to_river=head0, drop=r_ref/Sy, and bf=R_ref per step (:192-197, :270-278). Tau=Sy*head0/R_ref gives 50 d at 0.5 m and 2000 d at 20 m. Probe C ridge: recharge 339, baseflow 1072, wt 15 to 17.44 m (-732 mm), Q=1343 against P-AET=611. The comment at :87 says 1.6 mm/day while :88 sets 3.0. Qualification: 'any cell' holds only for head0>1e-3. Valley and terrace cells get zero (claim 2). #175 already flags the circular anchor. The new point is that over ~300-day calibration windows the storage mining is not penalized.
- **geohydrology-budget-4** [critical] [confirmed] Every metric reported as 'closed against observations' (BFI, Q/P, amplitude, peak month) is in the calibration objective; there is no independent validation.
  - evidence: notebooks/calibrate_fluxes.py:85-86 (objective holds all four terms). The 03a-physics-hydrology.qmd:216-222 table presents them as closure. Water_budget.py:56-61 says 'not curve-fitting'.
  - issues: #137 acceptance must freeze held-out basins, years and wells before tuning. Relabel the 03a table as calibration fit. #202 must not reuse D7 gauges as validation.
  - verifier: calibrate_fluxes.py:85-86 puts BFI, Q/P, amplitude and peak month in the misfit. 03a:217-222 presents the same four values, and the 03a:224 caption says 'closed against observations'. water_budget.py:57 says 'not curve-fitting'. The only other candidate, notebooks/close_basin_budget.py:83-95, is not independent validation of the calibrated model: it runs stale parameters (specific_yield=0.10, k_aniso=20) and hardcodes bf_mod=0.0. make_validation_figure.py reuses the calibration setup(). #171 and #175 already state the circularity.
- **geohydrology-budget-5** [major] [confirmed] The calibration compares domain-mean model fluxes and water-table rise (every 6th land cell, one ~10-month window Sep 2025-Jun 2026) with basin-gauge and well targets. This contradicts the book's statement that comparisons use basin-own precipitation and well locations.
  - evidence: calibrate_fluxes.py:44-45, 63, 71-77 vs docs/twin/03a-physics-hydrology.qmd:229-234.
  - issues: #137: score at native support (basin polygons, well cells, screened unconfined wells only per #9/#46), over multiple water years.
  - verifier: calibrate_fluxes.py:44-45 and :71-77 take domain-mean fluxes and domain-mean rise over a subsampled grid for the window prism_daily_2025-09_2026-06. Ptot (:63) is the domain-mean P, not basin P. The book (03a:229-234) claims basin-own precipitation and well locations. The basin-own-P code exists only in close_basin_budget.py, with stale parameters. Imprecision in the claim: STEP=6 takes every 6th row and every 6th column, about 1/36 of cells, not 'every 6th land cell'. Two further mismatches it misses: Ptot uses np.mean over the whole subgrid (water cells included) while Q uses land cells only, and the well amplitude target is a full-calendar climatology (see missed).
- **geohydrology-budget-6** [major] [confirmed] Model BFI is a store ratio baseflow/(runoff+interflow+baseflow) from unrouted cell fluxes. The observed BFI is a Lyne-Hollick filter applied to a gauge hydrograph. The two are different operators.
  - evidence: calibrate_fluxes.py:72-74 vs BFI_OBS defined from Lyne-Hollick (:13, :35). There is no routing in src (water_budget.py:44-45).
  - issues: Unblock a deterministic routing pilot (#200/#201) from #191 (gaia_group_issues.py:104-106) and apply the same filter to simulated Q; make #137 depend on it.
  - verifier: calibrate_fluxes.py:72-74 computes BFI=bf/(ro+it+bf) from unrouted per-cell totals. BFI_OBS comes from the Lyne-Hollick filter (fetch_usgs_discharge.py:99) applied to gauge hydrographs. water_budget.py:44-45 says routing is not done. These are different operators. The observed BFI is also computed over Sep-Mar (calibrate_fluxes.py:13), while the model ratio covers the Sep-Jun window, a further mismatch.
- **geohydrology-budget-7** [major] [confirmed] S_y = 0.30 exceeds the Saxton-Rawls drainable porosity (theta_sat - theta_fc) of loam (0.18), silt loam (0.17), clay loam (0.12) and clay (0.09). It is plausible only for sandy-loam-to-sand or clean outwash, not for till uplands (0.02-0.1).
  - evidence: wf/geohydro/probe_sy.py using soil_moisture.saxton_rawls_envelope. water_budget.py:62. One S_y does three jobs (:230, :266, :278), as #137 notes.
  - issues: #137: make S_y spatial by hydrostratigraphic unit (#50) with physical bounds, and separate it from the near-surface fillable deficit.
  - verifier: Re-ran probe_sy.py. Saxton-Rawls sat-fc: loam 0.180, silt loam 0.174, clay loam 0.122, clay 0.087; sandy loam 0.271, loamy sand 0.336, sand 0.387. So 0.30 sits between sandy loam and loamy sand, and is plausible only for coarse soils or outwash. The till range of 0.02-0.1 is a literature judgement, not checked here. The single S_y is used at :230 (VSA deficit), :266 (head rise) and :278 (baseflow). #137 and #171 already note that S_y is forced high.
- **geohydrology-budget-8** [major] [confirmed] Saturation-excess deficit S_y*wt counts root-zone pore space that the root-zone overflow also handles. At wt = 5 m the deficit is 1500 mm, so VSA almost never fires except at the surface.
  - evidence: water_budget.py:229-236. Probe section I (150/300/600/1500 mm at 0.5/1/2/5 m).
  - issues: #173 should be merged into the vadose-store slice (#172/#131): compute the deficit from the explicit vadose store.
  - verifier: water_budget.py:230-231 sets deficit=Sy*wt_depth: 150/300/600/1500 mm at 0.5/1/2/5 m. The 0-to-root-depth part of that deficit is also handled by the Ssat overflow at :235-236. A 100 mm/day storm fires VSA only where wt < ~0.33 m. This content is essentially the body of #173. The recommendation to merge it into the vadose-store slice is a judgement, though a reasonable one.
- **geohydrology-budget-9** [major] [confirmed] Groundwater-stream exchange is one-way: streams can never lose water to the aquifer, so losing reaches on Puget recessional outwash cannot be represented.
  - evidence: water_budget.py:271 to_river = clip(hand - d_now, 0). #10 only adds stream/coastal BCs to the interpolation (interpolate_residuals/baseline_regression), not to the dynamics.
  - issues: New issue: two-way river-conductance exchange plus dynamic coastal Dirichlet boundary in the aquifer store. Link #10 and #175.
  - verifier: :271 clips to_river>=0, so drop>=0 and streams can never recharge the aquifer. #10's 'Affected' list is interpolate_residuals.py and baseline_regression.py, and its stream coupling is a 'soft prior' on the interpolation, not dynamics. No open issue mentions losing reaches. The only 'losing' match is unrelated, in #187.
- **geohydrology-budget-10** [critical] [confirmed] There is no cell-to-cell water exchange anywhere: runoff, interflow and baseflow leave the domain in the step they are generated, and there is no lateral groundwater (Dupuit/Boussinesq), no convergence, and no regional or inter-basin flow to Puget Sound.
  - evidence: water_budget.py:247-279 (per-cell only). topmodel_watertable (:287-297) is a static prior. accumulate_runoff (:300-311) is a display weighting.
  - issues: No open issue covers lateral groundwater. Add one (needs-human-decision on grid and solver: 90 m shallow / 270 m-1 km deep). #133/#130 cover only interflow routing.
  - verifier: The loop at :214-279 is purely per-cell. topmodel_watertable (:287-297) is a static depth prior. accumulate_runoff (:300-311) multiplies runoff by (1+norm) and does not conserve: the probe gets 100 to 155 mm. An issue search finds no 'lateral groundwater', Dupuit, MODFLOW or regional flow. 'Boussinesq' appears only in #175, as a recession law. #130 and #133 cover perched/interflow routing only. #12 is a LandLab coordination bridge, not a solver.
- **geohydrology-budget-11** [minor] [not-checked (minor)] accumulate_runoff is not mass-conserving: 100 mm in gives 155 mm out in a 10-cell test (up to 2x).
  - evidence: water_budget.py:308-311 multiplies by (1+norm). Probe section F.
  - issues: Delete it or rename it as a display-only weighting so agents do not use it as routing. Add to #177.
- **geohydrology-budget-12** [major] [confirmed] The shipped 90 m soil-moisture product (total_water_bucket) returns no outflow fluxes and silently deletes water at the porosity clip: 600 mm in one month gives 360 mm unreported drainage plus 70 mm destroyed.
  - evidence: soil_moisture.py:183-188 and :292, :452. Probe section G.
  - issues: #52 and #177 m2: ship theta from the ledgered coupled model, or label the product as a non-conserving diagnostic.
  - verifier: soil_moisture.py:179-188: 600 mm on S0=280 gives excess 600; it drains 360 and the clip to Ssat=450 deletes 70. Callers are at :290-292 and :452. Two nuances. Draining above field capacity 'out of the system' is the documented design of this diagnostic (water_budget.py:3-5), so only the 70 mm clip loss is truly silent. And the bucket runs on the coarse driver grid (~4 km, :288 comment), with the 90 m field derived after.
- **geohydrology-budget-13** [critical] [confirmed] SWE is outside the ledger: liquid_input initialises SWE to zero and neither returns it nor carries it between runs. A forecast launched over an existing spring snowpack melts 0 mm.
  - evidence: forecast.py:123-131. Probe section H. WaterBudget has no SWE field (water_budget.py:91-102).
  - issues: New slice before #100/#227: make SWE a carried ledger state (also needed by #187/#188, which list SWE as a state). #100 calibration must precede #137.
  - verifier: forecast.py liquid_input (the function at ~:105-131) does swe=np.zeros(...) and returns only liquid. There is no SWE argument or output, and WaterBudget (:91-102) has no SWE field. A forecast started over an existing pack melts 0 mm, as probe H shows. Missed by the claim: coupled_water_budget also has no warm start for S or h. init is only 'fc'/'wp' and h=0 (:155-157), so every run cold-starts at field capacity and the baseline table, not just with zero SWE.
- **geohydrology-budget-14** [minor] [not-checked (minor)] There are two inconsistent snow parameterisations: soil_moisture.py uses T_lo/T_hi/T_melt = -1/3/0 C and calls them nominal; forecast.py uses 0/4/1 C and says they are SNOTEL-calibrated.
  - evidence: soil_moisture.py:199-202, 196-198 vs forecast.py:53-61.
  - issues: #100 / #177: one snow module and one parameter set.
- **geohydrology-budget-15** [major] [confirmed] Missing budget terms for a Cascades + Puget domain: glacier ice melt and dS_ice; canopy interception loss (order 20-25% of gross rain in old-growth Douglas-fir, Link et al. 2004, citation to verify); sublimation; infiltration excess; pumping; deep/inter-basin/submarine groundwater discharge; confined-aquifer leakance; hydrothermal inflow (likely negligible in volume, verify Frank 1995).
  - evidence: grep of src for glacier/interception/pumping/hydrothermal finds only NWIS QC qualifiers (download_nwis_domain.py:40, qc_nwis.py:56). Issues #225, #227, #228, #46, #50, #57.
  - issues: Pumping and deep/coastal outflow need new issues. Glacier must be a negative storage term in the ledger, not a source. #228 R6e stays tracer-only and low priority.
  - verifier: A grep of src for glacier/intercept/pumping/hydrotherm/sublimat/withdraw finds only the regression 'intercept' (climate_response.py:124) and NWIS pumping qualifiers (download_nwis.py:97, qc_nwis.py:56, download_nwis_domain.py:40). No open issue mentions pumping, withdrawal, sublimation, submarine discharge or leakance. Infiltration excess is already acknowledged at water_budget.py:41-44 and tracked in #57, so it is not an untracked gap. The Link et al. 2004 (~23% at Wind River) and Frank 1995 citations remain to be verified, as the claim itself says.
- **geohydrology-budget-16** [major] [confirmed] The issue set is a set of overlapping patches on one ~100-line loop, not one store topology. #172/#131/#87/#173 all target the vadose store, #174/#130/#133 the interflow store, #175/#10/#177m5 the aquifer-stream boundary, and #87 duplicates #131.
  - evidence: Issue bodies of #172, #131, #87, #173, #174, #130, #133, #175, #10, #177. #187 sketches the state [S_root, S_vadose, S_gw, SWE, S_interflow] without ice, canopy, channel or confined stores.
  - issues: Rewrite #171 as a needs-human-decision topology and ledger design record, then 6-8 dependency-ordered slices. Close #87 as a duplicate of #131.
  - verifier: Issue bodies confirm the overlap: #172, #131, #87 and #173 target the vadose store; #174, #130 and #133 the interflow/perched store; #175, #10 and #177-m5 the aquifer-stream boundary. #131 explicitly re-raises #87 ('Issue #87 was demoted...'), and #87 has no milestone, so it would be queued separately (batch 37 with #89). #187's state vector [S_root, S_vadose_or_transit, S_groundwater, SWE, S_interflow, bias] has no ice, canopy, channel or confined store. The topology-first rewrite of #171 is a recommendation.
- **geohydrology-budget-17** [critical] [confirmed] The GAIA queue runs glacier and canopy (#227, #225) plus #176/#177 in batch 6, BEFORE the storage foundation #172-#175 (batch 7) and #137/#131 (batch 8). It runs #100 at batch 15 and #89/#87 at batch 36, all after calibration #137.
  - evidence: queue_sim.jsonl batches 6-8, 15, 36. gaia_group_issues.py:212-219 chunks in reverse issue-number order. BLOCKED_BY (:86-107) has no entries for water-budget issues; prose 'Blocked by: #223' in #225/#227 is not parsed.
  - issues: Before launch add BLOCKED_BY entries, e.g. 225:[223,172], 227:[223,172,100], 131/173/174/175/176:[172], 130/133:[174], 137:[172,131,173,174,175,100,89] plus a routing pilot. Do not batch #172-#175 into one PR.
  - verifier: queue_sim.jsonl (1-indexed) has [227,225,177,176] at 7, [175,174,173,172] at 8, [137,131] at 9, [223,100] at 16 and [89,87,21] at 37. The claim's numbers are the same order, 0-indexed. BLOCKED_BY (gaia_group_issues.py:86-107) has no key for any water-budget issue. #172, #137 and #89 appear only as blockers of #187. Worse than stated: #225 and #227 run at batch 7, BEFORE their own prose blocker #223 at batch 16. The descending member order comes from gh issue list order, not from explicit sorting in :212-219.
- **geohydrology-budget-18** [major] [confirmed] #225 (and #224/#223's ordering text) depend on 'S1a/S1b' storage work on branch work/storage-conservation-2026-09-10, which does not exist in the origin or local refs of the twin repo.
  - evidence: reviews/docs/reviews/2026-09-28-rainier3d-leverage/README.md:13, 106. `git branch -a` in scratchpad/main and the local repo shows no such branch. docs/storage-conservation-contract.md and tests/test_water_budget_conservation.py named in #225 are absent on main.
  - issues: Fix #225: point it at #172 (or a new ledger-harness issue) and hold it until that lands.
  - verifier: The leverage README (line 13) says S1a/S1b live on work/storage-conservation-2026-09-10, unmerged, and :106 gates R3 on it. git branch -a in scratchpad/main and in the local repo shows no storage or conservation branch, and git log --all has no matching commits. docs/storage-conservation-contract.md and tests/test_water_budget_conservation.py are absent on main. soil-twin-operational-plan.md:44 maps S1 to #172/#89/#137, which supports repointing #225 at #172. The #223/#224 bodies only carry the shared ordering list; they do not themselves depend on S1.
- **geohydrology-budget-19** [major] [confirmed] The existing conservation test checks only the root-zone store with no slope or HAND, at a 5 m table where capillary rise is zero, so it cannot detect the capillary or valley leaks.
  - evidence: tests/test_water_budget.py:26-33 (wt_depth0_m=5.0, reach = 1+1 = 2 m); test_capillary_rise (:49-56) checks only that cap>0.
  - issues: The ledger-harness slice must include total-storage (all stores) tests: zero forcing, every branch, wt<0, timestep refinement.
  - verifier: tests/test_water_budget.py:26-33 checks dS = cap + P - runoff - aet - recharge on the root zone only, with no slope and no HAND, at d0=5 m. Probe: cap=0 there, min wt 4.72 m. The deeper reason it misses the leak: cap_rise is treated as an external input. Re-running the same test at d0=0.5 m still passes (residual 2.9e-5) with 624 mm of capillary water created. A total-storage ledger is needed, not just a shallower table.
- **geohydrology-budget-20** [major] [confirmed] The deterministic routing pilot (#200/#201) is held behind the ensemble-forecast issue #191, so no routed hydrograph can exist when #137 (batch 8) calibrates against gauges.
  - evidence: gaia_group_issues.py:104-106 (200:[187,191], 201:[200]). queue_held.txt.
  - issues: Split #200/#201 into a deterministic routing pilot without #191 dependence, sequenced before #137.
  - verifier: gaia_group_issues.py:104-106 sets 200:[187,191], 201:[200], 202:[201]. queue_held.txt holds #200, #201 and #202 behind #187/#191, while #137 is queued at batch 9 (1-indexed). No routed hydrograph can exist when #137 runs.
- **geohydrology-budget-21** [major] [partially] The vadose lag fix (#131/#87) should use pressure-wave (kinematic) celerity, not particle travel time. Particle velocity at ~1.5 mm/day flux and theta ~0.15 is ~10 mm/day (years per 10 m), while head responds in weeks to months.
  - evidence: #87 proposes t_lag = (wt-root)/v_perc. Physics: kinematic celerity dK/dtheta exceeds the pore-water velocity q/theta by a factor of several for Brooks-Corey exponents.
  - issues: Put this in #131's acceptance: celerity-based lag or Nash cascade, validated on continuous well hydrographs, with a 3-30 day sensitivity analysis.
  - verifier: The physics is sound. Particle velocity 1.5/0.15 is about 10 mm/d, roughly 2.7 yr per 10 m. Brooks-Corey celerity is about n*q/theta with n~7-13, giving ~70-130 mm/d and roughly 2.5-5 months per 10 m. But the claim misstates #87: it proposes v_perc 'from Ksat and the moisture state (a Green-Ampt / kinematic wave estimate)' or a Nash cascade, so the kinematic option is already named. #131's acceptance already requires the 3-30 day sensitivity and validation on a continuous well hydrograph. The new content is narrower: explicitly reject particle travel time, and note that macropore and preferential flow in forest soils may shorten the lag further.
- **geohydrology-budget-22** [minor] [not-checked (minor)] GRACE cannot close this domain's budget: 141 x 170 km is about 24,000 km2, well below GRACE's effective resolution (order 1e5 km2). GNSS loading (#226) and basin-scale SWE/well/gauge storage terms are the feasible total-storage constraints.
  - evidence: src/config/domain.py:17 (141 x 170 km, ~3.0 M cells). #29 lists GRACE for native-scale validation.
  - issues: #29: drop GRACE as a domain-closure constraint and keep it only as a regional context check. #226: separate snow loading from hydrology loading.
- **geohydrology-budget-23** [minor] [not-checked (minor)] close_basin_budget.py is stale and should not be cited as closure evidence: no snow partition, S_y=0.10, Ka=20, bf_mod hard-coded to 0, and 'observed residual' P-Q ignores ET.
  - evidence: notebooks/close_basin_budget.py:40, 64-66, 83-96.
  - issues: #177: retire it or rewrite it as the Level-3 water-year closure on held-out basins.
- **geohydrology-budget-24** [major] [partially] Recommended target is DA-friendly per-column stores (ice, SWE, canopy, ponded, root zone, vadose transit, perched/interflow routed downslope) over a hydrogeologic grid (unconfined Boussinesq plus confined/bedrock with till leakance, seepage face, two-way river conductance, coastal head, pumping) with channel routing. The light Python model should be benchmarked against DHSVM on 1-2 pilot basins and ParFlow/HydroGEN for steady-state WTD rather than replaced.
  - evidence: Synthesis of the gaps above. DHSVM is PNW-proven at 30-150 m but has no deep aquifer; ParFlow-CLM is integrated but HPC-heavy and K-field-limited; the HydroGEN product version, resolution and licence must be verified (align_hydrogen.py; rainier3d notes a CC-BY-NC-ND layer).
  - issues: Make this a needs-human-decision issue (adopt/benchmark vs build) before agents implement lateral groundwater. Add a DHSVM benchmark issue for the Nisqually/Puyallup glacier-snow basin and one lowland outwash basin.
  - verifier: This is a design recommendation, so it cannot be verified as a fact. The checkable parts hold. src/features/align_hydrogen.py exists. The Ma et al. 2026 WTD is CC-BY-NC-ND (rainier/docs/data_policy.md:23, paper:189, :991), and rainier3d uses Fan et al. 2017 instead (configs/cz.yaml:68). No DHSVM issue exists. The DHSVM and ParFlow characterizations are generic literature knowledge and were not checked against sources here.

## Verifier: missed problems

- No warm start for any state: coupled_water_budget accepts only init='fc'/'wp' and h=0 (water_budget.py:155-157), and liquid_input zeroes SWE. Every forecast or calibration run cold-starts at field capacity and the baseline table, so it cannot be initialized from an analysis or DA posterior (#187/#191) without a state-in/state-out interface. This should block #188/#191, not just #100.
- Calibration window mismatch: the model amplitude and peak come from monthly means of one Sep 2025-Jun 2026 run (calibrate_fluxes.py:44, :76-80; Jul/Aug missing). The 1.06 m observed amplitude is a full-calendar multi-year climatology of shallow-well anomalies (make_validation_figure.py:51-54). The observed BFI is Sep-Mar (calibrate_fluxes.py:13), while the model ratio is Sep-Jun. All three targets compare different time supports.
- Q/P denominator inconsistency: Ptot = nansum(P.mean(axis=(1,2))) over the entire subsampled grid, with plain mean (so any NaN cell propagates), while Q is a land-only nanmean (calibrate_fluxes.py:63, :71-75). Depending on PRISM masking over Puget Sound, Ptot is either biased or NaN, and the Q/P term could be degenerate. This could not be checked without the data.
- R_ref=3 mm/day (~1100 mm/yr) as the baseline baseflow leak is a large share of PNW lowland P (~900-1500 mm), and equilibrium head scales as head0*Rbar/R_ref. Over the 300-day calibration window this drift is invisible, so a multi-year spin-up/drift test (wt trend ~0) should be an acceptance criterion in #175/#137.
- accumulate_runoff (water_budget.py:300-311) does not conserve mass: 100 mm in gives 155 mm out (probe F). It is used for display, but any downstream use (landlab_export, #200) would inflate runoff. Flag it before #200/#201.
- Above-surface tables: when wt<0 the code keeps using Sy for storage (:266) and VSA routes all input to runoff. There is no ponding store, no porosity-1 storage and no exfiltration. Combined with the gw_recess=0 valley mask this permits metres of 'groundwater' above ground. #10's acceptance (DTW<0 in <0.1% of cells) should be tested on the dynamic model, not only on the interpolant.
- notebooks/close_basin_budget.py, the only basin-own-P closure, is stale: it uses specific_yield=0.10 and k_aniso=20 rather than the calibrated values, and it hardcodes bf_mod=0.0 (:86, :94). Agents taking #137/#202 may treat it as a validation harness. It needs updating or retiring.
- The GAIA queue places #225/#227 (batch 7) before their own declared blocker #223 (batch 16), not only before #172. Prose 'Blocked by' lines are ignored, so every Rainier slice #224-#228 needs explicit BLOCKED_BY entries.
