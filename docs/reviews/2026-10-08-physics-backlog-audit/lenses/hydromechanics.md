# Lens: hydromechanics

> **PI correction (Marine Denolle, 2026-10-08):** claim hydromechanics-5 overstates the result. dv/v sensitivity depends on band and is never zero at shallow depth; Illien et al. (2021) show 4-8 Hz dv/v is sensitive to vadose-zone moisture. Correct framing: the observable integrates the whole vadose column (m to tens of m), so the defect is the twin's missing depth-resolved vadose state and the hard-coded top-1 m kernel fraction (dvv.py:66-69), not the bands.

# Hydromechanics review: the twin's dv/v chain vs the rainier3d critical-zone (CZ) column, and what P0 #198 and the factor-of-safety (FS) path need

Lens: rock physics and geotechnical hydromechanics. All code citations are to the origin/main checkout (`scratchpad/main`) or to the rainier3d clone (`scratchpad/rainier`).

**Method and caveats (read first).**
- I read every module named in the brief, both rainier CZ docs, the paper's CZ and mass-movement sections, the relevant issues, and the GAIA queue simulation.
- I could not run numerical probes. My Python and grep commands were blocked by the permission classifier partway through. Every number below labelled "hand calc" is analytic arithmetic from the code's own equations and constants. It is reproducible but was not executed. Kernel-depth statements rely on rainier's own reported disba results (`docs/critical_zone.md:208,210`), not on a fresh disba run.
- Disclosure: one early `pip3 download disba` ran with the cwd reset to `/Users/marinedenolle/GIT_REPOS/gwl-space-time-smooth` and wrote 16 wheel/tarball files there. I deleted exactly those files at once. `git status` afterwards showed only the user's three pre-existing untracked files. Nothing else in that repo was touched.

---

## 1. What the twin implements today

**Vadose map.** `dvv_coupling._vs_vadose` (`src/models/dvv_coupling.py:80-92`):
- Effective pressure is `P_e = SIGMA0 + S_e·P_c` with `SIGMA0 = 10 kPa`, constant everywhere (`:48`).
- Stiffness follows a Hardin-type power law, `G = G_REF (P_e/P_REF)^{1/3}`, with `G_REF = 75 MPa` at `P_REF = 100 kPa` (`:45-47`).
- `Vs = sqrt(G/ρ_b)`, with ρ_b from θ.
- The suction term is the Lu–Godt–Wu (2010) suction stress with Bishop χ = S_e, written in kPa: `S_e·P_c`. So the functional form is the same as rainier's `rockphysics.suction_stress` (`rockphysics.py:62-64`). What differs is the total stress. The twin uses a single constant equal to the overburden at about 0.6 m. Rainier uses the cumulative column weight with saturation-dependent density (`medium.py:95-102`).

**Saturated band.** `dvv_low = −K_SAT·Δh` with `K_SAT = 5e-4 /m` (`dvv_coupling.py:50, 98-106`). It is one scalar, independent of depth, water-table depth, frequency band and hydrostratigraphic unit.

**Hysteresis.** `hysteresis.py` imports the same constants (`:28-36`). It is a Kool–Parker scanning model on the suction only. #176 already notes that it does not touch the water fluxes.

**Observation/DA path.** `dvv.py` uses fixed gains:
- `S_THETA = S_MATERIAL_THETA = −1.0` and `S_THETA_BAND = −0.08`, via `KERNEL_FRACTION_TOP1M = 0.08` (`dvv.py:65-69`).
- `K_SAT`, used in `dvv_to_wtd_change` (`:72-78`).
- Rayleigh kernels from codameter on a nominal profile `pnw_velocity_profile` (`:284-300`). That profile uses 10 m layers (`target_dz_km=0.01`), a 50 m top layer at Vs = Vs30, and runs to 6 km.
- Monitoring bands `DEFAULT_BANDS = (0.1–0.5, 0.5–1, 1–2, 2–4 Hz)` (`:41`).

**Forecast Vs30.** A linear depth-fraction blend, `w = root_depth/30` (`forecast.py:181-183`), applied to a 1 m single-bucket root zone (`water_budget.py:150-153, 253`).

**Soil mechanics.** `soil_mechanics.estimate_mechanics` raises `NotImplementedError` (`soil_mechanics.py:56-67`).

### 1a. Quantitative checks of the twin chain (hand calc)

**Material θ-sensitivity.** Take a loam: sand 40 %, clay 20 %, θ_wp 0.12, θ_sat 0.45. The texture heuristic gives α = 0.062 /kPa and n = 1.64 (`:73-74`).

| θ | P_c (kPa) | S_e·P_c (kPa) | P_e (kPa) | Vs (m/s) |
|---|---|---|---|---|
| 0.15 | 685 | 62 | 72 | 204 |
| 0.25 | — | 25.7 | 35.7 | 177 |
| 0.35 | — | 14.5 | 24.5 | 161 |
| 0.40 | — | 9.3 | 19.3 | 153 |
| 0.45 | — | — | 10 | 135 |

- Mean sensitivity from 0.15 to 0.40 is −25 %, i.e. **−1.01 per unit θ**. The local slope ranges from −0.9 at mid-range to −2.3 near saturation.
- So the current `S_MATERIAL_THETA = −1.0` (`dvv.py:65`) is consistent with the twin's own forward chain.
- #45's title ("S_THETA = −2.0") is stale. Its premise (compare to the observed 0.1–1 %) conflates a **material** sensitivity with a **band** observation.
- About 7 points of the 25 % come from density alone (√(1607/1857) = 0.930). The remainder is suction stress.

**G_REF and P_REF have no effect on any dv/v output.**
- The ratio `(Vs_t − Vs_0)/Vs_0` (`dvv_coupling.py:119`, `hysteresis.py:179-180`) reduces to `(P_e,t/P_e,0)^{1/6}·sqrt(ρ_0/ρ_t)`, so both constants cancel exactly.
- The magnitude of every twin dv/v is controlled by **SIGMA0, the exponent n, and the retention parameters**, not by G_REF.
- #176's instruction to "calibrate SIGMA0/G_REF" should drop G_REF.

**SIGMA0 is the dominant knob.** For the same 0.15→0.40 swing:

| SIGMA0 (kPa) | dv/v |
|---|---|
| 2 | −30 % |
| 10 | −25 % |
| 50 | −16 % |
| 100 | −13 % |
| 200 | −10 % |

The density term never decays with depth because the twin has no depth axis. A constant 10 kPa is equivalent to evaluating the whole "vadose zone" at about 0.6 m depth (σ ≈ 17 kN/m³ × 0.6 m).

**Saturated head sensitivity is depth- and water-table-dependent, not a constant.**
- In a drained Hertz–Mindlin/Hardin frame, dlnVs = (n/2)·dlnσ′ = (1/6)·dσ′/σ′. A 1 m head rise gives Δσ′ ≈ −ρ_w g(1 − S_y) ≈ −8 to −10 kPa below the water table.
- Local material sensitivity (with unit weights γ_unsat 17 and γ_sat 20 kN/m³) is 8 to 25 times K_SAT:

| Depth, water table | σ′ (kPa) | Sensitivity | Multiple of K_SAT (0.05 %/m) |
|---|---|---|---|
| z = 10 m, WT 5 m | ≈136 | −1.2 %/m | ≈24× |
| z = 15 m, WT 5 m | ≈187 | −0.87 %/m | ≈17× |
| z = 30 m, WT 10 m | ≈374 | −0.44 %/m | ≈9× |

- Rainier's own synthetic gives 0.09 %/m (permanent stations), 0.31 %/m (nodes) and 0.17 %/m (DAS) at 40 Hz, as medians (`critical_zone.md:208`). Those medians are diluted by sites whose Fan water table is more than 100 m deep.
- K_SAT = 5e-4 is therefore defensible only as a **band-integrated, low-frequency** coefficient. It cannot serve as a material value or be shared across bands.
- `forecast.py:182` applies `dvv_low` (K_SAT·Δh) as if it were δVs/Vs in every layer from 1 to 30 m. That is a category error.

**The bands cannot see the root zone.**
- `dvv_coupling.py:12` claims the "high-frequency band → shallow vadose (~1 m)". The twin's highest band is 2–4 Hz (`dvv.py:41`).
- Rainier's disba results on realistic layered columns put half the Vs sensitivity within 8.5–12 m at 10 Hz and 4–5 m at 40 Hz (`critical_zone.md:208`). At ~3 Hz the half-sensitivity depth is therefore of order 30–40 m.
- Rainier's synthetic storm (Richards plus the CZ column) gives −0.06 % at 5 Hz against −1.1 to −1.2 % at 40 Hz (`critical_zone.md:210`). Below about 5 Hz the storm-moisture signal is essentially invisible.
- `peak_depth_km` defaults to Vs = 1500 m/s (`dvv.py:45`), a crustal value that puts the 3 Hz peak at about 170 m.
- `KERNEL_FRACTION_TOP1M = 0.08` (`dvv.py:66`) is roughly what a 15–40 Hz band would give. My estimate is that it overstates the top-1 m fraction at 2–4 Hz by ×2–4. This is unverified because disba could not be run.
- The 10 m codameter grid cannot represent a 0–2 m layer at all.

**The deep aggregate is diluted.**
- `separate_depth` / `invert_states_from_bands` average the posterior over **all** nodes below the water table down to 6 km (`dvv.py:327-341, 362-370`). Nodes outside the kernel support revert to the prior mean (0), so `wtd_relative_dvv` shrinks with the depth extent of the grid.
- That aggregate is then divided by K_SAT (`dvv_to_wtd_change`). This is not a head metric.
- The synthetic truth assigns the GWL signal uniformly to every node below 30 m, down to 6 km (`dvv.py:395-400`). Physically, a drained head change produces m(z) = −(1/6)ρ_w g Δh / σ′(z), which decays roughly as 1/z.

**The Vs30 blend underweights the soft top layer.**
- Harmonic Vs30 weights a layer by h_i/Vs_i, not by h_i/30.
- With 1 m at 150 m/s over 29 m at 350 m/s, the top layer's weight is 0.0067/0.0895 = **7.5 %**, against the 3.3 % used in `forecast.py:181`. That understates storm-driven Vs30 change by ≈2.2×.
- The layer between the root zone and the water table (median water table 10 m in the Rainier box, `critical_zone.md:30`) is given the head-band coefficient instead of a vadose response.

**Missing mechanical forcings.**
- No total-stress loading term exists. Snow load (1 m SWE ≈ 9.8 kPa) on a drained frame at 2 m depth (σ′ ≈ 34 kPa) gives +4 % local stiffening. That is the same order as, and opposite in sign to, the wetting signal.
- The twin models snow hydrologically (`forecast.py:52-58`) but never as mechanical load.
- Rainier's docs flag snow loading as several % at 15–25 Hz (`critical_zone.md:127-128`).
- GNSS-scale elastic strain is a weak dv/v confounder. Areal strain has a median of 15 nε (paper:793); with a nonlinearity β ~10³–10⁴ that gives 0.0015–0.015 %. #226 is therefore a total-water-storage observable, not a dv/v correction.
- Drained vs undrained matters for clayey or lahar-cap confining units. With c_v ~10⁻⁶ m²/s and L = 5 m, the consolidation time is t ~ L²/c_v ≈ 300 days, so seasonal loads are partly undrained (B ≈ 1, Δσ′ ≈ 0). Both models are drained-only.

## 2. What rainier3d's CZ column provides

**Discretisation.** Geometric layers from 0.05 m with ×1.12 growth (`configs/cz.yaml:15-19`; `medium.fine_grid`, `medium.py:21-29`). That gives 52 layers to 150 m (paper:451), about 38 to 30 m, about 44 to 60 m.

**Layer structure.** Soil, cover, weathered and fractured layers with boundaries per column (`medium.py:32-47`). Porosity comes from SOLUS bulk density; van Genuchten parameters from POLARIS, correctly converted from 1/kPa to 1/m (`surface/soil.py:49,234`); log-permeability is blended.

**Effective stress.**
- Total stress is the cumulative column weight, including pore water and ice overburden (`medium.py:95-100`).
- Pore pressure is hydrostatic below the water table and Lu–Godt–Wu suction stress (χ = S_e) above it, weighted by the weathering index W (`medium.py:101`).
- A 1 kPa floor applies (`:102`).

**Frame.** Dvorkin–Nur soft sand on Hertz–Mindlin (`rockphysics.py:31-53`), Hill-averaged grain moduli by clay fraction, then Gassmann with a Brie patchy fluid for Vp (`:67-74`). It is blended with the crack-closure rock law by a Hill average in W at the same σ′ (`medium.py:104-125`). This continuity into L1 (Vs within 1 % at 150 m) is a real asset.

**Kernels and hydrology.**
- disba Rayleigh phase-velocity kernels on the actual layered column, 1–40 Hz (`synthetics.py:31-45`, `cz.yaml:45-48`).
- A mass-conservative mixed-form Richards/Celia solver (`richards.py`); the mass-balance error was 0.0002 mm on the December 2025 storm (`critical_zone.md:210`).
- A grid-search calibration hook against dispersion (`calibrate.py`).

**Weaknesses relevant to adopting it for #198.**
1. **Everything mechanical is a placeholder.** `m1_placeholder` covers C = 9, f = 0.5, φ_c = 0.40, Brie e = 3, layer van Genuchten and ksat, the 15 m fractured thickness and the weathering factors (`cz.yaml:2-3, 22-43, 73-90`). The stress exponent is fixed at Hertz–Mindlin 1/3.
   - Hand calc at σ′ = 10 kPa with clay 0.2, C = 9, f = 0.5: μ_HM ≈ 101 MPa and Vs ≈ 250 m/s, against 35 MPa and ≈140 m/s from the twin law. Rainier is about 2.9× stiffer in G at every stress.
   - The dv/v ratios are nevertheless identical: both use n = 1/3, so dlnVs/dlnσ′ = 1/6. Where they differ is Vs0(z), and therefore the kernels.
2. **Docstring/code mismatch in `soft_sand`.** The docstring says "above the critical porosity, Hertz–Mindlin at φ", but the code evaluates at `min(φ, φ_c)` (`rockphysics.py:45-47, 52-53`). SOLUS soil porosity has a median of 0.63 (`critical_zone.md:46`), above φ_c = 0.40, so the soil-layer frame stiffness is independent of porosity everywhere.
3. **The static saturation profile is hydrostatic equilibrium with the water table** (`medium.py:86-91`). Fan's water table is more than 100 m deep under ridges (`critical_zone.md:192-193`). Equilibrium then implies very dry, stiff near-surface soil (S_e ~0.03–0.08) and so an exaggerated wetting response. The profile must instead be driven by the twin's θ(z) and head. The `head` argument exists but only overrides the top layers (`medium.py:87-89`).
4. **Richards has no ET, lateral drainage, snow or hysteresis**, and its bottom boundary is a fixed static water table (`richards.py:8-11`). The paper says the storm numbers "illustrate the coupling, not a prediction" (paper:513-514).
5. **Kernels are Rayleigh phase velocity only.** The design calls for an Obermann coda surface/body mixture (`critical_zone.md:102`), which is not implemented. Kernels are frozen on the reference column and return NaN on `DispersionError` (`synthetics.py:22-24`).
6. **Internal inconsistency.** The storm dv/v at 40 Hz is "−1.1 to −1.2 %" in `critical_zone.md:210` but "about 2 %" in paper:513. The top-50 m Vs ratio is 0.50 in `critical_zone.md:173` and 0.58 in paper:493.
7. **The package is tied to the rainier geomodel.** It depends on the petro table, the rock law, ice and the GeMS units (`level.py:17-21, 149-167`). It cannot be imported as is into a statewide 90 m twin.

## 3. Decision on #198

**Recommendation: yes, with conditions.** Rainier3d's CZ column **equations and discretisation** should become the single reference forward operator H of #198. This means `medium.profile` (σ′(z) from column weight plus suction stress), `rockphysics`, disba kernels on Vs0(z), and harmonic Vs30.

It should be adopted as a ported, dependency-light module inside the twin, not by importing the rainier3d package. The twin supplies three things:
- the hydrologic state: θ(z) or ψ(z), head, hysteresis branch;
- a Vs0(z) anchor: a Vs30-consistent profile, or SVM/site inversion;
- a simple rock end-member, or a half-space.

**What must change first, in order:**
1. **State input.** Replace hydrostatic-equilibrium suction with the twin's θ(z)/ψ(z) and head on the operator grid. Without this the operator re-introduces the static-water-table artefact.
2. **Parameters as ensembles, not constants.** Use the stress exponent n (prior about 0.33–0.5 for G, per Makse et al. 1999 and field data), C·f (sets Vs0 only), φ_c and the soft-sand branch (fix item 2 of §2), and Brie e (Vp only). The calibration targets are n, σ′(z) and the retention parameters. G_REF/P_REF are irrelevant to dv/v.
3. **Bands.** Kernels are needed at every band actually observed. ~~For root-zone moisture this requires 5–40 Hz (DAS, nodes). Either add those bands or drop the vadose-from-dv/v claim for permanent stations at 0.1–4 Hz.~~
   > **Correction 2026-10-09 (C3; Codex review of PR #229, see `../2026-10-09-pr229-codex-response.md`).** Struck. The probe behind this (`probes/memory/probe.py`) builds kernels whose first node is at 5 m depth, so its "top-1 m" perturbation contains no node and returns exactly zero in every band. That is a discretisation defect, not zero physical sensitivity. Evaluate site-specific kernels for the bands actually observed, on a grid that resolves the top metres, then assess sensitivity, noise and which combinations of the state are recoverable before prescribing acquisition or a frequency threshold. Sensitivity alone does not show that individual depth layers are resolvable.
4. **Kernels.** Freeze them at Vs0 first (#198 already allows this). Evaluate them **only at station or footprint columns** (H is per-observation), not per 90 m cell. Per-cell Vs30(t) needs only the harmonic integral, which is cheap.
5. **Linear saturated mode.** Keep `linear_saturated`, but compute its coefficient per band from the operator, as ∫K_b(z)·(1/6)ρ_w g(1 − S_y)/σ′(z)·H(z − WT) dz. Do not use a global K_SAT.
6. **Explicit mode flags** for drained/undrained per unit (#50, #228) and for a total-stress surface load (snow, ponding).
7. **Units.** Standardise α in 1/m. The twin uses 1/kPa (`dvv_coupling.py:73`), rainier 1/m: a ×9.81 trap.

**Minimum depth discretisation.**
- **Operator (mechanical/kernel) grid:** about 40 geometric layers from 5 cm, ×1.12, to 30 m, then 2–5 m layers or L1-type cells to roughly 1.5 λ at the lowest band, ending in a half-space.
  - 5 cm top cells are needed for 40 Hz kernels (half-sensitivity 4–5 m) and for suction gradients during storms. `critical_zone.md:112-113` independently asks for 1–5 cm nodes in the top 1–2 m.
- **Prognostic hydrologic state:** at least four vertical stores with explicit depth bounds:
  - 0–0.3 m (evaporation/infiltration front);
  - 0.3 m to the soil/colluvium base z_soil (≤ 2 m; root zone, perched water above the contact);
  - z_soil to the water table (deep vadose lag store: #131, #172);
  - the saturated head.
  
  Each store is mapped onto the fine operator grid by a within-store equilibrium ψ profile. The current single 1 m bucket cannot feed #198.

## 4. What the FS path (#128, #133, #134) needs from hydrology

Infinite slope with suction stress (Lu & Godt 2008):

FS = tanφ′/tanβ + 2(c′ + c_r)/(γ H sin2β) − σ_s (tanβ + cotβ) tanφ′/(γ H),

with σ_s = −S_e ψ γ_w in the vadose zone and u = γ_w h_p cos²β for slope-parallel seepage.

**Required inputs:**
- γ(z) from θ(z);
- σ_s at the slip depth H (vadose);
- perched head h_p above the soil/colluvium–rock contact (shallow failures);
- water-table head at H (deep-seated failures);
- slip-depth classes;
- c′, c_r, φ′.

**Magnitudes (hand calc, β = 35°, φ′ = 33°, c′ = 0, γ = 18–19 kN/m³):**
- Dry FS is 0.93.
- At H = 1 m, a suction stress of −10 kPa adds +0.77 (FS ≈ 1.7). Wetting to S_e ≈ 0.9 (σ_s ≈ −2 kPa) drops FS to ≈1.08. **Suction loss is first-order for shallow slides.**
- At H = 14.6 m (median failure depth of the 453 lidar-protocol deposits, paper:1037), the same suction adds only 0.05. Full saturation (m = 1) gives FS ≈ 0.45. Each metre of water-table rise costs ΔFS ≈ −0.033.
- **Deep-seated stability therefore needs head accurate to 1–2 m at slip depth.** The twin's pooled 18.5 m RMSE (#47) is an order of magnitude too coarse in absolute terms.

**Can the current 1–2 m root zone provide these inputs? Only partially.**
- It gives a depth-averaged θ in the top 1 m (`water_budget.py:150-153, 253`). Through van Genuchten this yields S_e and σ_s for slip surfaces of about 1 m or less.
- It cannot produce positive perched pressure. Saturation excess is routed to runoff (`:236`) and interflow leaves the domain (`:248`); those are #130 and #133.
- It has no state between 1 m and the water table (#131, #172).
- It provides no colluvium thickness. Rainier's SOLUS soil thickness is capped at 2.01 m (`medium.py:37`), which suits shallow H but not deep H.

**Effect on GAIA ordering.**
- #128 is dispatched alone in the first wave (queue_sim batch 4), while #130/#133/#134 come in batch 22. An agent will build FS on root-zone θ plus the static water table.
- #128's acceptance criteria should require the suction-stress term, explicit H classes, and an interface stub for h_p. It should also state that deep-seated FS uses only the water table and inherits its σ.

## 5. GAIA queue hazards in this area

- **#198 runs too early.** It is in first-wave batch 2 together with #161/#162/#163, although its body says "Depends on #187, #176". #187 is held and #176 is in batch 7, so the grouper does not parse that list.
- **#226 is not held** despite stating "Blocked by #187 and #189".
- **The same constants are edited by different agents.** #45/#50/#30 (batch 28), #85 (batch 14) and #176 (batch 7) all touch SIGMA0, K_SAT and S_THETA in different batches. They should be folded under #198 or held until it lands, otherwise agents will tune constants that #198 is meant to retire.
- **#168 is relevant to the operator.** `DIFFUSIVITY_KM2_S = 8` and `LAPSE_TIME_S = 10` (`dvv_sensitivity.py:81-82`) imply about 18 km footprints. At 10–40 Hz, with v ~0.3 km/s and l* ~0.1 km, D ≈ 0.015 km²/s and footprints are ≈0.8 km, roughly 500× smaller in D. The spatial and depth operators must therefore be band-specific as well.

**Bottom line.** The twin's vadose physics is the right family (Lu–Godt–Wu plus a Hardin/Hertz–Mindlin exponent) but has no depth axis. Its magnitudes are set by an arbitrary 10 kPa and a scalar K_SAT, and its bands cannot see the depth it claims. Rainier3d has the right structure (σ′(z), layered, kernels on a real profile) but is uncalibrated and hydrologically static. Port rainier's column as the #198 operator, drive it with a multi-store twin state, calibrate n and σ′ rather than G_REF, and hold the constant-tuning issues until it lands.


## Claims (with adversarial verdict)

- **hydromechanics-1** [major] [confirmed] The magnitude of every twin dv/v output does not depend on G_REF or P_REF: they cancel exactly in (Vs_t - Vs_0)/Vs_0, so dv/v magnitude is set only by SIGMA0, the exponent N_EXP and the retention parameters.
  - evidence: src/models/dvv_coupling.py:89-92 (G = G_REF (P_e/P_REF)^N), :119 ratio; src/models/hysteresis.py:194-197 and :179-180. Ratio = (Pe_t/Pe_0)^{1/6} sqrt(rho_0/rho_t).
  - issues: #176: remove 'calibrate G_REF'; calibrate SIGMA0, which #198 should replace with sigma'(z), and the exponent. #30: drop G_REF from the calibration list for dv/v (it only sets the absolute Vs0).
  - verifier: I reproduced this. Changing G_REF/P_REF to (30,50), (75,100) and (200,100) gives the same dvv_high, -0.2536, for loam theta 0.15 to 0.40 (dvv_coupling.py:89-92, 119; hysteresis.py:194-197, 179-180). The 1 kPa clip does not involve P_REF. Caveat: 'set only by SIGMA0, N_EXP and retention' leaves out the density term sqrt(rho0/rho_t) (RHO_GRAIN, phi; :91) and K_SAT, which sets dvv_low entirely. #176 does ask to 'calibrate the SIGMA0/G_REF magnitude', so dropping G_REF from that issue is correct.
- **hydromechanics-2** [major] [confirmed] S_MATERIAL_THETA = -1.0 is consistent with the twin's own forward chain (hand calc, loam: -25% for theta 0.15 to 0.40, i.e. -1.01 per unit theta at SIGMA0 = 10 kPa). #45's '-2.0' premise is stale, and its comparison to the observed 0.1-1% conflates a material sensitivity with a band observation.
  - evidence: src/models/dvv.py:65-69; dvv_coupling.py:73-74, 84-92. Hand calc: Vs 204 m/s at theta 0.15 vs 153 m/s at 0.40 (alpha 0.062/kPa, n 1.64).
  - issues: #45: retitle to the material vs band convention; close as superseded by #198, or hold behind it; do not let an agent 'recalibrate' the scalar.
  - verifier: Reproduced for sand 40%, clay 20%, theta_wp 0.12, phi 0.45 (alpha 0.062, n 1.64): Vs 204.5 to 152.7 m/s, -25.4%, about -1.01 per unit theta. #45 still says S_THETA = -2.0, while the code is -1.0 (dvv.py:67-69), so its premise is stale. The material-vs-band distinction is already written into dvv.py:56-66. Caveat: -1.0 is a chord slope that depends on texture. For sand 90% / clay 3% I get about -12% over 0.05 to 0.40 (about -0.34 per unit theta), so even the material value is uncertain by about 3x, not only the band dilution.
- **hydromechanics-3** [major] [partially] The constant SIGMA0 = 10 kPa (equivalent to about 0.6 m depth) is the dominant control on twin vadose dv/v: the same theta swing gives -30% at 2 kPa, -25% at 10 kPa, -16% at 50 kPa, -13% at 100 kPa.
  - evidence: dvv_coupling.py:48, 89; hysteresis.py:194. Hand calc from the code's equations.
  - issues: #198: require sigma'(z) from cumulative column weight (as in rainier medium.py:95-102) instead of SIGMA0; add a test that dv/v decreases with depth for a fixed d(theta).
  - verifier: The numbers reproduce exactly for the lens's loam: -30.4%, -25.4%, -16.4%, -12.9% at 2, 10, 50 and 100 kPa. 10 kPa is about 0.6 m at rho about 1700. But 'dominant' is overstated. At fixed SIGMA0 = 10 kPa, plausible retention variation (theta_wp 0.08-0.14, phi 0.43-0.47) already gives -21% to -31%, and changing texture gives -12% to -31%. SIGMA0 and the retention/texture parameters are controls of similar size. #198 already writes sigma'_g(z), so the fix is in its body; the depth-monotonicity test is a good addition.
- **hydromechanics-4** [major] [partially] K_SAT = 5e-4 per m is 8-25x smaller than the local drained effective-stress sensitivity at 5-30 m depth (-0.44 to -1.2 %/m), and smaller than rainier's own 40 Hz synthetic (0.09-0.31 %/m medians). It is defensible only as a low-frequency, band-integrated coefficient.
  - evidence: dvv_coupling.py:50, 98-106; dvv.py:72-78; rainier docs/critical_zone.md:208. Hand calc dlnVs = (1/6) * rho_w g (1 - Sy) / sigma'(z).
  - issues: #50: expand to a K_b per band, per water-table depth and per unit (drained/undrained), computed from the operator; #198: the linear_saturated mode coefficient must be derived from the kernels, not a global scalar.
  - verifier: The direction holds: a drained head rise lowers sigma' by about gamma_w*dh*(1-Sy) everywhere below the table, and with G proportional to sigma'^(1/3), dlnVs = (1/6)*gamma_w*(1-Sy)/sigma'(z). With dry overburden I get about 1.5 %/m at 5 m and 0.25 %/m at 30 m (higher with buoyant stress), i.e. 5-30x K_SAT, not the stated 0.44-1.2 %/m and 8-25x. Rainier critical_zone.md:208 does give 0.09-0.31 %/m at 40 Hz. Those are band values for a 1 m shallower table clamped at the ground, a different quantity from the twin's 0.1-4 Hz band. The conclusion 'defensible only as a band-integrated low-frequency coefficient' is sound.
- **hydromechanics-5** [critical] [confirmed] The twin's monitoring bands (max 2-4 Hz) cannot resolve the 0-2 m root zone, contrary to the 'high band -> vadose ~1 m' claim. Realistic columns put half the sensitivity at 8.5-12 m at 10 Hz and 4-5 m at 40 Hz, and a storm moves dv/v only -0.06% at 5 Hz vs about -1.1% at 40 Hz.
  - evidence: dvv.py:41 DEFAULT_BANDS; dvv_coupling.py:12; rainier docs/critical_zone.md:208, 210.
  - issues: New issue (or a #198 acceptance item): add 5-40 Hz bands (DAS/nodes) for the vadose state, or restrict the permanent-station dv/v to the saturated/deep state; update #30's band-to-depth task.
  - verifier: DEFAULT_BANDS max is 4 Hz (dvv.py:42). The '~1 m vadose' high-band claim is at dvv_coupling.py:12. Rainier critical_zone.md:208/210 states half the sensitivity at 8.5-12 m (10 Hz) and 4-5 m (40 Hz), and storm dv/v of -0.06% at 5 Hz vs -1.1 to -1.2% at 40 Hz. Physically, L = Vs/3f is 17-60 m at 2-4 Hz for Vs 200-400 m/s. Minor inconsistency: the rainier paper:513 says about -2% at 40 Hz at permanent stations, while the doc table says -1.1 to -1.2%.
- **hydromechanics-6** [minor] [not-checked (minor)] KERNEL_FRACTION_TOP1M = 0.08 corresponds to roughly a 15-40 Hz band; for the 2-4 Hz band it likely overstates the top-1 m kernel fraction by about 2-4x. This is an estimate: disba was not run here.
  - evidence: dvv.py:66-69; scaling from rainier critical_zone.md:208 (half-sensitivity about 1/f).
  - issues: #45/#198: compute the fraction from kernels per band; add a test against disba.
- **hydromechanics-7** [major] [confirmed] The twin's depth-inversion grid (pnw_velocity_profile, 10 m layers, 50 m top layer at Vs30, to 6 km) cannot represent a 0-2 m layer, and peak_depth_km defaults to Vs = 1500 m/s (3 Hz peak at about 170 m).
  - evidence: dvv.py:45-47, 284-300.
  - issues: #198: require an operator grid with about 5 cm top cells growing geometrically (rainier cz.yaml:15-19); remove the 1500 m/s default for near-surface use.
  - verifier: In pnw_velocity_profile (dvv.py:284-300) the layer thicknesses are [0.05, 0.5, 2.0, half-space] km, the top layer Vs is set from Vs30, target_dz_km = 0.01 (10 m) and max_depth_km = 6. peak_depth_km defaults to 1500 m/s (dvv.py:45-47), which gives 167 m at 3 Hz. peak_depth_km is only used in tests/test_dvv.py:34, so the default is mainly a documentation and test hazard.
- **hydromechanics-8** [major] [partially] separate_depth and invert_states_from_bands average the deep posterior over all nodes below the water table to 6 km, where the posterior reverts to the zero prior. This dilutes wtd_relative_dvv by the grid's depth extent before it is divided by K_SAT.
  - evidence: dvv.py:327-341, 362-370; dvv_to_wtd_change :72-78.
  - issues: #51/#198: replace the deep mean with an operator-consistent head estimate (kernel-weighted, with 1/sigma' depth structure); add a test that the result is invariant to max_depth_km.
  - verifier: Confirmed: the deep partition is a plain mean over every node with z > water table down to max_depth_km (dvv.py:327-341, 362-370). With 10 m nodes and a 30 m table that is about 600 nodes, so the result depends on max_depth_km and is not kernel-weighted. In the old notebooks it is then divided by K_SAT (make_digital_twin.py:260). Not verified and probably overstated: 'reverts to zero prior' at depth. The 0.1-0.5 Hz kernels reach several km in this model, so deep nodes are not pure prior. The bigger issue is physical: km-depth dv/v is averaged into a head proxy. codameter is not installed, so I could not run it.
- **hydromechanics-9** [minor] [not-checked (minor)] The synthetic depth-time truth puts the GWL signal uniformly at all depths from 30 m to 6 km. A drained head change instead gives m(z) = -(1/6) rho_w g dh / sigma'(z), decaying with depth.
  - evidence: dvv.py:395-400 (w_deep tanh switches on and stays 1).
  - issues: #51: rebuild the synthetic truth from the effective-stress operator so round-trip tests are physically meaningful.
- **hydromechanics-10** [major] [confirmed] The forecast Vs30 blend w = root_depth/30 underweights the soft top layer: a harmonic average gives about 7.5% weight (1 m at 150 m/s over 29 m at 350 m/s) vs 3.3%, about 2.2x. It also assigns the band coefficient K_SAT*dh as a material change over 1-30 m, including the unsaturated band above the water table.
  - evidence: forecast.py:181-183; #198 already specifies harmonic Vs30.
  - issues: #85 and #198: compute Vs30(t) = 30 / integral(dz/Vs) on the operator grid; sequence #85 after #198 (they are currently batches 14 and 2).
  - verifier: forecast.py:181-183 uses w = root_depth/30 with root_depth_m defaulting to 1.0 (forecast.py:135). The harmonic travel-time fraction for 1 m at 150 m/s over 29 m at 350 m/s is 0.00667/0.0895 = 7.45%, vs 3.33%, about 2.2x. dvv_low (the K_SAT head term) is applied to the whole 1-30 m, including any unsaturated part. #198 acceptance requires a harmonic Vs30(t). Queue: #85 is in batch 14 and #198 in batch 2.
- **hydromechanics-11** [major] [confirmed] Neither model includes surface total-stress loading (snow or ponding). 1 m SWE (about 9.8 kPa) on a drained frame at 2 m depth gives about +4% local Vs, opposite in sign to and of the same order as the wetting signal. GNSS-scale elastic strain (15 nanostrain median) is a weak dv/v confounder (about 0.0015-0.015% for beta 1e3-1e4).
  - evidence: twin snow is hydrological only: forecast.py:52-58, no load in dvv_coupling.py; rainier critical_zone.md:127-128 (snow loading several % at 15-25 Hz); paper:793 (areal strain).
  - issues: New issue or #198 item: snow/surface load as a total-stress term in the operator. #226: frame GNSS as a total-water-storage observable, not a dv/v correction.
  - verifier: The twin's snow is degree-day only (forecast.py:52-58), and no load term exists in dvv_coupling.py. Check: 9.81 kPa on sigma' of about 35-45 kPa at 2 m gives (1/6)*ln(1 + 9.8/40) of about +3.7%, so roughly +4% is right. GNSS: 15 nanostrain (paper:793) times beta 1e3-1e4 gives 0.0015-0.015%. Both are arithmetic consistent; the beta range is assumed.
- **hydromechanics-12** [minor] [not-checked (minor)] Both chains are drained-only. For clayey, lahar-cap or till confining units (c_v about 1e-6 m2/s, L about 5 m, t about 300 days), seasonal loads are partly undrained (B about 1), which changes the sign and magnitude of the dv/v-head relation.
  - evidence: rainier critical_zone.md:65 ('A drained chain'); dvv_coupling.py:19-20; #50 body.
  - issues: #50 and #228: add a per-unit drained/undrained flag to the operator fidelity modes.
- **hydromechanics-13** [minor] [not-checked (minor)] Rainier's soft_sand docstring says Hertz-Mindlin at phi above the critical porosity, but the code uses min(phi, phi_c). With SOLUS soil porosity median 0.63 > phi_c = 0.40, soil-layer frame stiffness is independent of porosity everywhere.
  - evidence: rainier src/rainier3d/cz/rockphysics.py:42-53; docs/critical_zone.md:46.
  - issues: Fix the docstring or the code when porting into #198; flag to the rainier3d maintainers (no twin issue needed beyond a #198 note).
- **hydromechanics-14** [minor] [not-checked (minor)] Rainier's Hertz-Mindlin frame (C=9, f=0.5, clay 0.2) is about 2.9x stiffer in G than the twin's G_REF law at the same stress (about 101 vs 35 MPa at 10 kPa; Vs about 250 vs 140 m/s). Both use n = 1/3, so dv/v ratios agree and only Vs0(z) and the kernels differ.
  - evidence: rainier rockphysics.py:31-39, cz.yaml:33-43; dvv_coupling.py:45-47. Hand calc.
  - issues: #198: treat C*f as a Vs0 calibration parameter (dispersion/HVSR) and n as the dv/v calibration parameter.
- **hydromechanics-15** [major] [partially] Rainier's static saturation profile assumes hydrostatic equilibrium with the (Fan 2017) water table. Under ridges where the water table is more than 100 m deep this gives very dry, stiff near-surface soil and an exaggerated wetting response; it must be driven by a dynamic theta(z) before use as an operator.
  - evidence: rainier src/rainier3d/cz/medium.py:86-91 (head only overrides the top layers); docs/critical_zone.md:192-193.
  - issues: #198: the operator input is the twin's theta(z)/psi(z) and head; no hydrostatic default in operational mode.
  - verifier: medium.py:86-91 sets h = Z - water_table (hydrostatic), and the optional head overrides only the top len(head) layers. critical_zone.md:192-193 gives water tables deeper than 100 m under ridges (90th percentile 112-200 m). The effect is unquantified: 'very dry, stiff' and 'exaggerated wetting response' were not computed, and richards.py uses free drainage when the table is below the domain.
- **hydromechanics-16** [major] [partially] Rainier's Richards solver lacks ET, lateral drainage, snow and hysteresis and uses a fixed static water-table bottom boundary; all mechanical parameters are m1_placeholder. It is a structural template, not a calibrated model.
  - evidence: rainier richards.py:8-11; cz.yaml:2-3, 22-43; paper:513-514; critical_zone.md:107-110.
  - issues: #198 and #223/#224: adopt the equations and grid, not the parameter values; attach parameter priors and an ensemble.
  - verifier: richards.py:8-11: no lateral flow, ET, interception or snow. Hysteresis is listed as a placeholder in critical_zone.md:107-110. The bottom boundary is a fixed static water-table head only when the table is inside the domain, otherwise free drainage, so 'fixed static water-table bottom' is incomplete. cz.yaml marks rock_physics as m1_placeholder, but grain density and water modulus are physical constants. The 'structural template' conclusion holds.
- **hydromechanics-17** [critical] [partially] Recommendation: adopt rainier3d's CZ column (sigma'(z) from column weight plus Lu-Godt-Wu suction stress, Hertz-Mindlin/soft-sand with Gassmann-Brie, disba kernels on Vs0(z), harmonic Vs30) as the reference #198 operator, ported as a dependency-light twin module evaluated at station/footprint columns only, not by importing the rainier3d package (which depends on its geomodel/petro table).
  - evidence: rainier level.py:17-21, 149-167 (dependencies); medium.py:50-156; synthetics.py:31-45; #198 body.
  - issues: #198: add this design decision (needs-human-decision on porting vs dependency and licence); acceptance tests per section 3 of the report.
  - verifier: The design recommendation is reasonable, and the dependency claim holds: level.py:17-21 imports geomodel.rules, petro.table and properties.assign, and medium.profile takes a rock_fn from the petro table. Two corrections. (1) Rainier is BSD-3-Clause, so porting with attribution needs no licence decision. (2) Rainier's suction stress, chi = Se (rockphysics.py:62-64), is the same Se*Pc form the twin already uses (dvv_coupling.py:89). The real upgrades are sigma'(z) from column weight, soft-sand/Gassmann and kernels; the deeper layers need a replacement for the petro rock law.
- **hydromechanics-18** [major] [partially] Minimum operator grid is about 40 geometric layers (5 cm, x1.12) to 30 m (52 to 150 m, matching rainier), plus a half-space. The prognostic hydrologic state needs at least 4 vertical stores (0-0.3 m, 0.3 m to z_soil, z_soil to the water table, saturated head) and a perched head at z_soil; the single 1 m bucket is insufficient.
  - evidence: rainier cz.yaml:15-19, paper:451, critical_zone.md:112-113; twin water_budget.py:150-153, 236, 248, 253.
  - issues: #172/#131/#130: define the store depth bounds to match the operator grid; #198 depends on them; consider a new 'vertical state contract' item under #187.
  - verifier: cz.yaml sets top_m 0.05, growth 1.12 and base_m 60 (not 30), with 50 m deep cells below. 5 cm x 1.12 reaches 30 m in about 38 layers (bottom cell about 3.3 m), so '40 layers to 30 m' is roughly right, but '52 to 150 m, matching rainier' cannot be traced to cz.yaml. The richards domain is 30 m per critical_zone.md:208. The 4-store recommendation is design opinion, not verifiable. The single 1 m bucket is confirmed (water_budget.py:119, 150-153).
- **hydromechanics-19** [major] [confirmed] For the FS path, suction stress is first-order for shallow slip (H = 1 m: -10 kPa suction adds about +0.77 to FS on a 35 deg slope with phi' 33 deg). It is negligible at the 14.6 m median deposit depth (about +0.05), where each metre of water-table rise changes FS by about -0.03. Deep-seated FS therefore needs head accurate to 1-2 m at slip depth.
  - evidence: Lu & Godt 2008 infinite-slope with suction stress; rainier paper:1037 (453 lidar-protocol deposits, median failure depth 14.6 m); twin pooled RMSE 18.5 m (#47).
  - issues: #128: acceptance must include the suction-stress term, explicit slip-depth classes, and a sigma(FS) from head sigma; #129/#224: score shallow and deep-seated failures separately.
  - verifier: Lu-Godt infinite slope at beta 35, phi' 33, gamma 18 kN/m3: suction term = 10*(tan b + cot b)*tan phi'/(gamma*H) = 13.8/18 = 0.77 at H = 1 m, and 0.053 at 14.6 m (this assumes the same -10 kPa at depth, generous). For a water-table rise with slope-parallel seepage, -gamma_w*cos^2(b)*tan phi'/(gamma*H*sin b*cos b) = -0.035 per m (-0.05 per m with vertical u = gamma_w*h). Median failure depth 14.6 m from 453 deposits is confirmed at paper:1037. #128 currently lacks any suction term.
- **hydromechanics-20** [major] [confirmed] The current 1 m root zone can provide only depth-averaged theta, and hence suction stress, for slip surfaces of about 1 m or less. It cannot provide perched positive pore pressure (excess goes to runoff/interflow sinks), any state between 1 m and the water table, or colluvium thickness (rainier SOLUS soil thickness is capped at 2.01 m).
  - evidence: water_budget.py:236, 248, 251-253; rainier medium.py:37.
  - issues: #128 (first-wave batch 4) must ship an h_p interface stub and document its limits; #130/#133/#134 (batch 22) supply the missing inputs; consider holding #129 until they land.
  - verifier: Saturation excess goes to runoff (water_budget.py:236-237), and drainage splits into interflow and recharge (:248-253). There is no perched-head state, although the #128 body asks for pore pressure from 'modeled saturation/perched head'. Rainier caps soil thickness at 2.01 m (medium.py:37). Batches: #128 in 4, #130/#133/#134 in 22, #129 in 23.
- **hydromechanics-21** [critical] [confirmed] The GAIA grouper dispatches #198 in first-wave batch 2 although its body declares 'Depends on #187, #176' (#187 is held, #176 is in batch 7). #226 is also not held despite 'Blocked by #187 and #189'.
  - evidence: scratchpad/queue_sim.jsonl lines 2, 7, 10; queue_held.txt (lists #187 as held, not #198 or #226); #198 body 'Depends on'; #226 body 'Blocked by'.
  - issues: Add machine-readable blocked-by markers to #198 and #226, or fix the gaia_group_issues.py dependency parsing, before launch.
  - verifier: gaia_group_issues.py uses a hard-coded BLOCKED_BY dict (lines 86-102) that has no entries for 198 or 226. It does not parse issue bodies. #198 states 'Depends on: #187, #176', and #226 states 'Blocked by: #187 and #189'. queue_sim lines 2 (#198) and 10 (#226) dispatch them, while queue_held lists #187 and #189 as held.
- **hydromechanics-22** [major] [partially] Issues editing the same hydromechanical constants (SIGMA0, K_SAT, S_THETA) are spread across batches 7 (#176), 14 (#85) and 28 (#45, #50, #30) while #198 intends to retire those constants. Parallel agents will tune constants that #198 removes.
  - evidence: queue_sim.jsonl lines 7, 14, 28; dvv_coupling.py:42-50; dvv.py:50-69; #198 'Retire dvv_to_theta_change / dvv_to_wtd_change'.
  - issues: Hold #45, #50, #85 and the SIGMA0 part of #176 as blocked-by #198, or fold them into #198 sub-tasks.
  - verifier: Batches confirmed: #176 in line 7, #85 in line 14, #45/#50/#30 in line 28. #176 explicitly asks to calibrate SIGMA0/G_REF; #45 targets S_THETA, #50 K_SAT, and #30 calibrates the coupling parameters. #198 retires dvv_to_theta_change/dvv_to_wtd_change from the operational path but keeps them as diagnostics, so tuning them is not entirely wasted. #85 builds sigma'(z)/dynamic Vs30 rather than editing the constants, so it is overlapping duplicate work, not constant-tuning.
- **hydromechanics-23** [minor] [not-checked (minor)] The coda footprint parameters (D = 8 km2/s, lapse 10 s, about 18 km scale) are crustal. At 10-40 Hz near-surface (v about 0.3 km/s, transport mean free path about 0.1 km) D is about 0.015 km2/s, about 500x smaller, giving sub-km footprints; spatial kernels must be band-specific.
  - evidence: src/models/dvv_sensitivity.py:81-82.
  - issues: #168: make D and lapse time band-dependent parameters of the operator, with uncertainty in R.
- **hydromechanics-24** [minor] [not-checked (minor)] Rainier docs and paper disagree on two CZ numbers: storm dv/v at 40 Hz (-1.1 to -1.2% in critical_zone.md vs 'about 2%' in the paper) and the top-50 m Vs ratio (0.50 vs 0.58).
  - evidence: rainier docs/critical_zone.md:173, 210; docs/paper/rainier3d_paper.md:493, 513.
  - issues: Any #223/#224 issue citing these values should cite the run output, not the prose; flag to the rainier3d maintainers.

## Verifier: missed problems

- Vadose Vs(theta) is non-monotone for coarse soils, which breaks invert_dvv's 'monotone' lookup (dvv_coupling.py:136-146). Suction stress Se*Pc tends to 0 as Se goes to 0 when vG n > 2, and the pedotransfer at dvv_coupling.py:71-72 gives n up to 2.8. Probe: sand 90%, clay 3% (n = 2.36) gives Vs 149.9, 152.4, 152.4, 152.0 ... 132.3 m/s from theta 0.05 to 0.40, so the argmin inversion is ambiguous at the dry end.
- KERNEL_FRACTION_TOP1M = 0.08 (dvv.py:67-69) does not fit the twin's own 0.1-4 Hz bands. At 2-4 Hz with Vs about 400 m/s (wavelength about 100-200 m) the top-1 m Rayleigh kernel fraction is of order 1-2% (rough estimate, not computed; disba/codameter are not installed). If so, S_THETA_BAND overstates the band sensitivity by about 4-8x, and raw-band theta inversions would be underestimated by the same factor. Agents on #45/#51 should compute it from the kernels, not reuse 0.08.
- The S_MATERIAL_THETA = -1.0 sensitivity depends strongly on texture (about -0.34 per unit theta for sand vs -1.0 for loam at SIGMA0 = 10 kPa), so a single global scalar is wrong at the material level too, not only at the band level.
- A drained water-table rise lowers sigma' by gamma_w*dh*(1-Sy) over the whole saturated column, plus loss of suction in the capillary fringe above it. The right band coefficient is the integral of K_b(z)/(6*sigma'(z)) dz. Its depth structure (largest just below a shallow table) is not captured by a single K_SAT, nor by averaging the deep nodes uniformly (claim 8).
- Hertz-Mindlin n = 1/3 (G proportional to sigma'^(1/3)) is applied unchanged at all depths. For cemented or weathered rock below a few metres the pressure exponent is much lower, so any sigma'(z)-based K_b ported from the soil law will overstate deep head sensitivity. #198 should say which rock law applies to each unit (rainier uses soft-sand plus a separate rock law).
- The rainier storm synthetic reports different 40 Hz storm magnitudes in two places (about -2% at paper:513 vs -1.1 to -1.2% at critical_zone.md:208). Agents citing rainier as a calibration target should cite one of them, not mix them.
