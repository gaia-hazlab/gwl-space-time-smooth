"""Time-varying groundwater level at 90 m (gaia-soil-hydromechanics).

Assembles a monthly depth-to-water product on the 90 m grid with the same
*fine-static + coarse-dynamic + downscaling* decomposition used for soil moisture, so the
two state variables carry a consistent, auditable uncertainty budget:

    DTW(x, y, t) = baseline_dtw_90m(x, y)  +  anomaly_90m(x, y, t)

  * **static (fine, 90 m)** — the observation-anchored RF baseline (`baseline_dtw_m.tif`),
    carrying the terrain/texture structure; its RF spread is the static σ.
  * **dynamic (coarse)** — monthly well anomalies (DTW minus each well's window mean) kriged
    onto a coarse grid; ordinary-kriging σ is the dynamic σ. Bilinearly **downscaled** to 90 m.
  * **downscaling** — a representativeness σ for the fine baseline structure the coarse
    anomaly cannot resolve (see :func:`src.models.downscale.representativeness_sigma`).

This is the operational Stage-2/3 signal (kriged observation anomalies); a fitted
climate-response (β-map / TFN, issue #8/#23) can later replace the kriged anomaly in place.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import rioxarray  # noqa: F401
import xarray as xr

from src.models.downscale import (
    ProvStep,
    UncertaintyBudget,
    downscale,
    representativeness_sigma,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TARGET_RES_M = 90.0


def _coarse_grid(bounds, res_m):
    left, bottom, right, top = bounds
    gx = np.arange(left + res_m / 2, right, res_m)
    gy = np.arange(bottom + res_m / 2, top, res_m)
    return gx, gy


def _krige_month(x, y, z, gx, gy):
    """Ordinary kriging of one month's anomalies → (field[ny,nx], sigma[ny,nx]) on the coarse grid."""
    from pykrige.ok import OrdinaryKriging

    # A-priori bound: away from wells kriging must fall back to the climatological prior,
    # never claim MORE uncertainty than knowing nothing → cap σ at the anomaly sample std.
    prior = float(np.nanstd(z)) if np.isfinite(np.nanstd(z)) and np.nanstd(z) > 0 else 1.0
    # Physical bound on the interpolated anomaly: it cannot exceed the observed anomalies by
    # more than ~1 prior σ — clips pykrige's occasional extrapolation blow-ups.
    lo, hi = float(np.nanmin(z)) - prior, float(np.nanmax(z)) + prior
    try:
        ok = OrdinaryKriging(x, y, z, variogram_model="exponential",
                             enable_plotting=False, coordinates_type="euclidean")
        field, var = ok.execute("grid", gx, gy)
        field = np.clip(np.asarray(field), lo, hi)
        sigma = np.clip(np.sqrt(np.maximum(np.asarray(var), 0.0)), 0.0, prior)
        return field, sigma
    except Exception as exc:  # sparse/degenerate month → inverse-distance fallback
        logger.warning("kriging fell back to IDW (%s)", exc)
        XX, YY = np.meshgrid(gx, gy)
        d = np.sqrt((XX[..., None] - x) ** 2 + (YY[..., None] - y) ** 2) + 1e-6
        wgt = 1.0 / d ** 2
        field = (wgt * z).sum(-1) / wgt.sum(-1)
        # σ grows toward the prior where the nearest well is far (IDW has no native variance).
        nearest = np.sqrt(((XX[..., None] - x) ** 2 + (YY[..., None] - y) ** 2).min(-1))
        sigma = prior * (1.0 - np.exp(-nearest / (5.0 * (gx[1] - gx[0]))))
        return field, sigma


def gwl_dynamic_90m(
    monthly_pilot: pd.DataFrame,
    baseline_dtw: xr.DataArray,
    rf_std: xr.DataArray,
    window: tuple[str, str],
    coarse_res_m: float = 2000.0,
    min_wells: int = 8,
    downscaler: str = "bilinear",
):
    """Return (times, DTW_90m[t,y,x], UncertaintyBudget) over the requested window.

    ``monthly_pilot`` needs columns x_5070, y_5070, dtw_m, date (month start). Baseline and
    rf_std are 90 m EPSG:5070 DataArrays. Anomalies are relative to each well's window mean.
    The coarse kriged anomaly is mapped to 90 m via the modular downscaler (``"bilinear"``
    baseline; the fine baseline is passed as a covariate for future data-informed methods).
    """
    df = monthly_pilot.copy()
    df = df[(df.date >= pd.Timestamp(window[0])) & (df.date <= pd.Timestamp(window[1]))]
    well_mean = df.groupby("site_no").dtw_m.transform("mean")
    df["anom"] = df.dtw_m - well_mean

    like = baseline_dtw
    bounds = like.rio.bounds()
    gx, gy = _coarse_grid(bounds, coarse_res_m)
    base = baseline_dtw.values
    valid = np.isfinite(base)

    months = pd.date_range(window[0], window[1], freq="MS")
    times, frames, sig_dyn_frames = [], [], []
    for mo in months:
        g = df[df.date == mo]
        if g.site_no.nunique() < min_wells:
            continue
        field, sigma = _krige_month(g.x_5070.values, g.y_5070.values, g.anom.values, gx, gy)
        coarse = xr.DataArray(field, dims=("y", "x"), coords={"y": gy, "x": gx}) \
            .rio.write_crs("EPSG:5070").rio.set_spatial_dims(x_dim="x", y_dim="y")
        coarse_sig = xr.DataArray(sigma, dims=("y", "x"), coords={"y": gy, "x": gx}) \
            .rio.write_crs("EPSG:5070").rio.set_spatial_dims(x_dim="x", y_dim="y")
        cov = {"baseline": baseline_dtw}  # fine static covariate for smarter downscalers
        anom90 = downscale(coarse.sortby("y"), like, method=downscaler, covariates=cov).values
        sig90 = downscale(coarse_sig.sortby("y"), like, method=downscaler, covariates=cov).values
        dtw = np.where(valid, base + anom90, np.nan)
        times.append(mo)
        frames.append(dtw.astype("float32"))
        sig_dyn_frames.append(sig90.astype("float32"))

    if not frames:
        raise RuntimeError("no month met the min-wells threshold in the window.")

    dtw_90m = np.stack(frames, axis=0)
    sig_dynamic = np.nanmean(np.stack(sig_dyn_frames, 0), axis=0)  # time-mean kriging σ

    budget = UncertaintyBudget()
    budget.add("static_rf_baseline", np.where(valid, rf_std.values, np.nan))
    budget.add("dynamic_kriging", np.where(valid, sig_dynamic, np.nan))
    budget.add("downscaling", representativeness_sigma(like, coarse_res_m, TARGET_RES_M))
    budget.provenance = [
        ProvStep("HAND, slope, TWI, texture", "3DEP + SOLUS100", TARGET_RES_M, TARGET_RES_M, "RF baseline"),
        ProvStep("baseline DTW + RF σ", "observation-anchored RF", TARGET_RES_M, TARGET_RES_M, "fit at 863 wells"),
        ProvStep("monthly well anomalies", "USGS NWIS", 0.0, coarse_res_m, "ordinary kriging"),
        ProvStep("anomaly(t) → 90 m", "statistical downscaling", coarse_res_m, TARGET_RES_M, "bilinear + representativeness σ"),
        ProvStep("DTW(t) = baseline + anomaly", "static + dynamic", TARGET_RES_M, TARGET_RES_M, "combine"),
    ]
    logger.info("GWL dynamic: %d months over %s..%s, %d wells/mo median",
                len(times), window[0], window[1], int(df.groupby("date").site_no.nunique().median()))
    return np.array(times), dtw_90m, budget
