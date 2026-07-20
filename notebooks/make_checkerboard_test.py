"""Standard checkerboard resolution test: recovery of a regular anomaly pattern by each network
type alone, and combined -- for the water table (wells + deep dv/v) and soil moisture
(SNOTEL + shallow dv/v).

Run: ``pixi run checkerboard-test``

Replaces the earlier random-Gaussian-random-field "truth" (a smooth but irregular blob pattern that
is hard to read at a glance) with the tomography-standard checkerboard: a known, regular,
alternating-sign pattern at a chosen wavelength. Recovery quality and its spatial pattern (where a
network resolves the checker cells cleanly vs. smears/misses them) are then immediately legible, and
directly comparable across network combinations -- which is the point of a resolution test.
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
from pyproj import Transformer

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROC = Path("data/processed")
ASSETS = Path("docs/twin/assets")
OUT = Path("figures/demo/checkerboard_test.png")
STEP = 22
WAVELENGTH_KM = 24.0                    # checker cell size: 2 x the GWL correlation length below
GWL_L_KM, SM_L_KM = 6.0, 3.0
NOISE = dict(well=0.02, snotel=0.03, dvv_deep=0.25, dvv_shallow=0.12)


def checkerboard(coords_km: np.ndarray, wavelength_km: float) -> np.ndarray:
    r"""The standard tomography checkerboard: :math:`\sin(2\pi x/\lambda)\sin(2\pi y/\lambda)`.

    A regular, known, alternating-sign pattern -- the standard resolution-test input, precisely
    because "did the network recover this exact pattern" is a much sharper question than "did it
    recover this particular random draw."
    """
    x, y = coords_km[:, 0], coords_km[:, 1]
    k = 2.0 * np.pi / wavelength_km
    return np.sin(k * x) * np.sin(k * y)


def main():
    try:
        from src.viz.fonts import register_inter
        register_inter()
    except Exception:
        pass
    from src.config.domain import DOMAIN
    from src.models.dvv_sensitivity import pair_kernel, single_station_kernel
    from src.models.observability import (
        GaussianPrior,
        blue_update,
        normalise_footprint,
        point_footprint,
        resolution,
    )

    hand = rxr.open_rasterio(PROC / "terrain_hand_domain_90m.tif", masked=True).squeeze("band", drop=True)
    sub = hand.isel(y=slice(None, None, STEP), x=slice(None, None, STEP))
    land = np.isfinite(sub.values).ravel()
    gx, gy = np.meshgrid(sub.x.values / 1000.0, sub.y.values / 1000.0)
    coords = np.column_stack([gx.ravel(), gy.ravel()])
    shp = gx.shape
    x0, y0, x1, y1 = DOMAIN.bounds()
    tf = Transformer.from_crs("EPSG:4326", DOMAIN.crs, always_xy=True)

    def stations_km(lon, lat):
        xm, ym = tf.transform(np.asarray(lon), np.asarray(lat))
        keep = (xm >= x0) & (xm <= x1) & (ym >= y0) & (ym <= y1)
        return np.column_stack([xm[keep] / 1000.0, ym[keep] / 1000.0])

    wells = pd.read_parquet(PROC / "nwis_sites_clean.parquet")
    seis = pd.read_parquet("data/cache/seismic/inventory_UW-CC.parquet")
    swe, sm = PROC / "snotel_swe_daily.parquet", PROC / "snotel_soil_moisture_monthly.parquet"
    snotel = pd.read_parquet(swe) if swe.exists() else pd.DataFrame()
    if "lat" not in snotel.columns and sm.exists():
        snotel = pd.read_parquet(sm)

    well_km = stations_km(wells.lon, wells.lat)
    sno_km = stations_km(snotel.drop_duplicates("triplet").lon, snotel.drop_duplicates("triplet").lat)
    seis_km = stations_km(seis.lon, seis.lat)

    # --- the same checkerboard truth for both states -- only the observing NETWORK differs ---------
    truth = checkerboard(coords, WAVELENGTH_KM)

    def point_G(pts):
        return np.vstack([point_footprint(coords, p) for p in pts]) if len(pts) else np.empty((0, len(coords)))

    G_well, G_sno = point_G(well_km), point_G(sno_km)

    dvv_rows = []
    for i in range(len(seis_km)):
        dvv_rows.append(normalise_footprint(single_station_kernel(gx, gy, seis_km[i])))
        for j in range(i + 1, len(seis_km)):
            if np.hypot(*(seis_km[i] - seis_km[j])) <= 40.0:
                dvv_rows.append(normalise_footprint(pair_kernel(gx, gy, seis_km[i], seis_km[j])))
    G_dvv = np.vstack(dvv_rows)

    def m(v):
        return np.where(land, v, np.nan).reshape(shp)

    def recover(B, G_point, noise_point, G_dvv, noise_dvv, which):
        """Recover the checkerboard from ONE of: point network alone, dv/v alone, or both."""
        if which == "point":
            G, nv = G_point, np.full(len(G_point), noise_point)
        elif which == "dvv":
            G, nv = G_dvv, np.full(len(G_dvv), noise_dvv)
        else:
            G = np.vstack([G_point, G_dvv])
            nv = np.concatenate([np.full(len(G_point), noise_point), np.full(len(G_dvv), noise_dvv)])
        d = G @ np.nan_to_num(truth)                        # perfect (noise-free) forward data
        m_a, _ = blue_update(B, G, d, noise_var=nv)
        res, _ = resolution(B, G, nv)
        return m_a, res

    def corr(recovered, res):
        ok = np.isfinite(truth) & (res > 0.3)
        return np.corrcoef(recovered[ok], truth[ok])[0, 1] if ok.sum() > 1 else np.nan

    B_gwl = GaussianPrior(1.0, GWL_L_KM).cov(coords)
    B_sm = GaussianPrior(1.0, SM_L_KM).cov(coords)

    rows = [
        ("WATER TABLE", "#2E86AB", B_gwl, G_well, NOISE["well"], "Wells", well_km),
        ("SOIL MOISTURE", "#3BB273", B_sm, G_sno, NOISE["snotel"], "SNOTEL", sno_km),
    ]
    dvv_noise = {"WATER TABLE": NOISE["dvv_deep"], "SOIL MOISTURE": NOISE["dvv_shallow"]}

    fig, ax = plt.subplots(2, 4, figsize=(19.5, 9.7), constrained_layout=True)
    kw = dict(vmin=-1.0, vmax=1.0)
    cm = plt.get_cmap("RdBu_r").copy(); cm.set_bad("#eef0f3")

    for r, (state, col, B, G_pt, noise_pt, pt_label, pt_km) in enumerate(rows):
        nv_dvv = dvv_noise[state]
        m_point, res_point = recover(B, G_pt, noise_pt, G_dvv, nv_dvv, "point")
        m_dvv, res_dvv = recover(B, G_pt, noise_pt, G_dvv, nv_dvv, "dvv")
        m_both, res_both = recover(B, G_pt, noise_pt, G_dvv, nv_dvv, "both")

        panels = [
            (m(truth), f"Checkerboard truth\n($\\lambda$={WAVELENGTH_KM:.0f} km)", None),
            (m(m_point), f"{pt_label} alone\n(r={corr(m_point, res_point):.2f} where resolved)", pt_km),
            (m(m_dvv), f"dv/v alone\n(r={corr(m_dvv, res_dvv):.2f} where resolved)", None),
            (m(m_both), f"{pt_label} + dv/v\n(r={corr(m_both, res_both):.2f} where resolved)", pt_km),
        ]
        for cc, (field, title, station_km) in enumerate(panels):
            a = ax[r, cc]
            im = a.imshow(field, cmap=cm, **kw)
            if station_km is not None and len(station_km):
                stx = (station_km[:, 0] * 1000 - x0) / (DOMAIN.res_m * STEP)
                sty = (y1 - station_km[:, 1] * 1000) / (DOMAIN.res_m * STEP)
                a.scatter(stx, sty, s=14, c="k", marker="^", linewidths=0)
            a.set_title(title, fontsize=13, fontweight="bold")
            fig.colorbar(im, ax=a, shrink=.72)
            a.set_xticks([]); a.set_yticks([])
        ax[r, 0].set_ylabel(state, fontsize=15, fontweight="bold", color=col, labelpad=8)

    fig.suptitle("Checkerboard resolution test — recovery of a regular anomaly pattern by each network,\n"
                 "alone and combined (perfect forward data; recovery quality is the observing geometry, "
                 "not measurement noise)",
                 fontsize=15, fontweight="bold")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=120, bbox_inches="tight", facecolor="white")
    shutil.copy(OUT, ASSETS / OUT.name)
    print(f"wrote {OUT}  (wavelength={WAVELENGTH_KM:.0f} km, {len(well_km)} wells, "
          f"{len(sno_km)} SNOTEL, {G_dvv.shape[0]} dv/v footprints)")


if __name__ == "__main__":
    main()
