r"""Estimate the spatial prior from **out-of-fold residuals**, profiled over the smoothness :math:`\nu`.

This is the experiment that is supposed to replace the provisional
:data:`src.models.observability.PRIOR_HYPERPARAMETERS`. It exists because the twin currently asserts
:math:`(\sigma, L, \nu)` values that were never estimated, and because the two obvious shortcuts are
both wrong:

**Shortcut 1 — fit a variogram to the raw field.** Fitting a variogram to the domain-wide water-table
or soil-moisture *map* estimates the covariance of the deterministic landscape, not of the model's
error. Absolute DTW is :math:`D = z_s - h_{wt}`, so its empirical variogram is dominated by
topography; a histogram of it over Puget Sound is strongly skewed even where the *conditional* error
is close to Gaussian. The prior the assimilation needs is the covariance of :math:`\delta h` in
:math:`h_{wt} = h_\text{baseline} + \delta h`. So the input here is a table of **residuals from a
spatially held-out baseline**, and nothing else.

**Shortcut 2 — sweep :math:`\nu` with :math:`\sigma` and :math:`L` frozen.** :math:`\nu` trades off
directly against range and variance, so comparing smoothness values at fixed
:math:`(\sigma, L)` compares two arbitrary points, not two models. Every candidate :math:`\nu` here
gets its own re-estimated :math:`(\sigma, L, \tau^2)`.

## What is estimated, and what is not

For residuals :math:`y` at locations :math:`s`, the model is

.. math::  y = \mathbf{1}\beta + \varepsilon, \qquad
           \mathrm{Cov}(\varepsilon) = \Sigma = \sigma^2 R_\nu(\|s-s'\|; L) + \tau^2 I ,

with :math:`R_\nu` the Matérn correlation in this repo's :math:`\sqrt{2\nu}` convention
(:func:`src.models.observability.matern_correlation`) and :math:`\tau^2` a nugget absorbing
measurement error and sub-grid variability. Writing :math:`\Sigma = s^2 K`,
:math:`K = (1-\alpha)R_\nu + \alpha I`, the overall scale :math:`s^2` profiles out of the REML
objective in closed form, leaving a well-behaved two-dimensional search over
:math:`(L, \alpha)` at each fixed :math:`\nu`.

**REML, not ML**, because ML is biased low for the variance when a mean is estimated alongside it,
and the bias is worst exactly in the small-:math:`n`, strongly-correlated regime a regional well
network sits in.

What this cannot do is escape @zhang2004inconsistent: under fixed-domain asymptotics :math:`\sigma^2`
and :math:`L` are not separately consistently estimable, so the fitted pair should be read as a point
on a ridge whose *microergodic* combination
:math:`\sigma^2\kappa^{2\nu}` (:func:`src.models.observability.microergodic_parameter`) is the part
the data actually determine. The reported profile objective makes the ridge visible; a bare point
estimate hides it.

## What is reported

A **profile** over :math:`\nu` — the REML objective at each candidate, with its own refitted
parameters — plus spatial-holdout predictive scores, so a smoothness that wins the likelihood but
loses the holdout is visible rather than averaged away. The holdout metrics are the ones that decide:
predictive log score, CRPS, RMSE, 90% interval coverage, and the standardized-residual mean/sd
(which should be 0/1 if the fitted :math:`\sigma` is honest).

Folds are **spatial blocks**, never random points: nearby residuals are correlated by construction,
so a random split leaks the very structure being estimated and would return an optimistically short
range.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import minimize
from scipy.stats import norm

from src.models.observability import (
    RANGE_CONVENTION,
    matern_correlation,
    microergodic_parameter,
)

_JITTER = 1e-10


# --- the likelihood ---------------------------------------------------------------------------

def _corr_matrix(coords_km: NDArray[np.float64], length_km: float, nu: float,
                 nugget_frac: float) -> NDArray[np.float64]:
    """:math:`K = (1-\\alpha)R_\\nu + \\alpha I` — the unit-scale correlation-plus-nugget matrix."""
    d = np.sqrt(np.sum((coords_km[:, None, :] - coords_km[None, :, :]) ** 2, axis=-1))
    R = matern_correlation(d, length_km, nu)
    n = coords_km.shape[0]
    return (1.0 - nugget_frac) * R + (nugget_frac + _JITTER) * np.eye(n)


def reml_objective(coords_km: NDArray[np.float64], y: NDArray[np.float64], length_km: float,
                   nu: float, nugget_frac: float) -> tuple[float, float, float]:
    r"""Negative REML log-likelihood with the scale profiled out, plus :math:`(\hat s^2, \hat\beta)`.

    With a constant mean :math:`X = \mathbf{1}` and :math:`\Sigma = s^2 K`,

    .. math::
        \hat\beta = (X^\top K^{-1} X)^{-1} X^\top K^{-1} y, \qquad
        \hat s^2 = \frac{(y-X\hat\beta)^\top K^{-1} (y-X\hat\beta)}{n-p},

    and the profiled negative REML objective is

    .. math::
        -2\ell_R = (n-p)\big[\ln \hat s^2 + 1 + \ln 2\pi\big]
                   + \ln|K| + \ln|X^\top K^{-1} X| .

    Returns ``(neg2_reml, s2_hat, beta_hat)``. Numerically non-finite parameter combinations return
    ``inf`` so the optimiser walks away from them rather than crashing.
    """
    n = coords_km.shape[0]
    p = 1
    try:
        K = _corr_matrix(coords_km, length_km, nu, nugget_frac)
        cf = np.linalg.cholesky(K)
    except (np.linalg.LinAlgError, ValueError):
        return np.inf, np.nan, np.nan
    logdet_K = 2.0 * np.sum(np.log(np.diag(cf)))
    x = np.ones(n)
    Kinv_x = np.linalg.solve(K, x)
    xtkx = float(x @ Kinv_x)
    beta = float(x @ np.linalg.solve(K, y)) / xtkx
    r = y - beta
    s2 = float(r @ np.linalg.solve(K, r)) / (n - p)
    if not np.isfinite(s2) or s2 <= 0:
        return np.inf, np.nan, np.nan
    neg2 = (n - p) * (np.log(s2) + 1.0 + np.log(2.0 * np.pi)) + logdet_K + np.log(xtkx)
    return float(neg2), s2, beta


@dataclass
class MaternFit:
    """One :math:`\\nu` of the profile: the refitted parameters and the objective they achieved."""

    nu: float
    sigma: float                 # sqrt((1 - nugget_frac) * s2) -- the STRUCTURED std
    length_km: float
    nugget: float                # nugget_frac * s2 -- a VARIANCE, in the state's squared units
    nugget_fraction: float
    mean: float
    neg2_reml: float
    microergodic: float
    n: int
    converged: bool
    range_convention: str = RANGE_CONVENTION


def fit_matern_at_fixed_nu(coords_km: ArrayLike, residuals: ArrayLike, nu: float,
                           length_bounds_km: tuple[float, float] = (0.5, 200.0),
                           nugget_bounds: tuple[float, float] = (1e-4, 0.95),
                           n_starts: int = 5) -> MaternFit:
    r"""Re-estimate :math:`(\sigma, L, \tau^2)` by REML at a **fixed** ``nu``.

    Optimises :math:`(\log L, \mathrm{logit}\,\alpha)` — unconstrained coordinates, so the optimiser
    cannot wander onto a boundary and report a spurious convergence — from ``n_starts``
    log-spaced initial ranges, keeping the best. Multi-start matters because the REML surface in
    :math:`(L, \alpha)` is routinely flat-ridged and occasionally bimodal (short range + big nugget
    versus long range + small nugget describe similar data).
    """
    c = np.asarray(coords_km, dtype="float64")
    y = np.asarray(residuals, dtype="float64").ravel()
    if c.shape[0] != y.size:
        raise ValueError(f"coords ({c.shape[0]}) and residuals ({y.size}) must match")
    if y.size < 10:
        raise ValueError(f"need at least 10 residuals to fit a covariance, got {y.size}")

    lo_L, hi_L = length_bounds_km
    lo_a, hi_a = nugget_bounds

    def unpack(theta):
        L = float(np.clip(np.exp(theta[0]), lo_L, hi_L))
        a = float(np.clip(0.5 * (1.0 + np.tanh(0.5 * np.clip(theta[1], -50.0, 50.0))), lo_a, hi_a))
        return L, a

    def obj(theta):
        L, a = unpack(theta)
        return reml_objective(c, y, L, nu, a)[0]

    best, best_val = None, np.inf
    for L0 in np.geomspace(lo_L * 2.0, hi_L / 2.0, n_starts):
        for a0 in (0.1, 0.4):
            x0 = np.array([np.log(L0), np.log(a0 / (1.0 - a0))])
            res = minimize(obj, x0, method="Nelder-Mead",
                           options=dict(maxiter=2000, xatol=1e-4, fatol=1e-6))
            if np.isfinite(res.fun) and res.fun < best_val:
                best, best_val = res, float(res.fun)
    if best is None:
        raise RuntimeError(f"REML failed to converge at nu={nu}")

    L, a = unpack(best.x)
    neg2, s2, beta = reml_objective(c, y, L, nu, a)
    sigma = float(np.sqrt((1.0 - a) * s2))
    return MaternFit(
        nu=float(nu), sigma=sigma, length_km=float(L), nugget=float(a * s2),
        nugget_fraction=float(a), mean=float(beta), neg2_reml=float(neg2),
        microergodic=microergodic_parameter(sigma, L, nu), n=int(y.size),
        converged=bool(best.success),
    )


# --- spatial-block holdout ----------------------------------------------------------------------

def spatial_blocks(coords_km: ArrayLike, block_km: float) -> NDArray[np.int64]:
    """Assign each point to a square spatial block of side ``block_km`` (a deterministic CV fold id).

    Blocks, not random points: residuals within a correlation length of each other are not
    independent, so a random split trains on a test point's own neighbourhood and rewards a
    too-short range. Block side should be at least the largest plausible range being tested.
    """
    c = np.asarray(coords_km, dtype="float64")
    ix = np.floor((c[:, 0] - c[:, 0].min()) / block_km).astype(np.int64)
    iy = np.floor((c[:, 1] - c[:, 1].min()) / block_km).astype(np.int64)
    key = ix * (iy.max() + 1) + iy
    _, fold = np.unique(key, return_inverse=True)
    return fold.astype(np.int64)


def _crps_gaussian(y: NDArray, mu: NDArray, sd: NDArray) -> NDArray:
    r"""Closed-form CRPS of a Gaussian forecast: :math:`\sigma[z(2\Phi(z)-1)+2\phi(z)-\pi^{-1/2}]`."""
    sd = np.clip(sd, 1e-12, None)
    z = (y - mu) / sd
    return sd * (z * (2.0 * norm.cdf(z) - 1.0) + 2.0 * norm.pdf(z) - 1.0 / np.sqrt(np.pi))


def spatial_holdout_scores(coords_km: ArrayLike, residuals: ArrayLike, fit: MaternFit,
                           block_km: float, min_train: int = 10) -> dict[str, Any]:
    r"""Leave-one-block-out predictive scores for a fitted covariance.

    For each block, the model is *conditioned* on the other blocks (simple kriging with the fitted
    :math:`(\sigma, L, \nu, \tau^2)` and a GLS mean from the training folds) and scored on the held
    out block. The parameters are **not** refitted per fold: this scores the covariance model that
    the twin would actually deploy, which is the question being asked.

    Returns predictive log score (mean per point, higher is better), CRPS (lower is better), RMSE,
    empirical 90% and 50% interval coverage, and the mean/sd of the standardized residuals
    :math:`(y-\hat\mu)/\hat\sigma_\text{pred}` — the direct test of whether the fitted uncertainty is
    honest, which should read 0 and 1.
    """
    c = np.asarray(coords_km, dtype="float64")
    y = np.asarray(residuals, dtype="float64").ravel()
    fold = spatial_blocks(c, block_km)
    s2_struct, tau2 = fit.sigma ** 2, fit.nugget

    mu_all, sd_all, y_all = [], [], []
    n_folds_used = 0
    for f in np.unique(fold):
        te = fold == f
        tr = ~te
        if tr.sum() < min_train or te.sum() == 0:
            continue
        n_folds_used += 1
        d_tr = np.sqrt(np.sum((c[tr][:, None, :] - c[tr][None, :, :]) ** 2, axis=-1))
        d_te = np.sqrt(np.sum((c[te][:, None, :] - c[tr][None, :, :]) ** 2, axis=-1))
        Ktr = s2_struct * matern_correlation(d_tr, fit.length_km, fit.nu) \
            + (tau2 + _JITTER) * np.eye(int(tr.sum()))
        Kte = s2_struct * matern_correlation(d_te, fit.length_km, fit.nu)

        ones = np.ones(int(tr.sum()))
        Kinv_1 = np.linalg.solve(Ktr, ones)
        beta = float(ones @ np.linalg.solve(Ktr, y[tr])) / float(ones @ Kinv_1)
        r_tr = y[tr] - beta

        w = np.linalg.solve(Ktr, r_tr)
        mu = beta + Kte @ w
        # predictive variance INCLUDES the nugget: a new observation carries measurement error too
        var = s2_struct + tau2 - np.einsum("ij,ji->i", Kte, np.linalg.solve(Ktr, Kte.T))
        mu_all.append(mu)
        sd_all.append(np.sqrt(np.clip(var, 1e-12, None)))
        y_all.append(y[te])

    if not y_all:
        return {"n_folds": 0, "note": "no block had enough training points for a holdout score"}

    mu = np.concatenate(mu_all)
    sd = np.concatenate(sd_all)
    yy = np.concatenate(y_all)
    z = (yy - mu) / sd
    return {
        "n_folds": int(n_folds_used),
        "n_scored": int(yy.size),
        "block_km": float(block_km),
        "log_score": float(np.mean(norm.logpdf(yy, mu, sd))),
        "crps": float(np.mean(_crps_gaussian(yy, mu, sd))),
        "rmse": float(np.sqrt(np.mean((yy - mu) ** 2))),
        "coverage_90": float(np.mean(np.abs(z) <= norm.ppf(0.95))),
        "coverage_50": float(np.mean(np.abs(z) <= norm.ppf(0.75))),
        "standardized_residual_mean": float(np.mean(z)),
        "standardized_residual_sd": float(np.std(z, ddof=1)),
    }


# --- the profile over nu ------------------------------------------------------------------------

@dataclass
class PriorCalibration:
    """The full, version-controllable record of one state's prior-calibration run."""

    state: str
    transform: str
    support: str
    season: str
    domain: str
    n: int
    range_convention: str
    profile: list[dict[str, Any]] = field(default_factory=list)
    selected_nu: float | None = None
    selection_rule: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def profile_over_nu(coords_km: ArrayLike, residuals: ArrayLike, nu_candidates: tuple[float, ...],
                    state: str, transform: str = "identity", support: str = "unspecified",
                    season: str = "all", domain: str = "all", block_km: float = 25.0,
                    **fit_kwargs) -> PriorCalibration:
    r"""Fit and score the covariance at **each** candidate ``nu``, re-estimating everything else.

    This is the deliverable the documentation should cite instead of quoting a smoothness: a table
    with one row per :math:`\nu`, each carrying its own :math:`(\sigma, L, \tau^2)`, its REML
    objective, its microergodic combination, and its spatial-holdout scores.

    Selection is by **holdout predictive log score**, not by the REML objective, and the rule is
    recorded in the artifact. Where the profile is flat -- which is the expected outcome for
    :math:`\nu` on a network this size -- the honest conclusion is that the data do not distinguish
    the candidates, and that is visible in the table rather than hidden behind the argmax.
    """
    out = PriorCalibration(state=state, transform=transform, support=support, season=season,
                           domain=domain, n=int(np.asarray(residuals).size),
                           range_convention=RANGE_CONVENTION)
    for nu in nu_candidates:
        fit = fit_matern_at_fixed_nu(coords_km, residuals, nu, **fit_kwargs)
        row = asdict(fit)
        row["cv"] = spatial_holdout_scores(coords_km, residuals, fit, block_km)
        out.profile.append(row)

    scored = [r for r in out.profile if r["cv"].get("n_folds", 0) > 0]
    if scored:
        best = max(scored, key=lambda r: r["cv"]["log_score"])
        out.selected_nu = best["nu"]
        out.selection_rule = "max spatial-holdout predictive log score"
        scores = sorted((r["cv"]["log_score"] for r in scored), reverse=True)
        spread = scores[0] - scores[-1]
        gap = scores[0] - scores[1] if len(scores) > 1 else float("inf")
        out.notes.append(
            f"holdout log score spans {spread:.4f} nats across the nu grid; the winner leads the "
            f"runner-up by {gap:.4f} nats")
        if gap < 0.05:
            out.notes.append(
                "the nu grid is NOT distinguished by these data -- report the whole profile, not the "
                "argmax, and do not promote the selected nu from 'working hypothesis' to 'calibrated'")
        reml = sorted(r["neg2_reml"] for r in scored)
        if reml[1] - reml[0] < 2.0 if len(reml) > 1 else False:
            out.notes.append(
                f"the REML objective is also flat in nu (best two within {reml[1]-reml[0]:.2f} of "
                "-2 log-likelihood), which is the expected identifiability limit, not a bug")
        # Zhang (2004): sigma and L are not separately identified. Say so with numbers.
        micro = [r["microergodic"] for r in scored]
        out.notes.append(
            f"sigma ranges {min(r['sigma'] for r in scored):.3g}-{max(r['sigma'] for r in scored):.3g} "
            f"and L ranges {min(r['length_km'] for r in scored):.3g}-"
            f"{max(r['length_km'] for r in scored):.3g} km across the grid, while the microergodic "
            f"combination sigma^2 kappa^(2nu) ranges {min(micro):.3g}-{max(micro):.3g}; per "
            "Zhang (2004) only the latter is consistently estimable under infill asymptotics, and it "
            "is NOT comparable across different nu (its units depend on nu)")
    else:
        out.selection_rule = "not selected: no block had enough training points"
        out.notes.append("increase the sample or shrink block_km before reading anything into this")
    return out


def write_artifact(calibrations: list[PriorCalibration], path: str, provenance: dict[str, Any]
                   ) -> str:
    """Write the machine-readable calibration artifact that the book chapters should consume."""
    doc = {
        "schema": "gaia/spatial-prior-calibration/1",
        "provenance": provenance,
        "range_convention": RANGE_CONVENTION,
        "calibrations": [c.to_dict() for c in calibrations],
    }
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=2, sort_keys=False)
        fh.write("\n")
    return path
