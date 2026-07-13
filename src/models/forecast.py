"""Forecast the soil hydromechanical state (theta, water table, Vs) from a rainfall forecast.

This is the forcing-agnostic forecast engine. It takes *any* precipitation forecast — an AI weather
model (GraphCast via earth2studio), a NWP QPF, or a historical reanalysis replayed as a pseudo-
forecast — and drives the existing coupled water budget forward at the timestep the forcing actually
has, then maps the resulting water state onto near-surface stiffness through the petrophysical
coupling. Nothing here knows or cares where the rain came from: the AI model lives behind
:class:`ForecastForcing`, which is the only contract.

Chain:

    precip, T  ->  PET (Hamon)  ->  snow / liquid input  ->  coupled water budget  ->  theta, WTD
                                                                                        |
                                                    petrophysical coupling (dvv_coupling)|
                                                                                        v
                                                                                   Vs30(t)

Expected behaviour, and what to check before believing any output:

  - **theta responds within days** and is the large, fast signal. So does the **shallow (moisture)
    dv/v band**, which moves orders of magnitude more than the deep (head) band -- this is why dv/v is
    the right observable for a storm-scale forecast.
  - The **water table rises fast but recedes slowly**. The linear reservoir applies ``h += R/S_y``, so
    a 160 mm recharge event at ``S_y = 0.12`` lifts the table ~1.3 m *immediately*; the ~6-month tau
    governs the **recession**, not the rise. (Do not expect a flat water table over a 10-day storm --
    an earlier version of this docstring claimed exactly that, and it was wrong.)
  - **Vs30 barely moves** even when the moisture signal is large, because the vadose root zone is only
    ``d/30`` of the averaging depth. A 1 m root zone wetting by 6% in velocity moves Vs30 by ~0.2%.
    That is physically right and worth internalising: **dv/v sees the storm; Vs30 mostly does not.**

Known limitation (first-order on this exact horizon): recharge leaving the root zone is applied to the
water table **instantaneously**. In reality it must percolate the unsaturated zone between the root
base and the table (metres, i.e. days to weeks), so storm-scale water-table timing here is *early*.
An unsaturated travel-time lag is the main missing physics for a 10-day GWL forecast (see issue).

Vs30 response is first-order travel-time weighted: a fractional velocity change confined to the
vadose root zone (depth ``d``) contributes ``d/30`` of itself to the Vs30 fractional change, and the
saturated response below carries the rest. This is an MVP approximation to the full depth-kernel
treatment in :mod:`src.models.dvv` (calibration-pending).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.models.dvv_coupling import coupling_envelope, forward_dvv
from src.models.water_budget import coupled_water_budget

VS30_TOP_M = 30.0

# Degree-day snow parameters, CALIBRATED against 28 SNOTEL SWE stations in the domain (881-1414 m),
# fitting MELT-OUT TIMING rather than SWE RMSE. That distinction matters: RMSE is dominated by the
# accumulation season and selecting on it picked ddf=1.5, which melted so slowly the pack lingered
# into June and pushed melt release into MAY -- when the wells peak in APRIL. Fitting when the snow
# actually LEAVES recovers the April melt peak. The snowpack is the water table's clock (#100).
DDF_MM_C_DAY = 3.0      # melt factor (mm / degC / day)
T_SNOW_LO = 0.0         # all snow below this
T_SNOW_HI = 4.0         # all rain above this
T_MELT = 1.0            # melt threshold


@dataclass
class ForecastForcing:
    """A precipitation forecast on a grid, at whatever timestep it natively has.

    ``precip_mm`` and ``pet_mm`` are fluxes **per timestep** (mm/step), shape ``(t, ...)``.
    ``dt_days`` is the step length in days — this is the field that must match the fluxes, and the
    one that silently ruins the run if it does not (per-month rates driven with mm/day).
    """

    times: np.ndarray            # (t,) datetime64
    precip_mm: np.ndarray        # (t, ...) mm per step
    pet_mm: np.ndarray           # (t, ...) mm per step
    dt_days: float               # step length (days)
    tmean_c: np.ndarray | None = None   # (t, ...) degC, for the snow partition
    source: str = "unknown"      # provenance, e.g. "graphcast_small/1.0deg"

    def __post_init__(self):
        if self.precip_mm.shape != self.pet_mm.shape:
            raise ValueError("precip_mm and pet_mm must have the same shape")
        if len(self.times) != self.precip_mm.shape[0]:
            raise ValueError("times must match the leading axis of precip_mm")
        if not np.isfinite(self.dt_days) or self.dt_days <= 0:
            raise ValueError("dt_days must be a positive number of days")


@dataclass
class SoilStateForecast:
    """Forecast trajectory of the coupled soil state."""

    times: np.ndarray
    theta: np.ndarray            # (t, ...) m3/m3
    wt_depth_m: np.ndarray       # (t, ...) m below surface (smaller = shallower)
    vs30: np.ndarray             # (t, ...) m/s
    vs30_frac: np.ndarray        # (t, ...) fractional change from the baseline
    dvv_low: np.ndarray          # (t, ...) deep / water-table dv/v (the slow band)
    dvv_high: np.ndarray         # (t, ...) shallow / moisture dv/v (the fast band)
    runoff_mm: np.ndarray
    recharge_mm: np.ndarray
    source: str


def liquid_input(forcing, ddf_mm_c_day=DDF_MM_C_DAY, t_snow_hi=T_SNOW_HI,
                 t_snow_lo=T_SNOW_LO, t_melt=T_MELT):
    """Partition precipitation into liquid input (rain + snowmelt) with a degree-day snow model.

    Returns ``precip_mm`` unchanged when no temperature is supplied. The degree-day factor is per
    **day**, so it is scaled by ``dt_days`` — a 10-day winter forecast over the Cascades is
    snow-dominated, and treating snowfall as rain would fabricate an immediate soil-moisture and Vs
    response that does not physically happen until melt.
    """
    p = np.asarray(forcing.precip_mm, dtype="float64")
    if forcing.tmean_c is None:
        return p
    t = np.asarray(forcing.tmean_c, dtype="float64")
    # snow fraction ramps linearly from all-snow below t_snow_lo to all-rain above t_snow_hi
    rain_frac = np.clip((t - t_snow_lo) / max(t_snow_hi - t_snow_lo, 1e-6), 0.0, 1.0)
    rain, snow = p * rain_frac, p * (1.0 - rain_frac)

    out = np.empty_like(p)
    swe = np.zeros(p.shape[1:], dtype="float64")
    melt_cap = ddf_mm_c_day * forcing.dt_days                 # mm per degC per STEP
    for i in range(p.shape[0]):
        swe = swe + snow[i]
        melt = np.clip(melt_cap * (t[i] - t_melt), 0.0, None)
        melt = np.minimum(melt, swe)                          # cannot melt more snow than exists
        swe = swe - melt
        out[i] = rain[i] + melt
    return out


def forecast_soil_state(forcing, theta_wp, theta_fc, theta_sat, vs30_base, wt_depth0_m,
                        sand_pct=None, clay_pct=None, root_depth_m=1.0, slope_tan=None,
                        **budget_kw):
    """Drive the coupled water budget from a rainfall forecast and map it onto Vs30.

    ``theta_*`` and ``vs30_base`` / ``wt_depth0_m`` are the static envelope + baseline state on the
    analysis grid (they broadcast against the trailing dims of the forcing). Returns a
    :class:`SoilStateForecast`.

    The water state comes from :func:`coupled_water_budget` at the forcing's own ``dt_days``; the
    stiffness comes from the petrophysical coupling (Hertz-Mindlin + van Genuchten suction), *not*
    from a fitted correlation.
    """
    liquid = liquid_input(forcing)
    # slope_tan enables lateral interflow: drainage on a hillslope leaves DOWNSLOPE rather than
    # recharging the water table. Without it ~94% of rain becomes recharge (issue #88).
    wb = coupled_water_budget(liquid, forcing.pet_mm, theta_wp, theta_fc, theta_sat,
                              root_depth_m=root_depth_m, wt_depth0_m=wt_depth0_m,
                              dt_days=forcing.dt_days, slope_tan=slope_tan, **budget_kw)

    # petrophysical coupling: water state -> velocity change. theta_ref / wt reference are the
    # initial (t=0) state, so the forecast reports a change relative to the analysis, not an absolute.
    sand = np.broadcast_to(np.asarray(sand_pct if sand_pct is not None else 40.0, float),
                           np.shape(theta_sat) if np.ndim(theta_sat) else ())
    clay = np.broadcast_to(np.asarray(clay_pct if clay_pct is not None else 20.0, float),
                           np.shape(theta_sat) if np.ndim(theta_sat) else ())
    env = coupling_envelope(sand, clay, theta_wp, theta_sat)

    theta_ref = wb.theta[0]
    wt_ref = np.broadcast_to(np.asarray(wt_depth0_m, float), wb.wt_depth_m.shape[1:])
    dtw_anom = wb.wt_depth_m - wt_ref                          # +ve = table deeper than baseline

    d = forward_dvv(dtw_anom, wb.theta, theta_ref, env)
    dvv_low, dvv_high = d["dvv_low"], d["dvv_high"]

    # first-order travel-time weighting of the top 30 m: the vadose root zone carries d/30 of the
    # column, the saturated material below carries the rest.
    w_vadose = np.clip(root_depth_m / VS30_TOP_M, 0.0, 1.0)
    vs30_frac = w_vadose * dvv_high + (1.0 - w_vadose) * dvv_low
    vs30 = np.asarray(vs30_base, dtype="float64") * (1.0 + vs30_frac)

    return SoilStateForecast(
        times=forcing.times, theta=wb.theta, wt_depth_m=wb.wt_depth_m,
        vs30=vs30.astype("float32"), vs30_frac=np.asarray(vs30_frac, dtype="float32"),
        dvv_low=np.asarray(dvv_low, dtype="float32"),
        dvv_high=np.asarray(dvv_high, dtype="float32"),
        runoff_mm=wb.runoff_mm, recharge_mm=wb.recharge_mm, source=forcing.source,
    )
