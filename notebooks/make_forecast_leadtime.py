"""Daily +1..+15 day forecast of the soil hydromechanical state, on the real 90 m grid.

Drives the coupled water budget forward one day at a time from a daily rainfall forecast and maps it
onto theta / water table / Vs30 (and the two dv/v bands). The rainfall source is swappable:

  --forcing-zarr s3://gaia/soil-twin/forecast/fuxi/<init>.zarr
                                               real AI forecast (FuXi, 0.25 deg, 15-day cascade),
                                               staged to Kopah by src.data.fetch_earth2studio on a
                                               GPU host and read lazily -- no file copy
  --scenario ar                                a documented atmospheric-river SCENARIO (clearly
                                               labelled as such -- NOT an observation, NOT a forecast)

Everything downstream of the forcing is the real physics on the real static layers, so swapping in the
AI forecast changes one flag and nothing else.

Writes figures/demo/forecast_leadtime.png (+ docs/twin/assets/).
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rioxarray as rxr
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models.forecast import ForecastForcing, forecast_soil_state  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("forecast_leadtime")

PROC = Path("data/processed")
OUT = Path("figures/demo/forecast_leadtime.png")

try:
    from src.viz.fonts import register_inter
    register_inter()
except Exception:
    pass


def _scenario_ar(n_days=15, total_mm=220.0, tmean_c=7.0):
    """A documented atmospheric-river SCENARIO: a 3-day AR landfall inside a 15-day window.

    This is a *scenario*, not a forecast and not an observation. It exists so the chain can be
    exercised end to end without a GPU; the real FuXi forcing replaces it with one flag.
    """
    p = np.zeros(n_days)
    p[4:7] = total_mm / 3.0                      # AR landfall on days +5..+7
    p[7:10] = 6.0                                # trailing frontal drizzle
    return p, np.full(n_days, tmean_c)


def main(argv=None):
    ap = argparse.ArgumentParser(description="+1..+15 day soil-state forecast on the 90 m grid.")
    ap.add_argument("--forcing-zarr", default=None,
                    help="Daily AI forecast Zarr (precip_mm, tmean_c): a local .zarr or a Kopah "
                         "s3://gaia/soil-twin/forecast/... URI, read lazily (no download).")
    ap.add_argument("--scenario", default="ar", choices=["ar"],
                    help="Fallback scenario when no --forcing-nc is given.")
    ap.add_argument("--lead-days", type=int, default=15)
    ap.add_argument("--title", default=None, help="Override the figure title (e.g. HINDCAST).")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)

    # --- static layers (real) --------------------------------------------------------------------
    env = xr.open_zarr(PROC / "soil_hydraulic_envelope_90m.zarr")
    vs30 = rxr.open_rasterio(PROC / "vs30_90m.tif", masked=True).squeeze("band", drop=True)
    dtw0 = rxr.open_rasterio(PROC / "baseline_dtw_m.tif", masked=True).squeeze("band", drop=True)
    solus = xr.open_zarr(PROC / "solus100_wa.zarr").rio.write_crs("EPSG:5070")
    sand = solus["sand_pct"].rio.reproject_match(vs30).values
    clay = solus["clay_pct"].rio.reproject_match(vs30).values

    wp, fc, sat = (env[k].values for k in ("theta_wp", "theta_fc", "theta_sat"))
    land = np.isfinite(vs30.values) & np.isfinite(dtw0.values) & np.isfinite(wp) & np.isfinite(sand)
    logger.info("analysis grid %s, %d land cells", vs30.shape, int(land.sum()))

    # --- forcing ---------------------------------------------------------------------------------
    n = a.lead_days
    pet_series = None
    if a.forcing_zarr:
        from src.io.zarr_store import open_zarr
        f = open_zarr(a.forcing_zarr)
        src = f.attrs.get("source", str(a.forcing_zarr))
        tdim = "lead_time" if "lead_time" in f["precip_mm"].dims else "time"
        n = min(n, f.sizes[tdim]) if a.lead_days else f.sizes[tdim]

        def _mean(v):                       # area-mean the coarse forcing (4 km PRISM / 28 km FuXi)
            return f[v].mean(dim=[d for d in f[v].dims if d != tdim]).values[:n]
        pr, tm = _mean("precip_mm"), _mean("tmean_c")
        if "pet_mm" in f:                   # PRISM ships a real Hamon PET; use it, do not invent one
            pet_series = _mean("pet_mm")
        logger.info("forcing: %s (%d d, %.0f mm total, area mean)", src, n, np.nansum(pr))
    else:
        pr, tm = _scenario_ar(n)
        src = "SCENARIO: 3-day atmospheric river (not a forecast, not an observation)"
        logger.warning("No --forcing-zarr; using %s", src)

    # broadcast the (coarse / scenario) daily forcing over the 90 m grid
    shp = (n,) + vs30.shape
    precip = np.broadcast_to(pr[:, None, None], shp).astype("float64")
    tmean = np.broadcast_to(tm[:, None, None], shp).astype("float64")
    if pet_series is not None:
        pet = np.broadcast_to(pet_series[:, None, None], shp).astype("float64")
    else:
        pet = np.full(shp, 0.6)                   # fallback: winter PNW PET ~0.6 mm/day (Hamon-scale)

    forcing = ForecastForcing(times=np.arange(1, n + 1), precip_mm=precip, pet_mm=pet,
                              dt_days=1.0, tmean_c=tmean, source=src)

    # --- forecast the soil state -----------------------------------------------------------------
    fcst = forecast_soil_state(forcing, theta_wp=wp, theta_fc=fc, theta_sat=sat,
                               vs30_base=vs30.values, wt_depth0_m=dtw0.values,
                               sand_pct=sand, clay_pct=clay)

    def m(a_):                                    # land-masked spatial mean per lead day
        x = np.where(land[None, :, :], a_, np.nan)
        return np.nanmean(x.reshape(n, -1), axis=1)

    th, wt, v30 = m(fcst.theta), m(fcst.wt_depth_m), m(fcst.vs30)
    dhi, dlo = m(fcst.dvv_high), m(fcst.dvv_low)
    ro, rc = m(fcst.runoff_mm), m(fcst.recharge_mm)
    lead = np.arange(1, n + 1)

    # --- figure ----------------------------------------------------------------------------------
    fig, ax = plt.subplots(2, 3, figsize=(13.5, 7.2), constrained_layout=True)
    C = "#2E86AB"; R = "#E84855"; G = "#3BB273"; P = "#7B2D8B"

    ax[0, 0].bar(lead, pr, color=C, width=0.7)
    ax[0, 0].set_title("Rainfall forcing", fontweight="bold"); ax[0, 0].set_ylabel("mm / day")

    ax[0, 1].plot(lead, th, "o-", color=G, lw=2)
    ax[0, 1].set_title("Soil moisture θ", fontweight="bold"); ax[0, 1].set_ylabel("m³ m⁻³")

    ax[0, 2].plot(lead, wt, "o-", color=C, lw=2)
    ax[0, 2].invert_yaxis()
    ax[0, 2].set_title("Water-table depth", fontweight="bold"); ax[0, 2].set_ylabel("m below surface")

    ax[1, 0].plot(lead, v30, "o-", color=P, lw=2)
    ax[1, 0].set_title("Vs30 (near-surface stiffness)", fontweight="bold"); ax[1, 0].set_ylabel("m s⁻¹")

    ax[1, 1].plot(lead, 100 * dhi, "o-", color=R, lw=2, label="shallow (moisture)")
    ax[1, 1].plot(lead, 100 * dlo, "s-", color=C, lw=2, label="deep (water table)")
    ax[1, 1].axhline(0, color="#999", lw=0.8)
    ax[1, 1].set_title("dv/v by band — the observable", fontweight="bold")
    ax[1, 1].set_ylabel("dv/v (%)"); ax[1, 1].legend(fontsize=8, frameon=False)

    ax[1, 2].bar(lead - 0.18, rc, width=0.36, color=G, label="recharge")
    ax[1, 2].bar(lead + 0.18, ro, width=0.36, color=R, label="runoff")
    ax[1, 2].set_title("Fluxes", fontweight="bold"); ax[1, 2].set_ylabel("mm / day")
    ax[1, 2].legend(fontsize=8, frameon=False)

    for x in ax.ravel():
        x.set_xlabel("day"); x.grid(alpha=0.25, lw=0.6)
        x.set_xticks(lead[::max(1, n // 8)])

    fig.suptitle(a.title or f"Soil-state forecast, lead +1…+{n} days (90 m Puget/Cascades)\n{src}",
                 fontsize=12, fontweight="bold")
    out = a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight", facecolor="white")
    logger.info("wrote %s", out)
    assets = Path("docs/twin/assets"); assets.mkdir(parents=True, exist_ok=True)
    shutil.copy(out, assets / out.name)

    logger.info("lead+1  θ=%.3f  WT=%.2f m  Vs30=%.1f", th[0], wt[0], v30[0])
    logger.info("lead+%-2d θ=%.3f  WT=%.2f m  Vs30=%.1f  | dv/v shallow %+.2f%%, deep %+.4f%%",
                n, th[-1], wt[-1], v30[-1], 100 * dhi[-1], 100 * dlo[-1])


if __name__ == "__main__":
    main()
