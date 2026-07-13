"""Close the water budget PER BASIN against the USGS gauges (issue #90).

The seasonal budget previously compared **domain-mean** PRISM against **gauge** discharge and got
Q (1639 mm) > P (1510 mm). That was not a mass violation: the gauge basins are Cascade *headwater*
catchments receiving far more orographic precipitation than the domain mean, so the mm columns were
never comparable. Here precipitation, the static layers, and the modelled fluxes are all averaged
over **each gauge's own watershed** (NLDI polygon), which is exactly the area the gauge integrates.

Only then does the comparison mean anything:

    P  =  Q(quickflow + baseflow)  +  AET  +  dS      [observed Q, from the gauge]
    P  =  runoff + interflow + recharge + AET + dS    [modelled]

and the observed baseflow index is the constraint the model must reproduce.

    pixi run basin-closure
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rioxarray as rxr
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.io.zarr_store import open_zarr  # noqa: E402
from src.models.water_budget import coupled_water_budget  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("basin_closure")

PROC = "data/processed"
PRISM = f"{PROC}/prism_daily_2025-09_2026-03.zarr"


def main():
    basins = gpd.read_file(f"{PROC}/gauge_basins.gpkg")
    gauges = pd.read_parquet(f"{PROC}/usgs_discharge_mvp.parquet")

    # forcing (lat/lon) and the 90 m static layers (EPSG:5070)
    pr = open_zarr(PRISM).rio.write_crs("EPSG:4326")
    env = xr.open_zarr(f"{PROC}/soil_hydraulic_envelope_90m.zarr").rio.write_crs("EPSG:5070")
    dtw = rxr.open_rasterio(f"{PROC}/baseline_dtw_m.tif", masked=True).squeeze("band", drop=True)
    slp = rxr.open_rasterio(f"{PROC}/terrain_slope_90m.tif", masked=True).squeeze("band", drop=True)
    hnd = rxr.open_rasterio(f"{PROC}/terrain_hand_90m.tif", masked=True).squeeze("band", drop=True)

    rows = []
    for _, b in basins.iterrows():
        geom4326 = gpd.GeoSeries([b.geometry], crs="EPSG:5070").to_crs("EPSG:4326")
        geom5070 = gpd.GeoSeries([b.geometry], crs="EPSG:5070")
        try:
            pb = pr.rio.clip(geom4326.geometry, geom4326.crs, drop=True)
        except Exception as exc:
            logger.warning("%s: PRISM clip failed (%s)", b.site_no, exc)
            continue
        sp = [d for d in pb.precip_mm.dims if d != "time"]
        P = pb.precip_mm.mean(dim=sp).values                  # basin-mean daily precip (mm/day)
        E = pb.pet_mm.mean(dim=sp).values
        Ptot = float(np.nansum(P))

        def clipm(da):
            try:
                return da.rio.clip(geom5070.geometry, geom5070.crs, drop=True).values
            except Exception:
                return np.array([np.nan])

        wp, fc, sat = (clipm(env[k]) for k in ("theta_wp", "theta_fc", "theta_sat"))
        d0, tb, hd = clipm(dtw), np.tan(np.radians(clipm(slp))), clipm(hnd)
        ok = np.isfinite(wp) & np.isfinite(d0) & np.isfinite(tb) & np.isfinite(hd)
        if ok.sum() < 10:
            logger.warning("%s: too few static cells in the basin; skipping", b.site_no)
            continue

        n = len(P)
        shp = (n,) + wp.shape
        wb = coupled_water_budget(
            np.broadcast_to(P[:, None, None], shp), np.broadcast_to(E[:, None, None], shp),
            wp, fc, sat, wt_depth0_m=d0, dt_days=1.0, specific_yield=0.10,
            slope_tan=tb, k_aniso=20.0, hand_m=hd)
        M = lambda a: float(np.nanmean(np.nansum(a, 0)[ok]))   # noqa: E731
        ro, it, rc, ae = M(wb.runoff_mm), M(wb.interflow_mm), M(wb.recharge_mm), M(wb.aet_mm)

        g = gauges[gauges.site_no == b.site_no]
        Q, B, F = g.q_mm_day.sum(), g.baseflow_mm_day.sum(), g.quickflow_mm_day.sum()
        rows.append(dict(site=b["name"][:22], km2=round(b.area_km2),
                         P=Ptot, Q_obs=Q, ratio=Q / Ptot,
                         qf_obs=F, qf_mod=ro + it, bf_obs=B, bf_mod=0.0,
                         bfi_obs=B / Q, rech_mod=rc, aet_mod=ae,
                         resid_obs=Ptot - Q, resid_mod=Ptot - (ro + it) - ae - rc))

    df = pd.DataFrame(rows)
    print("\nPER-BASIN WATER BUDGET, Fall-Winter 2025-2026 (mm over the season)")
    print("=" * 104)
    print(df.assign(**{c: df[c].round(2) if c in ("ratio", "bfi_obs") else df[c].round(0)
                       for c in df.columns if c not in ("site", "km2")}).to_string(index=False))
    print("=" * 104)
    print("  P        basin-mean PRISM (was domain-mean before -- that was the #90 bug)")
    print("  Q_obs    gauge discharge; ratio = Q/P (runoff coefficient)")
    print("  qf/bf    quickflow / baseflow, obs vs model")
    print("  resid    P - (all outgoing fluxes) = storage change; should be SMALL and POSITIVE")
    print()
    print("  MEDIAN runoff coefficient Q/P : %.2f   (observed)" % df.ratio.median())
    print("  MEDIAN baseflow index         : %.2f   (observed)  vs model %.2f" %
          (df.bfi_obs.median(), 0.0))
    print("  MEDIAN model residual (dS)    : %+.0f mm  <- water the model RETAINS as recharge" %
          df.resid_mod.median())
    print("  MEDIAN observed residual (dS) : %+.0f mm  <- what actually stayed in the ground" %
          df.resid_obs.median())
    df.to_csv(f"{PROC}/basin_budget_closure.csv", index=False)
    logger.info("wrote %s/basin_budget_closure.csv", PROC)


if __name__ == "__main__":
    main()
