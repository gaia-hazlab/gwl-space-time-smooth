# Editorial framework for the GAIA Digital Twin of Soil book

This proposal aligns the Quarto book in `gwl-space-time-smooth/docs/twin/` with the simpler language developed for the WCM 2026 slides. It does not remove technical depth; it gives readers a stable conceptual map before they encounter it.

## The one framework to repeat throughout the book

The twin should be introduced as one repeating cycle:

1. **Represent** the subsurface state at the scale required by the hazard.
2. **Advance** that state with water-conserving and hydromechanical physics.
3. **Predict each observation** at the sensor's own spatial and temporal support.
4. **Compare and correct** the model with observations.
5. **Propagate uncertainty** into the next nowcast, forecast, and hazard product.
6. **Validate in observation space**, using measurements not used in the correction.

The short version, suitable for chapter openers and figures, is:

> **Represent → advance → observe → correct → propagate → evaluate → act.**

The scientific claim is not “all data become 90 m data.” It is:

> **The state lives at 90 m; every observation retains its own footprint.**

The implementation-status claim should also be repeated consistently:

> **Now:** a physically constrained prior and snapshot BLUE analyses.  
> **Next:** a cycling ensemble analysis that carries the posterior distribution into probabilistic forecasts.

## A common notation for the whole book

Use one state vector and one superscript convention everywhere:

$$
\mathbf{x}_t=
\begin{bmatrix}
S_{\mathrm{soil},t} & S_{\mathrm{gw},t} & V_S(z,t) & \mathbf{q}_t
\end{bmatrix}^{\!T},
$$

where $\mathbf{q}_t$ contains optional memory states such as capillary branch, earthquake damage, or post-fire soil recovery. Use $f$ for the forecast/prior and $a$ for the analysis/posterior.

The entire twin can then be expressed with four equations:

$$
\mathbf{x}_{t+1}^{f,(e)}=
\mathcal{M}\!\left(\mathbf{x}_{t}^{a,(e)},\mathbf{u}_{t}^{(e)},\boldsymbol{\eta}_{t}^{(e)}\right),
\tag{1}
$$

$$
\widehat{\mathbf{y}}_t^{(e)}=\mathcal{H}\!\left(\mathbf{x}_t^{f,(e)}\right),
\qquad
\mathbf{r}_t=\mathbf{y}_t-\overline{\widehat{\mathbf{y}}}_t,
\tag{2}
$$

$$
\mathbf{x}_t^{a}=\mathbf{x}_t^{f}+\mathbf{K}_t\mathbf{r}_t,
\tag{3}
$$

$$
p(\mathbf{x}_{t+1}\mid \mathbf{y}_{1:t})
=\int p(\mathbf{x}_{t+1}\mid\mathbf{x}_t,\mathbf{u}_t),
p(\mathbf{x}_t\mid\mathbf{y}_{1:t})\,d\mathbf{x}_t.
\tag{4}
$$

Equation 1 advances each ensemble member; Equation 2 predicts what each sensor would observe and forms the innovation; Equation 3 is the correction; Equation 4 states the future probabilistic objective. The full BLUE cost function and covariance algebra remain useful, but should follow these equations rather than introduce the chapter.

## Proposed replacement for the overview

### Opening paragraph

> The GAIA Digital Twin of Soil maintains a time-evolving estimate of subsurface water and stiffness at the scale required by flood, landslide, and liquefaction models. The state is fine-scale; the evidence is not. Wells observe points, satellites average pixels, seismic coda samples volumes, and gauges integrate basins. The twin reconciles them by predicting each measurement from one physical state at that measurement's native support. Observations then correct the model where they carry information, and the resulting uncertainty is propagated into the next nowcast and forecast.

### Replace “Five kinds of information constrain the state”

The current list is accurate but organizes the book as an inventory. Replace it with the operating loop:

| Stage | Reader's question | Book chapters |
|---|---|---|
| Represent | What state do we need, and at what scale? | Digital twins review; Structural model |
| Supply | What enters, in what units, support, cadence, and role? | Input data; Cyberinfrastructure |
| Advance | How do water and stiffness evolve while conserving water? | Hydrology; Hydromechanics; Memory |
| Observe | What would each sensor measure from this state? | Hydromechanics; Assimilation |
| Correct | How do data update the state and reduce uncertainty? | Assimilation |
| Evaluate | What is genuinely resolved and independently verified? | Evaluation data; State evaluation |
| Forecast | How does the posterior distribution evolve under uncertain forcing? | Forecast |
| Act | How do state distributions become hazard probabilities? | Hazard integration |

### Add a status box beneath the framework figure

> **Implemented:** common 90 m state grid, water-budget model, native-support observation operators, snapshot BLUE analysis, observability diagnostics, and deterministic forecast pathway.  
> **Demonstrated with synthetic or partial inputs:** time-varying dv/v assimilation and selected uncertainty maps.  
> **In development:** a mass-consistent two-store exchange, common forward/inverse petrophysics, cycling ensemble DA, posterior ensembles, probabilistic forcing, and probabilistic damage/healing states.

This prevents a reader from inferring that a cycling Kalman/EnKF system is already operational.

## Chapter-by-chapter changes

### 0 · Digital twins and digital shadows

Open with the distinction that matters for this project:

> A digital shadow updates a model from the physical system. A digital twin closes the loop: it updates, quantifies uncertainty, forecasts, and exposes those forecasts to decisions. The present system is a strong digital shadow moving toward a probabilistic digital twin.

End the literature review with the six-stage framework above. Use it to turn the modeling, data, interoperability, validation, computation, and adoption challenges into requirements rather than a disconnected list.

### 1 · Structural model

Suggested opener:

> This chapter defines what the ground can be before weather and observations change it. Terrain, soil, geology, and baseline velocity supply the spatial envelope and prior uncertainty; they are not observations of today's state.

Introduce the baseline/anomaly split once:

$$
\mathbf{x}(\mathbf{s},t)=\overline{\mathbf{x}}(\mathbf{s})+\Delta\mathbf{x}(\mathbf{s},t).
$$

Apply it consistently to water-table depth and velocity. State prominently that a 90 m delivered grid does not imply 90 m independent information where the source is coarser.

### 2 · Input data

Reorganize the dataset inventory around four roles:

- **Static prior:** soil, terrain, geology, baseline $V_S$.
- **Forcing:** precipitation, temperature, PET, disturbance events.
- **Assimilation observations:** measurements allowed to correct the state.
- **Held-out evaluation:** measurements used only for scoring.

Add required object metadata to the table: variable, units, CRS, timestamp/interval, native footprint, delivered grid, uncertainty model, provenance, and role. This is the practical “ecosystem-binding” contract.

### 3 · Cyberinfrastructure

Rename the central concept from “homogenise data” to **“homogenise interfaces, preserve observations.”** A canonical data object should be written schematically as

$$
\mathcal{O}_i=\{y_i,t_i,\Omega_i,H_i,R_i,\text{units},\text{provenance},\text{role}\},
$$

where $\Omega_i$ is native support, $H_i$ maps the state to that support, and $R_i$ describes measurement plus representation error. Reprojection may locate a footprint on the common grid; it must not turn the datum into 90 m information.

### 4 · Physics — Hydrology

Lead with two audience-readable storage equations and move individual closures to the next section:

$$
\Delta S_{\mathrm{soil}}
=(P+M)+C_{\uparrow}-ET-Q_{\mathrm{surface}}-Q_{\mathrm{interflow}}-R_{\mathrm{gw}},
\tag{H1}
$$

$$
\Delta S_{\mathrm{gw}}
=R_{\mathrm{gw}}-Q_{\mathrm{baseflow}}-C_{\uparrow},
\qquad
\Delta d_{\mathrm{wt}}=-\frac{\Delta S_{\mathrm{gw}}}{1000S_y}.
\tag{H2}
$$

Define them in plain language: rain and snowmelt enter; evapotranspiration and lateral flows leave; recharge transfers water downward; capillary rise transfers the same water upward. The identical transfer must appear with opposite signs in the two stores.

Then show the detailed flux closures. Avoid presenting the older monthly Thornthwaite–Mather bucket as a second simultaneous governing model; label it as a legacy or lower-rung approximation. Keep the three-paradigm literature discussion, but move it after the model statement so readers first learn what this twin does.

Add an implementation note linked to issue #172: the intended equations debit groundwater for capillary rise, while the current implementation needs that conservation fix and test coverage. Until resolved, avoid “conserves every millimeter” as an unqualified implementation claim.

### 5 · Physics — Hydromechanics

Open with the state decomposition used in the slides:

$$
V_S(z,t)=V_{S,0}(z)+\Delta V_S(z,t).
\tag{M1}
$$

Then show one shared physics chain:

$$
\{\theta,S_w,h,\text{history}\}
\rightarrow P_c,\sigma'\rightarrow \mu_{\mathrm{eff}},\rho
\rightarrow V_S(z,t)
\rightarrow \widehat y_i=H_i[V_S(z,t)].
\tag{M2}
$$

For a seismic band $b$, the observation is

$$
\widehat{(\delta v/v)}_b(t)
=\int K_b(z;V_{S,0})
\frac{\Delta V_S(z,t)}{V_{S,0}(z)}\,dz.
\tag{M3}
$$

The main prose claim should be: **the forward prediction and inversion must use the same petrophysical operator.** Keep the full effective-stress and dynamic-capillarity equations as technical detail. Mark equilibrium van Genuchten/Hertz–Mindlin and hysteresis as implemented where true; mark dynamic capillarity and the common nonlinear observation operator as planned under issue #198. Avoid calling the current fixed-sensitivity relations the full petrophysics.

### 6 · Memory and disturbance

Suggested opener:

> Hydrology remembers accumulated water; soil and rock also remember the path, damage, and recovery. Those memories must be carried as state variables if the same dv/v anomaly can arise from wetting, earthquake damage, or fire.

Use one additive velocity equation:

$$
V_S(z,t)=V_{S,0}(z)+\Delta V_{S,\mathrm{hydro}}(z,t)+D(z,t),
$$

with property perturbations $\Phi(t)$ modifying infiltration, retention, or cohesion. Separate **implemented capillary hysteresis** from **planned probabilistic damage/healing and post-fire recovery**. This chapter should introduce why the future ensemble must sample both atmospheric forcing and mechanical memory.

### 7 · Assimilation

Lead with the three equations used in the simplified slide:

$$
\widehat y_i=H_i(\mathbf{x}^{f}),
\qquad
r_i=y_i-\widehat y_i,
\qquad
\mathbf{x}^{a}=\mathbf{x}^{f}+\mathbf{K}\mathbf{r}.
\tag{DA}
$$

Immediately translate them:

> Predict what each instrument should see; compare prediction with measurement; spread the correction through the state according to model, observation, and footprint uncertainty.

Then introduce the BLUE objective, gain, and posterior covariance. Replace $m_b/m_a/B/C_a/G/d$ in the main narrative with the forecast-analysis notation $x^f/x^a/P^f/P^a/H/y$ used by Kalman and ensemble filters. The old symbols can remain in an equivalence box for readers coming from inverse theory.

Correct the current-state language:

- Snapshot BLUE is implemented and tested.
- Independent frame-by-frame analyses are a demonstration, not a cycling filter.
- Posterior covariance is computed analytically in the small BLUE formulation but is not yet propagated through the operational state trajectory.
- The planned destination is a cycling EnKF or ensemble square-root filter with mass-conserving state updates.

Move the dynamic Bayesian network discussion to an “advanced extensions” subsection or appendix. It currently interrupts the direct path from snapshot BLUE to the near-term ensemble filter.

### 8 · Evaluation of the soil state

Open with the rule:

> A model is evaluated where and how an independent instrument observes it—not after the observation has been painted onto the model grid.

Use a common validation equation:

$$
\widehat y_i^{\mathrm{val}}=H_i^{\mathrm{val}}(\mathbf{x}^{a}),
\qquad
z_i=\frac{y_i^{\mathrm{val}}-\widehat y_i^{\mathrm{val}}}
{\sqrt{R_i^{\mathrm{val}}+H_i^{\mathrm{val}}P^{a}H_i^{\mathrm{val}\,T}}}.
\tag{V}
$$

Report accuracy, interval coverage, and calibration in observation space. Keep three labels visible on every figure: **independent validation**, **shared-forcing consistency**, or **synthetic recovery**. Replace absolute language such as “masked” with “should be masked” unless the exported product actually applies the mask in that workflow.

### 9 · Forecast

Suggested opener:

> A forecast begins from the analyzed distribution, not only the analyzed mean. Each member carries a plausible hydrologic state, mechanical memory, and weather forcing through the same physical model.

Use the ensemble forecast equation:

$$
\mathbf{x}_{t+\ell}^{f,(e)}
=\mathcal{M}_{t:t+\ell}
\left(\mathbf{x}_{t}^{a,(e)},\mathbf{u}_{t:t+\ell}^{(e)},\boldsymbol{\eta}^{(e)}\right),
$$

and summarize with quantiles or exceedance probabilities rather than a single trajectory. Separate uncertainty sources explicitly: initial-state/posterior, precipitation and temperature ensemble, hydrologic parameters/process error, observation operator, and probabilistic damage/healing.

Revise the wet-season animation caption: if each frame is analyzed independently, say so. Do not call it a recursive Kalman nowcast until posterior members or covariance are carried forward between frames.

### 10 · Hazard integration

The handoff should be a distribution, not “mean plus optional sigma.” Use

$$
P(H>h^*)\approx\frac{1}{N_e}\sum_{e=1}^{N_e}
\mathbf{1}\!\left[g\!\left(\mathbf{x}^{(e)}\right)>h^*\right],
$$

where $g$ is the downstream landslide, liquefaction, or flood model. Preserve cross-variable and cross-time dependence by passing ensemble member identity through the hazard model. This is essential when soil moisture, water table, stiffness, and damage jointly determine hazard.

### Appendix A · Compute and deployment

Connect compute directly to the probabilistic requirement: cost scales approximately with ensemble size, forecast lead, and number of analysis cycles. Document chunking and storage around an explicit `member` dimension. Include reproducibility metadata for model version, forcing initialization, ensemble construction, random seed, and observation set.

## Editorial rules to apply everywhere

1. Start every chapter with **one sentence stating its job in the operating loop**.
2. Follow with **no more than three interpretable equations**; move derivations and alternative paradigms later.
3. Use “state,” “forcing,” “observation,” and “evaluation” as mutually exclusive data roles.
4. Use “native support,” not only “native resolution”; support includes point, depth interval, pixel, coda volume, and basin integral.
5. Label every capability **implemented**, **demonstrated**, or **planned**.
6. Never imply that regridding creates information.
7. Never show uncertainty only as a per-cell standard deviation when joint dependence matters to a downstream forecast.
8. Make conservation and common forward/inverse physics testable invariants, not rhetorical claims.

## Suggested revised book title

**The GAIA State2Hazard Twin**

Subtitle: **Physics-constrained nowcasts and probabilistic forecasts of water, stiffness, and ground memory**

This is broader and more accurate than “Digital Twin of Soil”: the system represents vadose and saturated water, near-surface seismic velocity, and disturbance memory, and it connects those states to multiple hazards.

