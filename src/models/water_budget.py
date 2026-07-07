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
    - **saturation-excess surface runoff** is generated when the column fills to porosity,
    - **subsurface lateral flow** is represented by a TOPMODEL relation: the steady-state water
      table follows the topographic wetness index (valleys wet/shallow, ridges dry/deep),
    - generated runoff can be routed down-gradient with a flow-accumulation weight.

Mass is conserved by construction each step: dS = cap_rise + input - runoff - AET - recharge.

Scope / caveats (tracked as follow-ups): the balance is monthly, so *infiltration-excess* runoff
(a sub-daily, intensity-driven process) is not represented (issue #57); full channel routing to a
hydrograph is left to a downstream runoff model (issue #55). Nominal parameters (specific yield,
recession time, capillary reach, TOPMODEL m) are calibration-pending.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Nominal, calibration-pending parameters.
SPECIFIC_YIELD = 0.12          # unconfined specific yield S_y (dimensionless)
RECESSION_MONTHS = 6.0         # water-table baseflow recession time constant tau (months)
CAP_MAX_MM = 30.0              # max capillary-rise flux into the root zone (mm/month)
CAP_FRINGE_M = 1.0             # capillary reach below the root-zone base (m)
TOPMODEL_M = 0.6               # TOPMODEL transmissivity-decay scale (m of water-table spread)
_DRAIN_FRAC = 0.6              # gravity-drainage fraction above field capacity (matches bucket)


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
                         wt_depth0_m=5.0, init="fc"):
    """Time-step the coupled vadose-column + water-table budget.

    ``liquid_in_mm`` (rain + snowmelt) and ``pet_mm`` are (t, ...) arrays; the envelope limits
    (``theta_wp/fc/sat``) broadcast to ``(...)``. Returns a :class:`WaterBudget`. The water table
    is a linear reservoir in head anomaly h: ``h += (R/S_y - h/tau) dt`` with ``R`` the recharge in
    metres and ``dt = 1`` month; ``wt_depth = wt_depth0 - h`` (rising head -> shallower table).
    Capillary rise uses the *previous* step's table (explicit coupling), so the loop
    theta -> recharge -> table -> capillary rise -> theta is closed without an implicit solve.
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
    tau = max(recession_months, 1e-6)

    theta = np.empty_like(liquid)
    wt = np.empty_like(liquid); rech_o = np.empty_like(liquid)
    run_o = np.empty_like(liquid); aet_o = np.empty_like(liquid); cap_o = np.empty_like(liquid)

    for t in range(nt):
        wt_depth = wt0 - h                                    # current table depth (m)
        deficit_frac = (Ssat - S) / span
        cap = _capillary_rise(wt_depth, root_depth_m, deficit_frac, cap_max_mm, cap_fringe_m)
        cap_eff = np.minimum(S + cap, Ssat) - S              # actual added (exact mass balance)
        S = S + cap_eff

        S = S + liquid[t]
        runoff = np.maximum(S - Ssat, 0.0); S = S - runoff   # saturation-excess surface runoff
        aet = np.minimum(pet[t], np.maximum(S - Swp, 0.0)); S = S - aet
        rech = np.maximum(S - Sfc, 0.0) * drain_frac; S = S - rech   # deep percolation = recharge
        S = np.clip(S, Swp, Ssat)

        theta[t] = S / z
        rech_o[t] = rech; run_o[t] = runoff; aet_o[t] = aet; cap_o[t] = cap_eff

        # water-table reservoir: recharge (m) raises head, recession lowers it
        h = h + (rech / 1000.0 / max(specific_yield, 1e-6) - h / tau)
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
