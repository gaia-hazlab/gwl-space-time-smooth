"""Spatial resolution contributed by the STATIC LAYERS themselves, not just by the sensor
network -- and how much the network adds ON TOP of what the static layers already resolve.

Run: ``pixi run static-resolution-figure``

``make_observability_figure.py`` answers "how much does the sensor network reduce variance
relative to a spatially FLAT prior" -- by construction it credits zero spatial information to
HAND/soil/terrain, because the prior it compares against is a generic stationary Gaussian field.
But Stage 1 (`src/models/baseline_regression.py`) already resolves real 90 m spatial structure
from covariates alone, even far from any well: the random-forest tree-ensemble sigma
(`rf_std_m`, physical units, spatially varying) IS a per-cell posterior std against that same
flat baseline. Treating the covariate-informed estimate as a "virtual observation" of every cell
by itself (footprint = identity, noise = rf_std_m(x)^2) puts it in exactly the same
information-theoretic units as the sensor-network resolution, so the two are directly comparable
and combinable:

    R_static(x)   = 1 - sigma_rf(x)^2 / sigma_flat^2            -- static layers alone
    R_sensor(x)   = 1 - Var_post_sensor(x) / sigma_flat^2        -- wells + dv/v alone (existing calc)
    R_combined(x) = 1 - Var_post_combined(x) / sigma_flat^2      -- both, against the flat baseline
    R_marginal(x) = 1 - Var_post_combined(x) / sigma_rf(x)^2     -- what the NETWORK adds BEYOND
                                                                     what the static layers already give

sigma_flat^2 is the population variance of the well DTW target itself (issue: "what would you
guess with zero covariates and zero nearby wells") -- the same denominator the random forest's
block-CV R^2 is implicitly benchmarked against.

R_combined is computed from a single NONSTATIONARY prior covariance C(x,x') = sigma_rf(x)
sigma_rf(x') rho(|x-x'|) -- the same Matern correlation `resolution()` always used, just scaled
by the covariate-informed std at each point instead of a constant -- so the sensor network's own
resolving power is evaluated against the ACTUAL (spatially varying) prior uncertainty, not a
fictitious flat one.
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
import xarray as xr
from pyproj import Transformer

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROC = Path("data/processed")
ASSETS = Path("docs/twin/assets")
OUT = Path("figures/demo/static_resolution.png")
STEP = 22                      # same coarse grid as make_observability_figure.py
GWL_L_KM = 6.0                 # same Matern correlation length used for GWL elsewhere
NOISE_WELL, NOISE_DVV = 0.02, 0.25   # noise-to-flat-prior-variance ratios, as in make_observability_figure.py


def main():
    try:
        from src.viz.fonts import register_inter
        register_inter()
    except Exception:
        pass
    from src.config.domain import DOMAIN
    from src.models.dvv_sensitivity import pair_kernel, single_station_kernel
    from src.models.observability import (
        matern_correlation,
        normalise_footprint,
        point_footprint,
        resolution,
    )

    hand = rxr.open_rasterio(PROC / "terrain_hand_domain_90m.tif", masked=True).squeeze("band", drop=True)
    wt = xr.open_zarr(PROC / "baseline_wt_domain_90m.zarr")

    sub_hand = hand.isel(y=slice(None, None, STEP), x=slice(None, None, STEP))
    sub_rfstd = wt.rf_std_m.isel(y=slice(None, None, STEP), x=slice(None, None, STEP))
    land = np.isfinite(sub_hand.values).ravel()
    gx, gy = np.meshgrid(sub_hand.x.values / 1000.0, sub_hand.y.values / 1000.0)
    coords = np.column_stack([gx.ravel(), gy.ravel()])
    shp = gx.shape
    x0, y0, x1, y1 = DOMAIN.bounds()
    tf = Transformer.from_crs("EPSG:4326", DOMAIN.crs, always_xy=True)

    def stations_km(lon, lat):
        xm, ym = tf.transform(np.asarray(lon), np.asarray(lat))
        keep = (xm >= x0) & (xm <= x1) & (ym >= y0) & (ym <= y1)
        return np.column_stack([xm[keep] / 1000.0, ym[keep] / 1000.0])

    wells_df = pd.read_parquet(PROC / "nwis_sites_clean.parquet")
    mask = (~wells_df.get("is_sparse_timeseries", pd.Series(False, index=wells_df.index)))
    mask &= (~wells_df.get("is_deep_well", pd.Series(False, index=wells_df.index)))
    mask &= wells_df["median_dtw_m"].notna() & (wells_df["median_dtw_m"] > 0)
    wells_df = wells_df[mask]
    sigma_flat2 = float(np.var(wells_df["median_dtw_m"].values))   # flat-prior (no-covariate) variance

    seis = pd.read_parquet("data/cache/seismic/inventory_UW-CC.parquet")
    well_km = stations_km(wells_df.lon, wells_df.lat)
    seis_km = stations_km(seis.lon, seis.lat)

    G_well = np.vstack([point_footprint(coords, p) for p in well_km])
    dvv_rows = []
    for i in range(len(seis_km)):
        dvv_rows.append(normalise_footprint(single_station_kernel(gx, gy, seis_km[i])))
        for j in range(i + 1, len(seis_km)):
            if np.hypot(*(seis_km[i] - seis_km[j])) <= 40.0:
                dvv_rows.append(normalise_footprint(pair_kernel(gx, gy, seis_km[i], seis_km[j])))
    G_dvv = np.vstack(dvv_rows)
    G_both = np.vstack([G_well, G_dvv])
    nv_both = np.concatenate([np.full(len(G_well), NOISE_WELL), np.full(len(G_dvv), NOISE_DVV)])

    def m(v):
        return np.where(land, v, np.nan).reshape(shp)

    # --- R_static: the covariate-informed estimate treated as a self-observation of every cell ---
    sigma_rf2 = np.nan_to_num(sub_rfstd.values, nan=np.sqrt(sigma_flat2)).ravel() ** 2
    r_static = np.clip(1.0 - sigma_rf2 / sigma_flat2, 0.0, 1.0)

    # --- R_sensor: wells + dv/v alone, against the FLAT prior (dimensionless resolution() is
    # scale-invariant, so this is identical whether the flat prior sigma is 1 or sqrt(sigma_flat2)) ---
    dist = np.sqrt(np.sum((coords[:, None, :] - coords[None, :, :]) ** 2, axis=-1))
    C_flat = sigma_flat2 * matern_correlation(dist, GWL_L_KM, nu=1.5)
    var_flat = np.diag(C_flat).copy()

    _, vpost_sensor_flat = resolution(C_flat, G_both, nv_both * sigma_flat2)
    r_sensor = np.clip(1.0 - vpost_sensor_flat / var_flat, 0.0, 1.0)

    # --- R_combined and R_marginal: a NONSTATIONARY prior C(x,x') = sigma_rf(x) sigma_rf(x') rho(d),
    # so the sensor network is evaluated against the ACTUAL covariate-informed uncertainty, not a
    # fictitious flat one -- this is what makes R_marginal a genuine "beyond the static layers" map.
    sigma_rf = np.sqrt(sigma_rf2)
    C_static = np.outer(sigma_rf, sigma_rf) * matern_correlation(dist, GWL_L_KM, nu=1.5)
    _, vpost_combined = resolution(C_static, G_both, nv_both * sigma_flat2)
    r_combined = np.clip(1.0 - vpost_combined / sigma_flat2, 0.0, 1.0)
    r_marginal = np.clip(1.0 - vpost_combined / np.maximum(sigma_rf2, 1e-6), 0.0, 1.0)

    fig, ax = plt.subplots(2, 2, figsize=(13.5, 12.6), constrained_layout=True)
    panels = [
        (r_static, "Static layers alone\n(HAND/soil/terrain -> RF, vs. flat prior)", "viridis"),
        (r_sensor, "Wells + dv/v alone\n(vs. flat prior)", "viridis"),
        (r_combined, "Static + sensors combined\n(vs. flat prior)", "viridis"),
        (r_marginal, "What the NETWORK adds beyond\nthe static layers (vs. static-informed prior)", "magma"),
    ]
    for a, (field, title, cmap) in zip(ax.ravel(), panels):
        cm = plt.get_cmap(cmap).copy(); cm.set_bad("#eef0f3")
        im = a.imshow(m(field), cmap=cm, vmin=0, vmax=1)
        a.set_title(title, fontsize=13, fontweight="bold")
        fig.colorbar(im, ax=a, shrink=0.75, label="resolution R(x)")
        a.set_xticks([]); a.set_yticks([])

    fig.suptitle("Where spatial resolution comes from: static layers vs. the sensor network vs. both\n"
                 "(GWL / water table; flat-prior variance = %.0f m² from the well population)" % sigma_flat2,
                 fontsize=15, fontweight="bold")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=120, bbox_inches="tight", facecolor="white")
    shutil.copy(OUT, ASSETS / OUT.name)
    print(f"wrote {OUT}  (mean R_static={np.nanmean(r_static):.2f}, "
          f"mean R_sensor={np.nanmean(r_sensor):.2f}, mean R_combined={np.nanmean(r_combined):.2f}, "
          f"mean R_marginal={np.nanmean(r_marginal):.2f})")


if __name__ == "__main__":
    main()
