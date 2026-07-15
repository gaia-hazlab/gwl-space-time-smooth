"""Ground sensors on the twin, and the spatial support of a dv/v measurement.

Run: ``pixi run sensor-figure``
"""
from __future__ import annotations

import shutil
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rioxarray as rxr
from matplotlib.colors import LogNorm
from pyproj import Transformer

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROC = Path("data/processed")
ASSETS = Path("docs/twin/assets")
OUT = Path("figures/demo/sensors_and_dvv_support.png")
STEP = 12                       # coarse grid: the kernel is smooth, and the pair count (printed at the
                                # end, and set by max_pair_km) drives the cost


def main():
    try:
        from src.viz.fonts import register_inter
        register_inter()
    except Exception:
        pass
    from src.config.domain import DOMAIN
    from src.models.dvv_sensitivity import (
        LAPSE_TIME_S,
        network_sensitivity,
        sensitivity_to_sigma,
        single_station_kernel,
    )

    hand = rxr.open_rasterio(PROC / "terrain_hand_domain_90m.tif", masked=True).squeeze("band", drop=True)
    x0, y0, x1, y1 = DOMAIN.bounds()
    tf = Transformer.from_crs("EPSG:4326", DOMAIN.crs, always_xy=True)

    def to_px(lon, lat):
        x, y = tf.transform(np.asarray(lon), np.asarray(lat))
        return (x - x0) / DOMAIN.res_m, (y1 - y) / DOMAIN.res_m, x, y

    seis = pd.read_parquet("data/cache/seismic/inventory_UW-CC.parquet")
    wells = pd.read_parquet(PROC / "nwis_sites_clean.parquet")
    # SNOTEL station locations, offline-safe: prefer the SWE table, fall back to the soil-moisture
    # table (same network), and only reach for the network as a last resort. A figure should not fail
    # because a data provider's DNS is down.
    snotel = pd.read_parquet(PROC / "snotel_swe_daily.parquet").drop_duplicates("triplet")
    if "lat" not in snotel.columns:
        sm = PROC / "snotel_soil_moisture_monthly.parquet"
        if sm.exists():
            snotel = pd.read_parquet(sm).drop_duplicates("triplet")
        else:
            from src.data.fetch_snotel_swe import find_swe_stations
            snotel = find_swe_stations()
    gauges = pd.read_parquet(PROC / "usgs_discharge_mvp.parquet").drop_duplicates("site_no")

    # gauges carry no lat/lon in the discharge table; take them from the basin polygons' centroid
    import geopandas as gpd
    basins = gpd.read_file(PROC / "gauge_basins.gpkg").to_crs(DOMAIN.crs)
    from src.data.fetch_usgs_discharge import PUGET_GAGES
    if len(basins) < len(PUGET_GAGES):
        print("NOTE: gauge_basins.gpkg holds %d of %d gauges; re-run `pixi run gauge-basins` to refresh"
              % (len(basins), len(PUGET_GAGES)))

    rows, cols = hand.shape

    def clip(lon, lat):
        """Sensors OUTSIDE the domain are dropped, not plotted off-canvas: the well catalogue spans
        the whole state, and letting it set the axis limits shrinks the domain to a postage stamp."""
        px, py, xm, ym = to_px(lon, lat)
        keep = (px >= 0) & (px < cols) & (py >= 0) & (py < rows)
        return px[keep], py[keep], xm[keep], ym[keep]

    sx, sy, sxm, sym = clip(seis.lon, seis.lat)
    wx, wy, *_ = clip(wells.lon, wells.lat)
    nx, ny, *_ = clip(snotel.lon, snotel.lat)
    st_km = np.column_stack([sxm / 1000.0, sym / 1000.0])

    # --- coda sensitivity on a coarse grid -------------------------------------------------------
    sub = hand.isel(y=slice(None, None, STEP), x=slice(None, None, STEP))
    gx, gy = np.meshgrid(sub.x.values / 1000.0, sub.y.values / 1000.0)
    pair_s, n_pairs = network_sensitivity(gx, gy, st_km, max_pair_km=40.0, include_single=False)
    single_s = np.zeros_like(gx)
    for sxy in st_km:
        single_s += single_station_kernel(gx, gy, sxy)
    combined = pair_s + single_s
    sigma = sensitivity_to_sigma(combined)
    land = np.isfinite(sub.values)
    pair_s = np.where(land, pair_s, np.nan)
    single_s = np.where(land, single_s, np.nan)
    sigma = np.where(land, sigma, np.nan)

    fig, ax = plt.subplots(1, 4, figsize=(21.0, 5.6), constrained_layout=True)

    # 1. the networks
    bg = np.where(np.isfinite(hand.values), hand.values, np.nan)
    ax[0].imshow(bg, cmap="Greys", vmin=0, vmax=400, alpha=.55)
    ax[0].set_xlim(0, cols); ax[0].set_ylim(rows, 0)      # pin to the domain, not to the sensors
    ax[0].scatter(wx, wy, s=7, c="#2E86AB", label=f"NWIS wells ({len(wx)})  — saturated store",
                  edgecolors="none")
    ax[0].scatter(nx, ny, s=42, c="#3BB273", marker="^",
                  label=f"SNOTEL SWE ({len(nx)})  — snow / vadose", edgecolors="k", linewidths=.4)
    for _, b in basins.iterrows():
        c = b.geometry.centroid
        ax[0].scatter((c.x - x0) / DOMAIN.res_m, (y1 - c.y) / DOMAIN.res_m, s=70, c="#F6AE2D",
                      marker="s", edgecolors="k", linewidths=.5, zorder=4)
    ax[0].scatter([], [], s=70, c="#F6AE2D", marker="s", edgecolors="k",
                  label=f"USGS gauges ({len(basins)})  — fluxes")
    ax[0].scatter(sx, sy, s=48, c="#E84855", marker="*",
                  label=f"Seismic UW/CC ({len(sx)})  — dv/v", edgecolors="k", linewidths=.4, zorder=5)
    ax[0].set_title("Ground sensors over the twin", fontweight="bold")
    ax[0].legend(fontsize=7.5, loc="lower left", framealpha=.92)
    ax[0].set_xticks([]); ax[0].set_yticks([])

    stx = (st_km[:, 0] * 1000 - x0) / (DOMAIN.res_m * STEP)
    sty = (y1 - st_km[:, 1] * 1000) / (DOMAIN.res_m * STEP)

    def _stations(a):
        a.scatter(stx, sty, s=22, c="w", marker="*", edgecolors="k", linewidths=.4)

    # 2. inter-station (cross-correlation): sensitive ALONG THE PATH between receivers
    v = pair_s[np.isfinite(pair_s) & (pair_s > 0)]
    im = ax[1].imshow(pair_s, cmap="magma", norm=LogNorm(vmin=np.percentile(v, 25), vmax=v.max()))
    _stations(ax[1])
    ax[1].set_title("Inter-station  (cross-corr.)\n%d pairs — path between stations" % n_pairs,
                    fontweight="bold")
    fig.colorbar(im, ax=ax[1], shrink=.8, label="sensitivity (log)")
    ax[1].set_xticks([]); ax[1].set_yticks([])

    # 3. single-station (autocorrelation): sensitive AT each receiver, everywhere a station sits
    v = single_s[np.isfinite(single_s) & (single_s > 0)]
    im = ax[2].imshow(single_s, cmap="magma", norm=LogNorm(vmin=np.percentile(v, 25), vmax=v.max()))
    _stations(ax[2])
    ax[2].set_title("Single-station  (autocorr.)\n%d stations — at each receiver" % len(st_km),
                    fontweight="bold")
    fig.colorbar(im, ax=ax[2], shrink=.8, label="sensitivity (log)")
    ax[2].set_xticks([]); ax[2].set_yticks([])

    # 4. the combined uncertainty
    sg = np.where(np.isfinite(sigma), sigma, np.nan)
    cm = plt.get_cmap("viridis_r").copy(); cm.set_bad("#eef0f3")
    im = ax[3].imshow(np.clip(sg, 1, 12), cmap=cm, vmin=1, vmax=12)
    _stations(ax[3])
    ax[3].set_title("dv/v measurement uncertainty  $\\sigma \\propto S^{-1/2}$\n"
                    "combined, × the best-observed cell", fontweight="bold")
    fig.colorbar(im, ax=ax[3], shrink=.8, label="relative σ")
    ax[3].set_xticks([]); ax[3].set_yticks([])

    fig.suptitle("dv/v is measured over a VOLUME, not at a cell — inter-station samples the path "
                 "BETWEEN receivers, single-station samples AT each one; combined, they separate the two\n"
                 "The twin evaluates dv/v at every cell as a FORWARD prediction; "
                 "this is where a measurement can test it  (early coda, lapse %.0f s)" % LAPSE_TIME_S,
                 fontsize=12, fontweight="bold")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=125, bbox_inches="tight", facecolor="white")
    shutil.copy(OUT, ASSETS / OUT.name)
    print("wrote %s  (%d pairs + %d single-station, %d seismic stations)" % (OUT, n_pairs, len(st_km), len(sx)))


if __name__ == "__main__":
    main()
