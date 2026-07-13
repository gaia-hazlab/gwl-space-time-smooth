"""Coupled water budget: recharge, capillary rise, runoff, and subsurface lateral flow.

Closes the flux gap the peer review flagged (issues #43, #44). The standalone
``soil_moisture.total_water_bucket`` drains above-field-capacity water *out of the system*, so soil
moisture and groundwater were only co-located. Here the vadose column and the water table exchange
water through explicit fluxes, and lateral redistribution moves water down-gradient:

  Vertical (issue #43)
    - deep percolation below the root zone is **recharge** to the water table (theta -> GWL),
    - the water table responds as a linear reservoir (recharge in, baseflow recession out),
    - where the table is shallow, **capillary rise** feeds water back up into the root zone
      (GWL -> theta), closing the feedback.

  Lateral (issue #44)
    - **saturated-area (variable-source-area) runoff**: where the water table is at or near the
      surface there is no space to infiltrate into, so rain runs off. This is the dominant runoff
      mechanism in humid temperate catchments like the PNW -- it fires on valley floors and riparian
      corridors (HAND ~ 0) while ridges infiltrate freely. It is a **sink** in this budget, so
      omitting it biases theta and the water table high,
    - **root-zone saturation excess** on top of that, when the column itself fills to porosity,
    - **subsurface lateral flow** is represented by a TOPMODEL relation: the steady-state water
      table follows the topographic wetness index (valleys wet/shallow, ridges dry/deep),
    - generated runoff can be routed down-gradient with a flow-accumulation weight.

Mass is conserved by construction each step: dS = cap_rise + input - runoff - AET - recharge.

The timestep is set by ``dt_days`` (default: one month, reproducing the original monthly behaviour).
A **daily** step is what lets an AI weather forecast (GraphCast et al., 6-hourly) drive the budget at
the scale storms actually happen: aggregating a 10-day forecast to a monthly mean destroys the very
event signal the forecast exists to provide, and a concentrated storm generates far more
saturation-excess runoff (and less recharge) than the same water spread evenly over a month.

Scope / caveats (tracked as follow-ups): *infiltration-excess* (Hortonian) runoff is still not
represented (issue #57) -- it is intensity-driven and needs sub-daily rain: a 68 mm/day storm is only
2.8 mm/hr, far below these soils' Ksat (15-55 mm/hr), so it correctly never fires at a daily mean even
though real storms burst well above it. Runoff *routing* to a hydrograph is deliberately NOT done here
-- we generate the source term and LandLab routes it (issue #55). Nominal parameters (specific yield, recession time,
capillary reach, TOPMODEL m) are calibration-pending.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Nominal, calibration-pending parameters.
SPECIFIC_YIELD = 0.12          # unconfined specific yield S_y (dimensionless)
RECESSION_MONTHS = 6.0         # water-table baseflow recession time constant tau (months)
CAP_MAX_MM = 30.0              # max capillary-rise flux into the root zone (mm PER MONTH)
CAP_FRINGE_M = 1.0             # capillary reach below the root-zone base (m)
TOPMODEL_M = 0.6               # TOPMODEL transmissivity-decay scale (m of water-table spread)
_DRAIN_FRAC = 0.6              # gravity-drainage fraction above field capacity, PER MONTH (legacy)
DAYS_PER_MONTH = 30.436875     # mean Gregorian month; the unit the rate parameters are quoted in
# Gravity drainage above field capacity is a ~1-3 day process. Note that the legacy monthly
# drain_frac=0.6 implies a timescale of 30.44/ln(2.5) ~ 33 days -- i.e. it is a lumped monthly
# calibration with no physical meaning at daily resolution. Sub-monthly runs must use a real
# timescale instead, or the column drains ~15x too slowly. Calibration-pending (see issue).
DRAIN_TAU_DAYS = 2.0           # e-folding timescale of gravity drainage above field capacity (days)


@dataclass
class WaterBudget:
    """Coupled state + fluxes on a (time, ...) grid. All storages in m^3/m^3 or m; fluxes in mm."""

    theta: np.ndarray          # (t, ...) volumetric soil moisture
    wt_depth_m: np.ndarray     # (t, ...) water-table depth below surface (m; smaller = shallower)
    recharge_mm: np.ndarray    # (t, ...) deep percolation to the water table
    runoff_mm: np.ndarray      # (t, ...) saturation-excess surface runoff generated
    aet_mm: np.ndarray         # (t, ...) actual evapotranspiration
    cap_rise_mm: np.ndarray    # (t, ...) capillary rise from the water table into the root zone


def _capillary_rise(wt_depth_m, root_depth_m, deficit_frac, cap_max_mm, fringe_m):
    """Upward flux (mm) from a shallow water table into the root zone.

    Zero when the table is deeper than the root-zone base plus the capillary fringe; otherwise it
    scales with how close the table is to the root zone and with the current storage deficit
    (a full column pulls nothing up). ``deficit_frac`` in [0, 1] is (S_sat - S)/(S_sat - S_wp).
    """
    reach = root_depth_m + fringe_m
    proximity = np.clip((reach - wt_depth_m) / max(reach, 1e-6), 0.0, 1.0)
    return cap_max_mm * proximity * np.clip(deficit_frac, 0.0, 1.0)


def coupled_water_budget(liquid_in_mm, pet_mm, theta_wp, theta_fc, theta_sat, root_depth_m=1.0,
                         specific_yield=SPECIFIC_YIELD, recession_months=RECESSION_MONTHS,
                         cap_max_mm=CAP_MAX_MM, cap_fringe_m=CAP_FRINGE_M, drain_frac=_DRAIN_FRAC,
                         wt_depth0_m=5.0, init="fc", dt_days=None, drain_tau_days=DRAIN_TAU_DAYS,
                         sat_area_runoff=True):
    """Time-step the coupled vadose-column + water-table budget at an arbitrary timestep.

    ``liquid_in_mm`` (rain + snowmelt) and ``pet_mm`` are (t, ...) arrays **per timestep** — mm/month
    for a monthly run, mm/day for a daily one. The envelope limits (``theta_wp/fc/sat``) broadcast to
    ``(...)``. Returns a :class:`WaterBudget`.

    ``dt_days`` sets the step length. ``None`` (default) means one mean month and reproduces the
    original monthly behaviour exactly. Three of the parameters are **per-month rates**, and each is
    converted to the step so that a daily run is physically equivalent rather than 30x too fast:

      - recession: ``h -= h * dt/tau`` with ``tau = recession_months`` in days,
      - gravity drainage: sub-monthly steps use a physical e-folding time ``drain_tau_days``
        (~1-3 d), **not** the lumped monthly ``drain_frac`` (which implies an unphysical ~33 d),
      - capillary rise: ``cap_max_mm`` is a mm/month flux, scaled linearly by ``dt/month``.

    Getting this wrong is the whole difficulty of driving the budget from a sub-daily AI weather
    forecast: pass mm/day into a model whose rates are per-month and the column drains ~30x too fast.

    The water table is a linear reservoir in head anomaly h (``wt_depth = wt_depth0 - h``; rising head
    -> shallower table). Capillary rise uses the *previous* step's table (explicit coupling), so the
    loop theta -> recharge -> table -> capillary rise -> theta closes without an implicit solve.
    """
    liquid = np.asarray(liquid_in_mm, dtype="float64")
    pet = np.asarray(pet_mm, dtype="float64")
    nt = liquid.shape[0]
    z = root_depth_m * 1000.0                                  # root-zone depth in mm
    wp, fc, sat = (np.asarray(a, dtype="float64") for a in (theta_wp, theta_fc, theta_sat))
    Swp, Sfc, Ssat = wp * z, fc * z, sat * z
    span = np.clip(Ssat - Swp, 1e-6, None)

    S = (Sfc if init == "fc" else Swp).astype("float64").copy()
    S = np.broadcast_to(S, liquid.shape[1:]).astype("float64").copy()
    h = np.zeros_like(S)                                       # water-table head anomaly (m)
    wt0 = np.broadcast_to(np.asarray(wt_depth0_m, float), S.shape).astype("float64")

    # --- per-month rates -> per-step rates -------------------------------------------------------
    if dt_days is None:                                        # legacy monthly step, bit-for-bit
        step_frac = 1.0
        recess = 1.0 / max(recession_months, 1e-6)
        drain_step = np.clip(drain_frac, 0.0, 1.0)             # the lumped per-month fraction, as-is
    else:
        step_frac = float(dt_days) / DAYS_PER_MONTH
        recess = float(dt_days) / max(recession_months * DAYS_PER_MONTH, 1e-6)
        # NOT the compounded monthly fraction: that implies a ~33 d drainage timescale (see
        # DRAIN_TAU_DAYS). Sub-monthly drainage uses its own physical e-folding time.
        drain_step = 1.0 - np.exp(-float(dt_days) / max(drain_tau_days, 1e-6))
    recess = min(recess, 1.0)                                  # never overshoot the reservoir
    cap_max_step = cap_max_mm * step_frac                      # mm/month -> mm/step

    theta = np.empty_like(liquid)
    wt = np.empty_like(liquid); rech_o = np.empty_like(liquid)
    run_o = np.empty_like(liquid); aet_o = np.empty_like(liquid); cap_o = np.empty_like(liquid)

    for t in range(nt):
        wt_depth = wt0 - h                                    # current table depth (m)
        deficit_frac = (Ssat - S) / span
        cap = _capillary_rise(wt_depth, root_depth_m, deficit_frac, cap_max_step, cap_fringe_m)
        cap_eff = np.minimum(S + cap, Ssat) - S              # actual added (exact mass balance)
        S = S + cap_eff

        # --- saturated-area (variable-source-area) runoff -----------------------------------------
        # The dominant runoff mechanism in humid temperate catchments: rain falling where the water
        # table is at/near the surface cannot infiltrate, because there is no space to put it. The
        # storage available between the table and the surface is S_y * wt_depth; anything above that
        # runs off. Where the table outcrops (wt_depth <= 0) the deficit is zero and ALL rain runs off.
        # This fires on valley floors / riparian corridors (HAND ~ 0) while ridges infiltrate freely,
        # which is exactly the variable source area -- and it is a SINK in this budget, so omitting it
        # biases theta and the water table high.
        if sat_area_runoff:
            deficit_mm = np.clip(specific_yield * wt_depth, 0.0, None) * 1000.0
            sat_runoff = np.maximum(liquid[t] - deficit_mm, 0.0)
        else:
            sat_runoff = np.zeros_like(S)

        S = S + (liquid[t] - sat_runoff)                     # only what can infiltrate
        excess = np.maximum(S - Ssat, 0.0); S = S - excess   # root-zone saturation excess
        runoff = sat_runoff + excess
        aet = np.minimum(pet[t], np.maximum(S - Swp, 0.0)); S = S - aet
        rech = np.maximum(S - Sfc, 0.0) * drain_step; S = S - rech   # deep percolation = recharge
        S = np.clip(S, Swp, Ssat)

        theta[t] = S / z
        rech_o[t] = rech; run_o[t] = runoff; aet_o[t] = aet; cap_o[t] = cap_eff

        # water-table reservoir: recharge (m) raises head, recession lowers it
        h = h + (rech / 1000.0 / max(specific_yield, 1e-6) - h * recess)
        wt[t] = wt0 - h

    return WaterBudget(theta=theta.astype("float32"), wt_depth_m=wt.astype("float32"),
                       recharge_mm=rech_o.astype("float32"), runoff_mm=run_o.astype("float32"),
                       aet_mm=aet_o.astype("float32"), cap_rise_mm=cap_o.astype("float32"))


def topmodel_watertable(mean_depth_m, twi, m_param=TOPMODEL_M):
    """Steady-state subsurface lateral flow: spread a mean water-table depth by the TWI (TOPMODEL).

    Local depth ``d_i = mean_depth - m*(TWI_i - mean_TWI)``: high TWI (convergent valleys) -> shallower
    table (wetter), low TWI (divergent ridges) -> deeper. This is the topographically-driven lateral
    redistribution of the water table along its gradient. Returns a depth field (m), clipped >= 0.
    """
    twi = np.asarray(twi, dtype="float64")
    twi_mean = np.nanmean(twi)
    d = np.asarray(mean_depth_m, dtype="float64") - m_param * (twi - twi_mean)
    return np.clip(d, 0.0, None)


def accumulate_runoff(runoff_mm, flow_accum):
    """Route generated runoff down-gradient with a flow-accumulation weight (simple, non-dynamic).

    ``flow_accum`` is a contributing-area / accumulation raster (cells, or upstream area). The routed
    field weights local runoff by (1 + normalized accumulation), a first-order proxy for down-slope
    concentration; a true hydrograph needs a channel-routing model (issue #55). Returns the weighted
    runoff on the same grid.
    """
    fa = np.asarray(flow_accum, dtype="float64")
    fa = np.where(np.isfinite(fa), fa, 0.0)
    norm = fa / (np.nanmax(fa) + 1e-9)
    return np.asarray(runoff_mm, dtype="float64") * (1.0 + norm)
