"""Baseline water table over the extended domain, with an HONEST extrapolation mask (D5, #96).

## The problem, measured

The RF baseline is trained on NWIS wells, and wells are drilled where people live — the lowlands.
Over the extended domain that is no longer a detail, it is the dominant fact:

                        wells      domain
    median slope         3.1 deg    13.3 deg
    median HAND         15.2 m      75.2 m
    p95 slope           12.8 deg    38.6 deg
    on steep ground      1%         37%

**The wells sample flat lowland; the domain is now 37% mountain.** A random forest asked to predict
there is *extrapolating into terrain it has never seen*, and it will do so silently and confidently —
tree ensembles do not extrapolate, they return the nearest training leaf, so a Cascade ridge inherits
a lowland water table with a small, reassuring, and entirely meaningless variance.

That matters beyond tidiness: the river/baseflow sink is anchored to this field
(``gw_recess = (R_ref/S_y) / [HAND - d0]``), so a wrong ``d0`` on ridges corrupts the very flux the
domain was extended to calibrate.

## What this does instead

1. **RF on physical covariates only** (terrain + soil + climate). No lat/lon — those let the model
   memorise *where* the wells are rather than *what makes* a water table (the Stage-1 critique).
2. **An applicability domain**, not just a spatial distance. Confidence is the distance in
   *standardised covariate space* to the nearest training well: a cell 200 m from a well but 30 deg
   steeper than anything in the training set is an extrapolation, and a purely spatial mask would
   call it safe.
3. **A physical prior where the wells cannot speak.** The water table is a subdued replica of
   topography (TOPMODEL): ``d_i = d_bar - m*(TWI_i - TWI_bar)`` — deeper under ridges, shallow in
   convergent hollows — bounded below by the regolith. Where confidence is low the RF is blended out
   in favour of this, so the mountains get a *defensible* prior rather than a fabricated lowland one.
4. **Block CV**, because a random split leaks: lowland wells cannot vouch for mountain cells.

The confidence field is written alongside the water table. It is not decoration — downstream users
must be able to see which cells are observed and which are inferred.
"""

from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd
import rioxarray as rxr
import xarray as xr
from pyproj import Transformer

from src.config.domain import DOMAIN
from src.io.zarr_store import write_zarr
from src.models.water_budget import topmodel_watertable

logger = logging.getLogger("baseline_wt_domain")

PROC = "data/processed"
# Physical covariates ONLY. lat/lon are deliberately absent: they let the model memorise well
# locations and produce a map that looks skilful in cross-validation and is useless off-sample.
FEATURES = ["hand_m", "slope_deg", "twi", "log_contrib", "clay_pct", "sand_pct",
            "ksat", "soil_thickness_cm", "theta_sat"]
RF_KWARGS = dict(n_estimators=400, min_samples_leaf=3, random_state=0, n_jobs=-1)
TOPMODEL_M = 4.0        # m of water-table spread per unit TWI; larger than the lowland value because
                        # relief (and therefore the water-table range) is far larger here


def _grid():
    t = DOMAIN.template()
    g = lambda f: rxr.open_rasterio(f"{PROC}/{f}", masked=True).squeeze("band", drop=True)  # noqa: E731
    soil = xr.open_zarr(f"{PROC}/soil_domain_90m.zarr")
    d = {
        "hand_m": g("terrain_hand_domain_90m.tif").values,
        "slope_deg": g("terrain_slope_domain_90m.tif").values,
        "twi": g("terrain_twi_domain_90m.tif").values,
        "log_contrib": np.log10(np.clip(g("terrain_contrib_area_domain_90m.tif").values, 1e2, None)),
    }
    for k in ("clay_pct", "sand_pct", "ksat", "soil_thickness_cm", "theta_sat"):
        d[k] = soil[k].values
    return t, d


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Baseline water table + extrapolation mask (D5).")
    p.add_argument("--out", default=f"{PROC}/baseline_wt_domain_90m.zarr")
    a = p.parse_args()

    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import GroupKFold

    tmpl, grids = _grid()
    rows, cols = tmpl.shape
    x0, y0, x1, y1 = DOMAIN.bounds()

    # --- wells ---------------------------------------------------------------------------------
    w = pd.read_parquet(f"{PROC}/nwis_sites_clean.parquet").dropna(subset=["median_dtw_m"])
    w = w[w.median_dtw_m > 0]
    tf = Transformer.from_crs("EPSG:4326", DOMAIN.crs, always_xy=True)
    wx, wy = tf.transform(w.lon.values, w.lat.values)
    ix = ((wx - x0) / DOMAIN.res_m).astype(int)
    iy = ((y1 - wy) / DOMAIN.res_m).astype(int)
    keep = (ix >= 0) & (ix < cols) & (iy >= 0) & (iy < rows)
    w, ix, iy, wx, wy = w[keep], ix[keep], iy[keep], wx[keep], wy[keep]

    X = np.column_stack([grids[f][iy, ix] for f in FEATURES])
    y = w.median_dtw_m.values
    good = np.isfinite(X).all(axis=1) & np.isfinite(y)
    X, y, wx, wy = X[good], y[good], wx[good], wy[good]
    logger.info("training wells inside the domain: %d", len(y))

    # --- block CV: a random split LEAKS, because lowland wells cannot vouch for mountain cells ----
    block = (np.floor(wx / 10000.0) * 1000 + np.floor(wy / 10000.0)).astype(int)   # 10 km blocks
    gkf = GroupKFold(n_splits=min(5, len(np.unique(block))))
    err = []
    for tr, te in gkf.split(X, y, groups=block):
        m = RandomForestRegressor(**RF_KWARGS).fit(X[tr], y[tr])
        err.append(np.sqrt(np.mean((m.predict(X[te]) - y[te]) ** 2)))
    logger.info("block-CV RMSE: %.2f m (mean of %d folds)", float(np.mean(err)), len(err))

    rf = RandomForestRegressor(**RF_KWARGS).fit(X, y)
    imp = sorted(zip(FEATURES, rf.feature_importances_), key=lambda t: -t[1])
    logger.info("feature importance: %s", ", ".join(f"{k} {v:.2f}" for k, v in imp[:5]))

    # --- predict on the grid --------------------------------------------------------------------
    G = np.column_stack([grids[f].ravel() for f in FEATURES])
    ok = np.isfinite(G).all(axis=1)
    dtw = np.full(rows * cols, np.nan)
    dtw[ok] = rf.predict(G[ok])

    # per-cell sigma from the tree ensemble (a LOWER bound off-sample: trees do not extrapolate,
    # they agree confidently on the nearest training leaf)
    trees = np.stack([t.predict(G[ok]) for t in rf.estimators_])
    sd = np.full(rows * cols, np.nan)
    sd[ok] = trees.std(axis=0)

    # --- APPLICABILITY DOMAIN: distance in standardised COVARIATE space, not in metres -----------
    mu, sig = X.mean(0), X.std(0) + 1e-9
    Xs, Gs = (X - mu) / sig, (G[ok] - mu) / sig
    from scipy.spatial import cKDTree
    dist, _ = cKDTree(Xs).query(Gs, k=1)
    d_ref = np.percentile(cKDTree(Xs).query(Xs, k=2)[0][:, 1], 90)   # typical well-to-well spacing
    conf = np.full(rows * cols, np.nan)
    conf[ok] = np.clip(1.0 / (1.0 + (dist / max(d_ref, 1e-6)) ** 2), 0.0, 1.0)

    # --- physical prior where the wells cannot speak ---------------------------------------------
    # Water table as a subdued replica of topography (TOPMODEL). Anchored to the mean observed DTW
    # so it is consistent with the wells where they exist, and it degrades gracefully where they do not.
    twi = grids["twi"]
    prior = topmodel_watertable(float(np.nanmedian(y)), twi, m_param=TOPMODEL_M).ravel()
    prior = np.clip(prior, 0.5, 120.0)

    c = np.nan_to_num(conf, nan=0.0)
    blended = np.where(np.isfinite(dtw), c * np.nan_to_num(dtw) + (1 - c) * prior, prior)
    blended = np.where(ok | np.isfinite(prior), blended, np.nan)

    ds = xr.Dataset(
        {
            "dtw_m": (("y", "x"), blended.reshape(rows, cols).astype("float32")),
            "dtw_rf_m": (("y", "x"), dtw.reshape(rows, cols).astype("float32")),
            "dtw_prior_m": (("y", "x"), prior.reshape(rows, cols).astype("float32")),
            "rf_std_m": (("y", "x"), sd.reshape(rows, cols).astype("float32")),
            "confidence": (("y", "x"), conf.reshape(rows, cols).astype("float32")),
        },
        coords={"y": tmpl.y, "x": tmpl.x},
    ).rio.write_crs(DOMAIN.crs)
    ds.attrs.update(
        grid=DOMAIN.name, n_wells=int(len(y)), block_cv_rmse_m=float(np.mean(err)),
        note=("dtw_m = confidence-weighted blend of the RF (where wells constrain it) and a TOPMODEL "
              "subdued-replica prior (where they do not). confidence is distance in STANDARDISED "
              "COVARIATE space to the nearest training well -- not a spatial distance. rf_std_m is a "
              "LOWER bound off-sample: tree ensembles do not extrapolate, they agree confidently."),
    )
    write_zarr(ds, a.out)

    lo = np.nanmean(conf < 0.25)
    logger.info("confidence: median %.2f | %.0f%% of the domain is LOW-confidence extrapolation",
                float(np.nanmedian(conf)), 100 * lo)
    logger.info("dtw_m median %.1f m (RF alone %.1f, prior alone %.1f)",
                float(np.nanmedian(blended)), float(np.nanmedian(dtw)), float(np.nanmedian(prior)))


if __name__ == "__main__":
    main()
