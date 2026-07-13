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

    - **lateral interflow / subsurface stormflow**: drainage out of the root zone competes between a
      vertical velocity ~K_v and a downslope one ~K_h*tan(beta). With the anisotropy of layered forest
      soils most of it leaves DOWNSLOPE and reaches a stream in days rather than recharging the water
      table. Omitting it turned ~94% of rain into recharge (issue #88).

Mass is conserved by construction each step:
``dS = cap_rise + input - runoff - AET - recharge - interflow``, and the water table balances
``S_y * dh = recharge - baseflow``. Streamflow, the quantity a gauge actually measures, is
``Q = runoff + interflow + baseflow``.

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
# --- CALIBRATED (D7, #98) against the gauges AND the wells, in DAILY mode, with the snow clock on.
# Each parameter is pinned by a DIFFERENT observation, so this is a constrained fit, not curve-fitting:
#   specific_yield      <- water-table seasonal AMPLITUDE (1.06 m, 26,816 well obs)
#   k_aniso             <- QUICKFLOW / runoff coefficient Q/P (0.57-0.73, per-basin closure)
#   recharge_ref_mm_day <- BASEFLOW INDEX (0.47, Lyne-Hollick separation, 6 gauges)
# Result: BFI 0.52 (obs 0.47) | Q/P 0.71 (obs 0.65) | amplitude 1.02 m (obs 1.06 m).
SPECIFIC_YIELD = 0.30          # unconfined specific yield S_y -- calibrated (was a nominal 0.12)
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
# Lateral:vertical hydraulic-conductivity anisotropy K_h/K_v. Layered, macroporous forest soils are
# strongly anisotropic (literature 10-100), which is why hillslope drainage leaves DOWNSLOPE as
# interflow rather than recharging the water table. Calibration-pending (issue #88).
# NOTE, honestly: the fitted Ka is BELOW the 10-100 literature range for forest-soil anisotropy. On
# this steep domain (median slope 13.3 deg) Ka=20 drove f_lat to ~0.82 -- 82% of drainage shed
# laterally -- which starved recharge and gave Q/P 0.96 against an observed 0.65. Either the
# literature range does not transfer to a 90 m cell, or this single term is absorbing other processes.
# Flagged rather than dressed up.
K_ANISO = 2.0
# Groundwater discharge to the stream network (baseflow). The table relaxes toward the local drainage
# elevation (HAND) on this timescale -- the rivers take the water away. This is the SELF-LIMITING sink
# the model lacked: without it recharge piles up and the water table runs away (issue #88).
# Long-term mean recharge used to anchor the stream-discharge coefficient so the OBSERVED baseline
# water table is a steady state. PNW: ~1500 mm/yr precip, ~40% recharge -> ~600 mm/yr ~ 1.6 mm/day.
RECHARGE_REF_MM_DAY = 3.0      # calibrated (D7, #98)


@dataclass
class WaterBudget:
    """Coupled state + fluxes on a (time, ...) grid. All storages in m^3/m^3 or m; fluxes in mm."""

    theta: np.ndarray          # (t, ...) volumetric soil moisture
    wt_depth_m: np.ndarray     # (t, ...) water-table depth below surface (m; smaller = shallower)
    recharge_mm: np.ndarray    # (t, ...) deep percolation to the water table
    runoff_mm: np.ndarray      # (t, ...) saturation-excess surface runoff generated
    interflow_mm: np.ndarray   # (t, ...) lateral subsurface stormflow leaving the column downslope
    baseflow_mm: np.ndarray    # (t, ...) groundwater discharged to the stream network ("the rivers")
    aet_mm: np.ndarray         # (t, ...) actual evapotranspiration
    cap_rise_mm: np.ndarray    # (t, ...) capillary rise from the water table into the root zone


def _capillary_rise(wt_depth_m, root_depth_m, deficit_frac, cap_max_mm, fringe_m):
    """Upward flux (mm) from a shallow water table into the root zone.

    Zero when the table is deeper than the root-zone base plus the capillary fringe; otherwise it
    scales with how close the table is to the root zone and with the current storage deficit
    (a full column pulls nothing up). ``deficit_frac`` in [0, 1] is (S_sat - S)/(S_sat - S_wp).
    """
    # root_depth_m may be a PER-CELL array (D3 derives it from soil thickness), so use np.maximum --
    # Python's max() raises on arrays, and root depth was a scalar until the soils were regridded.
    reach = np.asarray(root_depth_m, dtype="float64") + fringe_m
    proximity = np.clip((reach - wt_depth_m) / np.maximum(reach, 1e-6), 0.0, 1.0)
    return cap_max_mm * proximity * np.clip(deficit_frac, 0.0, 1.0)


def coupled_water_budget(liquid_in_mm, pet_mm, theta_wp, theta_fc, theta_sat, root_depth_m=1.0,
                         specific_yield=SPECIFIC_YIELD, recession_months=RECESSION_MONTHS,
                         cap_max_mm=CAP_MAX_MM, cap_fringe_m=CAP_FRINGE_M, drain_frac=_DRAIN_FRAC,
                         wt_depth0_m=5.0, init="fc", dt_days=None, drain_tau_days=DRAIN_TAU_DAYS,
                         sat_area_runoff=True, slope_tan=None, k_aniso=K_ANISO,
                         hand_m=None, recharge_ref_mm_day=RECHARGE_REF_MM_DAY):
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

    # Groundwater discharge to the stream network -- "the rivers take the water away". Groundwater
    # standing ABOVE the local drainage (HAND is literally the Height Above Nearest Drainage) flows to
    # it, so the table relaxes toward the drainage elevation. This is the SELF-LIMITING sink the model
    # lacked: the higher the table climbs above the river, the harder it drains (issue #88).
    #
    # The coefficient is not free. A ridge water table genuinely sits tens of metres above the valley
    # stream -- that is normal and PERSISTENT, sustained by continuous recharge down a long, slow flow
    # path. So the discharge is anchored to make the OBSERVED baseline table a steady state: at the
    # long-term mean recharge R_ref, discharge exactly balances recharge. Storms then perturb around
    # that equilibrium. An arbitrary coefficient instead drains the baseline away (metres per month).
    #
    #     gw_recess_i = (R_ref/S_y) / [HAND_i - d0_i]_+
    #
    # Cells whose table already sits below the drainage (HAND < d0) do not discharge.
    hand = None if hand_m is None else np.clip(np.asarray(hand_m, dtype="float64"), 0.0, None)
    if hand_m is None:
        gw_recess = 0.0
    else:
        dt_d = float(dt_days if dt_days else DAYS_PER_MONTH)
        head0 = np.clip(hand - wt0, 0.0, None)                        # baseline head above the river
        r_ref = float(recharge_ref_mm_day) * dt_d / 1000.0            # m of water per step
        gw_recess = np.where(head0 > 1e-3,
                             (r_ref / max(specific_yield, 1e-6)) / np.clip(head0, 1e-3, None), 0.0)
        gw_recess = np.clip(gw_recess, 0.0, 1.0)

    # lateral fraction of root-zone drainage: f_lat = Ka*tan(beta) / (1 + Ka*tan(beta)).
    # Flat ground (tan beta = 0) -> f_lat = 0, i.e. ALL drainage recharges the water table, which is
    # correct: valley floors recharge, hillslopes shed. slope_tan=None reproduces the old behaviour.
    if slope_tan is None:
        f_lat = 0.0
    else:
        kt = np.clip(k_aniso * np.abs(np.asarray(slope_tan, dtype="float64")), 0.0, None)
        f_lat = kt / (1.0 + kt)

    theta = np.empty_like(liquid)
    int_o = np.empty_like(liquid)
    bf_o = np.empty_like(liquid)
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

        # --- drainage above field capacity: DOWN (recharge) vs DOWNSLOPE (interflow) --------------
        # Water leaving the root zone does not all go to the water table. On a slope it competes
        # between a vertical velocity ~K_v and a lateral one ~K_h*tan(beta); with the strong
        # anisotropy of layered/macroporous forest soils (K_a = K_h/K_v ~ 10-100) most of it leaves
        # DOWNSLOPE as interflow / subsurface stormflow and reaches a stream within days.
        # Forcing all of it vertically (the old behaviour) turned ~94% of rain into recharge and
        # over-predicted the water-table rise by 8-26x against the NWIS wells (issue #88).
        drain = np.maximum(S - Sfc, 0.0) * drain_step
        inter = drain * f_lat                                # leaves the column downslope
        rech = drain - inter                                 # the rest reaches the water table
        S = S - drain
        S = np.clip(S, Swp, Ssat)

        theta[t] = S / z
        rech_o[t] = rech; run_o[t] = runoff; aet_o[t] = aet; cap_o[t] = cap_eff; int_o[t] = inter

        # --- water table: recharge raises it, the RIVERS drain it ---------------------------------
        # Recharge (m of water) lifts the table by R/S_y. The sink is discharge to the stream
        # network: groundwater sitting ABOVE the local drainage flows to it (Dupuit). HAND is
        # literally the Height Above Nearest Drainage, so the head driving that discharge is
        # (HAND - wt_depth), and the table relaxes TOWARD the drainage elevation.
        #
        # This is self-limiting, which the old spatially-uniform h/tau recession was not: the higher
        # the table climbs above the river, the harder it drains, so recharge cannot pile up without
        # bound. Valley floors (HAND ~ 0) cannot rise at all; ridges can. Without it the water table
        # ran away (issue #88). hand_m=None keeps the legacy recession.
        h = h + rech / 1000.0 / max(specific_yield, 1e-6)
        if hand_m is None:
            drop = h * recess                                 # legacy: relax to the baseline
        else:
            d_now = wt0 - h                                   # current depth below surface (m)
            to_river = np.clip(hand - d_now, 0.0, None)       # head above the nearest drainage (m)
            drop = to_river * gw_recess                       # relax toward the drainage
        h = h - drop
        # RECORD the discharge as a flux. It was previously applied to the head but never reported,
        # so every budget comparison scored the model's baseflow as ZERO against an observed BFI of
        # ~0.5 -- an accounting artefact, not (only) a physics failure. A head drop of `drop` metres
        # releases S_y * drop of water to the stream.
        bf_o[t] = np.clip(drop, 0.0, None) * max(specific_yield, 1e-6) * 1000.0
        wt[t] = wt0 - h

    return WaterBudget(theta=theta.astype("float32"), wt_depth_m=wt.astype("float32"),
                       recharge_mm=rech_o.astype("float32"), runoff_mm=run_o.astype("float32"),
                       interflow_mm=int_o.astype("float32"), baseflow_mm=bf_o.astype("float32"),
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
