"""D7: joint calibration of the flux partition against GAUGES and WELLS (#98, closes #88/#90).

Calibrated in DAILY mode -- the mode we forecast in. Daily and monthly drain 4.7x differently (#89),
so a monthly calibration is invalid here; that mistake already produced one false "perfect fit".

Three parameters, each constrained by a DIFFERENT observation, so this is not curve-fitting:

    k_aniso              interflow partition     <- constrained by QUICKFLOW / the runoff coefficient
    recharge_ref_mm_day  river-sink strength     <- constrained by BASEFLOW and the BFI
    specific_yield       storage per unit head   <- constrained by the water-table AMPLITUDE

Targets, all measured earlier and none invented here:
    BFI               0.47   (Lyne-Hollick separation, 6 gauges, Sep-Mar)
    Q/P               0.65   (per-basin closure, Newaukum 0.57 / Clarks 0.73)
    peak month        April  (26,816 shallow-well obs; and the snowmelt clock, #100)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rioxarray as rxr
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.domain import DOMAIN  # noqa: E402
from src.io.zarr_store import open_zarr  # noqa: E402
from src.models.forecast import liquid_input, ForecastForcing  # noqa: E402
from src.models.water_budget import coupled_water_budget  # noqa: E402

BFI_OBS, QP_OBS, PEAK_OBS = 0.47, 0.65, 4
AMP_OBS = 1.06          # water-table seasonal amplitude (m), 26,816 shallow-well obs
STEP = 6


def setup():
    g = lambda f: rxr.open_rasterio(f"data/processed/{f}", masked=True).squeeze("band", drop=True)  # noqa: E731
    soil = xr.open_zarr("data/processed/soil_domain_90m.zarr")
    wt = xr.open_zarr("data/processed/baseline_wt_domain_90m.zarr")
    f = open_zarr("data/processed/prism_daily_2025-09_2026-06.zarr").rio.write_crs("EPSG:4326")
    sub = DOMAIN.template().isel(y=slice(None, None, STEP), x=slice(None, None, STEP))
    P = f.precip_mm.rio.reproject_match(sub).values
    T = f.tmean_c.rio.reproject_match(sub).values
    E = f.pet_mm.rio.reproject_match(sub).values
    times = pd.to_datetime(f.time.values)
    sl = (slice(None, None, STEP), slice(None, None, STEP))
    env = {k: soil[k].values[sl] for k in ("theta_wp", "theta_fc", "theta_sat")}
    d0 = wt.dtw_m.values[sl]
    hd = g("terrain_hand_domain_90m.tif").values[sl]
    tb = np.tan(np.radians(g("terrain_slope_domain_90m.tif").values[sl]))
    rd = soil.root_depth_m.values[sl]

    # snow ON, with the SNOTEL-calibrated parameters, and SPATIALLY DISTRIBUTED temperature --
    # the domain mean is ~7 C and forms no snow at all (#100).
    fo = ForecastForcing(times=times.values, precip_mm=P, pet_mm=E, dt_days=1.0, tmean_c=T,
                         source="PRISM")
    liquid = liquid_input(fo)
    land = np.isfinite(d0) & np.isfinite(env["theta_wp"]) & np.isfinite(hd) & np.isfinite(tb)
    return liquid, E, env, d0, hd, tb, rd, times, land, float(np.nansum(P.mean(axis=(1, 2))))


def score(ka, rref, sy, liquid, E, env, d0, hd, tb, rd, times, land, Ptot):
    r = coupled_water_budget(liquid, E, env["theta_wp"], env["theta_fc"], env["theta_sat"],
                             root_depth_m=rd, wt_depth0_m=d0, dt_days=1.0,
                             specific_yield=sy, slope_tan=tb, k_aniso=ka, hand_m=hd,
                             recharge_ref_mm_day=rref)
    M = lambda a: float(np.nanmean(np.nansum(a, 0)[land]))  # noqa: E731
    ro, it, bf = M(r.runoff_mm), M(r.interflow_mm), M(r.baseflow_mm)
    Q = ro + it + bf
    bfi = bf / max(Q, 1e-9)
    qp = Q / max(Ptot, 1e-9)
    rise = d0[None, :, :] - r.wt_depth_m
    ser = np.array([np.nanmean(rise[i][land]) for i in range(len(times))])
    mon = pd.Series(ser, index=times).groupby(times.month).mean()
    peak = int(mon.idxmax())
    amp = float(mon.max() - mon.min())
    dph = min(abs(peak - PEAK_OBS), 12 - abs(peak - PEAK_OBS))
    # AMPLITUDE must be in the objective. It is the ONLY thing that constrains specific_yield
    # (amplitude ~ recharge / S_y), and leaving it out let S_y drift to the edge of the grid at 0.05,
    # giving a 5.4 m seasonal swing against an observed 1.06 m -- fluxes right, storage wrong.
    mis = (abs(bfi - BFI_OBS) / BFI_OBS + abs(qp - QP_OBS) / QP_OBS
           + abs(amp - AMP_OBS) / AMP_OBS + dph / 3.0)
    return mis, bfi, qp, peak, ro, it, bf, amp


def main():
    S = setup()
    print("target:  BFI %.2f | Q/P %.2f | water-table peak month %d\n" % (BFI_OBS, QP_OBS, PEAK_OBS))
    print("%-24s %6s %6s %6s   %s" % ("params", "BFI", "Q/P", "peak", "runoff/interflow/baseflow (mm)"))
    best = None
    for ka in (1, 2, 5, 10, 20):
        for rref in (1.0, 3.0, 6.0, 10.0):
            for sy in (0.05, 0.10, 0.15, 0.20, 0.30, 0.40):
                mis, bfi, qp, pk, ro, it, bf, amp = score(ka, rref, sy, *S)
                if best is None or mis < best[0]:
                    best = (mis, ka, rref, sy, bfi, qp, pk, ro, it, bf, amp)
    mis, ka, rref, sy, bfi, qp, pk, ro, it, bf, amp = best
    print()
    print("%-30s %6s %6s %7s %6s" % ("", "BFI", "Q/P", "amp(m)", "peak"))
    print("%-30s %6.2f %6.2f %7.2f %6d" % ("BEST  Ka=%d R=%.0f Sy=%.2f" % (ka, rref, sy),
                                           bfi, qp, amp, pk))
    print("%-30s %6.2f %6.2f %7.2f %6d" % ("OBSERVED", BFI_OBS, QP_OBS, AMP_OBS, PEAK_OBS))
    print()
    print("  fluxes: runoff %.0f / interflow %.0f / baseflow %.0f mm" % (ro, it, bf))
    print("  BEFORE everything: BFI 0.00 (never recorded) | Q/P 0.96 | rise +3.24 m")


if __name__ == "__main__":
    main()
