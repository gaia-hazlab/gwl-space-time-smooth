"""Observation anchoring — bias-correct a model field toward point observations (issue #28).

The soil-moisture bucket is model-only; groundwater level, by contrast, is anchored to USGS
wells. This module supplies the analogous **residual anchoring** for any state variable: given
point observations, interpolate the (obs − model) residual onto the grid and add it, so the
product is pulled toward the data where data exist and reverts to the model (with inflated σ)
where it does not — the same idea as the GWL Stage-3 residual kriging.

The interpolation is a Gaussian-distance weighting (a light, robust stand-in for kriging when
the station count is small); the companion σ grows from a small value at a station to the
climatological ``prior_sigma`` far away, so anchoring never claims skill it cannot support.
"""

from __future__ import annotations

import numpy as np


def residual_anchor(grid_x, grid_y, obs_x, obs_y, residuals, length_scale_m, prior_sigma,
                    obs_sigma=0.02):
    """Interpolate point residuals onto a grid → (anchor field, σ field).

    Parameters
    ----------
    grid_x, grid_y : 2-D arrays of target-cell coordinates (same CRS/units as obs).
    obs_x, obs_y, residuals : 1-D station coordinates and their (obs − model) residuals.
    length_scale_m : Gaussian correlation length (support radius) in the coord units.
    prior_sigma : σ far from any station (fall-back / climatological spread).
    obs_sigma : σ at a station.

    Returns (anchor, sigma) as 2-D arrays on the grid. Add ``anchor`` to the model field;
    combine ``sigma`` into the uncertainty budget.
    """
    gx = np.asarray(grid_x, dtype="float64")[..., None]
    gy = np.asarray(grid_y, dtype="float64")[..., None]
    ox = np.asarray(obs_x, dtype="float64")
    oy = np.asarray(obs_y, dtype="float64")
    r = np.asarray(residuals, dtype="float64")

    d2 = (gx - ox) ** 2 + (gy - oy) ** 2                      # (..., n_obs) squared distance
    w = np.exp(-d2 / (2.0 * length_scale_m ** 2))            # Gaussian weights
    wsum = w.sum(axis=-1)
    anchor = np.where(wsum > 1e-9, (w * r).sum(axis=-1) / np.maximum(wsum, 1e-9), 0.0)

    # Support ∈ [0,1]: 1 at a station (w.max→1), →0 far away. σ interpolates obs_sigma↔prior.
    support = np.clip(w.max(axis=-1), 0.0, 1.0)
    sigma = obs_sigma * support + prior_sigma * (1.0 - support)
    # Fade the correction out where there is no support, so the product reverts to the model.
    anchor = anchor * support
    return anchor.astype("float32"), sigma.astype("float32")


def assimilate_points(grid_x, grid_y, obs_x, obs_y, obs_val, obs_sigma,
                      length_scale_m, prior_sigma):
    """Heteroscedastic, precision-weighted assimilation of point anomalies into a grid.

    The uncertainty-aware generalisation of :func:`residual_anchor`: each observation carries its
    **own** 1σ, so a tightly-constrained datum (a USGS well, σ~cm) pulls harder than a noisy one
    (a single-season dv/v estimate, σ from codameter's data covariance). This is what lets a new
    observational source — the dv/v-derived relative water table or soil moisture — be assimilated
    *alongside* the existing wells / SNOTEL rather than replacing them: concatenate every source's
    ``(x, y, value, sigma)`` and pass them together; the precision weighting fuses them correctly.

        w_i(x) = exp(-d²/2L²) / σ_i²          (spatial support × observation precision)
        estimate(x) = Σ w_i vᵢ / Σ w_i
        P(x) = Σ w_i,   P₀ = 1/prior_σ²       (data precision vs prior/model precision)
        field(x) = estimate · P/(P+P₀)        (→ 0, i.e. reverts to the model, where no data)
        σ_post(x) = sqrt(1/(P+P₀))            (shrinks below prior_σ near informative stations)

    ``obs_val`` are anomalies (obs − model, or a relative change) to ADD to the model field.
    ``obs_sigma`` is a scalar or a per-station array. Returns (field, sigma) on the grid.
    """
    gx = np.asarray(grid_x, dtype="float64")[..., None]
    gy = np.asarray(grid_y, dtype="float64")[..., None]
    ox = np.asarray(obs_x, dtype="float64")
    oy = np.asarray(obs_y, dtype="float64")
    v = np.asarray(obs_val, dtype="float64")
    s = np.broadcast_to(np.asarray(obs_sigma, dtype="float64"), v.shape)
    prec = 1.0 / np.maximum(s, 1e-9) ** 2                     # per-observation precision

    d2 = (gx - ox) ** 2 + (gy - oy) ** 2
    w = np.exp(-d2 / (2.0 * length_scale_m ** 2)) * prec      # support × precision
    wsum = w.sum(axis=-1)
    estimate = np.where(wsum > 1e-30, (w * v).sum(axis=-1) / np.maximum(wsum, 1e-30), 0.0)

    p0 = 1.0 / prior_sigma ** 2
    shrink = wsum / (wsum + p0)                               # 0 far away → reverts to model
    field = estimate * shrink
    sigma = np.sqrt(1.0 / (wsum + p0))
    return field.astype("float32"), sigma.astype("float32")


def loso_anchor_skill(obs_x, obs_y, model_val, obs_val, length_scale_m):
    """Leave-one-station-out test of the anchor: does it reduce held-out bias/RMSE?

    ``model_val``/``obs_val`` are per-station time-mean model and observed values. For each held
    station, the residual is predicted from the *other* stations (Gaussian-weighted) and applied;
    returns (raw_bias, raw_rmse, anchored_bias, anchored_rmse) over the held-out stations.
    """
    ox, oy = np.asarray(obs_x, float), np.asarray(obs_y, float)
    m, o = np.asarray(model_val, float), np.asarray(obs_val, float)
    resid = o - m
    n = len(o)
    pred = np.zeros(n)
    for i in range(n):
        d2 = (ox[i] - ox) ** 2 + (oy[i] - oy) ** 2
        w = np.exp(-d2 / (2.0 * length_scale_m ** 2)); w[i] = 0.0
        pred[i] = (w * resid).sum() / max(w.sum(), 1e-9)      # residual from neighbours only
    anch = m + pred
    return (float(np.mean(m - o)), float(np.sqrt(np.mean((m - o) ** 2))),
            float(np.mean(anch - o)), float(np.sqrt(np.mean((anch - o) ** 2))))
