r"""Observability, resolution, and information gain of the sensor networks (linear-Gaussian design).

This answers a question the sensitivity map (:mod:`src.models.dvv_sensitivity`) raises but does not
close: given *where* each instrument is sensitive, **how much does it actually tell us about the state
of the twin — the groundwater level and the soil moisture — and where?**

## The framing

The state is a field :math:`m(x)` (a GWL anomaly, or a soil-moisture anomaly) on the analysis grid,
with a Gaussian prior of variance :math:`\sigma^2` and spatial correlation length :math:`L` — the
model's own error covariance :math:`C`. Each observation is a **linear functional** of that field,

.. math::  d_i = g_i^\top m + \varepsilon_i, \qquad \varepsilon_i \sim \mathcal N(0, \sigma_{d,i}^2),

where :math:`g_i` is the instrument's footprint (a weighting that sums to one, so every sensor observes
a weighted *average* of the state):

- a **well** or a **SNOTEL** site is a point sensor — :math:`g_i` is a narrow blob at the location;
- a **dv/v** station pair or autocorrelation is a *volume* sensor — :math:`g_i` is the coda kernel.

The states are observed by *different* instruments, and that separation is the whole point: the **deep
(low-frequency) dv/v band and the wells constrain GWL**; the **shallow (high-frequency) dv/v band and
SNOTEL constrain soil moisture**. dv/v is the only one of the three that is a *volume* measurement, so
it is the only one that fills the space *between* the point sensors.

## What is computed

For a set of observations with operator matrix :math:`G` (rows :math:`g_i^\top`) and noise
:math:`C_d`, the Gaussian posterior covariance is

.. math::  C_\text{post} = C - C G^\top (G C G^\top + C_d)^{-1} G C .

Everything below is a diagonal of this, computed in **observation space** (an
:math:`n_\text{obs}\times n_\text{obs}` solve, not an :math:`n_\text{cell}` one):

- **resolution** :math:`R(x) = 1 - C_\text{post}(x,x)/C(x,x) \in [0,1]` — the fraction of the prior
  variance the network removes at each cell. 1 = fully observed, 0 = the model is on its own.
- **information gain** :math:`I(x) = \tfrac12 \ln\!\big(C(x,x)/C_\text{post}(x,x)\big)` nats — the
  local Kullback–Leibler gain, additive and unbounded, so a cell pinned by several sensors reads as
  more informed than one grazed by one.
- **marginal gain** of a sensor set *given* another: :math:`R(A\cup B) - R(B)` — where a network adds
  information the others do not already provide. This is the map that says *where dv/v is worth its
  cost*: where it constrains a state the wells or SNOTEL cannot reach.

Resolution is a **ratio**, so it is independent of the absolute prior variance :math:`\sigma^2`; only
the correlation length and the noise-to-prior ratio matter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray


@dataclass(frozen=True)
class GaussianPrior:
    """A stationary Gaussian prior over the state field: variance ``sigma^2``, correlation ``length_km``."""

    sigma: float
    length_km: float

    def cov(self, coords_km: NDArray[np.float64]) -> NDArray[np.float64]:
        """Dense prior covariance ``C`` for cell centres ``coords_km`` (``(n, 2)`` array, km)."""
        c = np.asarray(coords_km, dtype="float64")
        d2 = np.sum((c[:, None, :] - c[None, :, :]) ** 2, axis=-1)
        return (self.sigma ** 2) * np.exp(-d2 / (2.0 * self.length_km ** 2))

    def cross(self, coords_km: NDArray[np.float64], pts_km: NDArray[np.float64]) -> NDArray[np.float64]:
        """Prior cross-covariance between every cell and every point in ``pts_km`` (``(n, m)``)."""
        c = np.asarray(coords_km, dtype="float64")
        p = np.asarray(pts_km, dtype="float64")
        d2 = np.sum((c[:, None, :] - p[None, :, :]) ** 2, axis=-1)
        return (self.sigma ** 2) * np.exp(-d2 / (2.0 * self.length_km ** 2))


def point_footprint(coords_km: NDArray[np.float64], loc_km: ArrayLike,
                    width_km: float = 0.5) -> NDArray[np.float64]:
    """Footprint of a point sensor: a narrow normalised blob at ``loc_km``.

    A finite width (rather than a hard one-hot) keeps the operator stable on a coarse grid and encodes
    the small but non-zero support of a real point measurement. Sums to 1.
    """
    c = np.asarray(coords_km, dtype="float64")
    loc = np.asarray(loc_km, dtype="float64")
    g = np.exp(-np.sum((c - loc) ** 2, axis=-1) / (2.0 * width_km ** 2))
    tot = g.sum()
    return g / tot if tot > 0 else g


def normalise_footprint(g: ArrayLike) -> NDArray[np.float64]:
    """Normalise a footprint (e.g. a coda kernel sampled on the grid) to sum to 1."""
    g = np.asarray(g, dtype="float64").ravel()
    tot = np.nansum(g)
    return np.nan_to_num(g / tot) if tot > 0 else np.nan_to_num(g)


def resolution(prior_cov: NDArray[np.float64], G: NDArray[np.float64],
               noise_var: ArrayLike) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    r"""Per-cell resolution and posterior variance for observations ``G`` with noise ``noise_var``.

    ``G`` is ``(n_obs, n_cell)`` (each row a footprint summing to 1); ``noise_var`` is a scalar or an
    ``(n_obs,)`` array of :math:`\sigma_{d,i}^2` in the same units as the prior variance. Returns
    ``(resolution, var_post)``, both length ``n_cell``. Empty ``G`` returns zero resolution.
    """
    C = np.asarray(prior_cov, dtype="float64")
    var_prior = np.diag(C).copy()
    G = np.atleast_2d(np.asarray(G, dtype="float64"))
    if G.size == 0 or G.shape[0] == 0:
        return np.zeros_like(var_prior), var_prior.copy()

    nv = np.broadcast_to(np.asarray(noise_var, dtype="float64"), (G.shape[0],))
    CG = C @ G.T                                     # (n_cell, n_obs): cell <-> obs cross-covariance
    M = G @ CG + np.diag(nv)                          # (n_obs, n_obs): obs-space covariance
    X = np.linalg.solve(M, CG.T)                      # (n_obs, n_cell)
    reduction = np.einsum("ij,ji->i", CG, X)          # diag(CG M^-1 CG^T)
    reduction = np.clip(reduction, 0.0, var_prior)    # numerical guard
    var_post = var_prior - reduction
    res = np.where(var_prior > 0, reduction / var_prior, 0.0)
    return res, var_post


def information_gain(var_prior: ArrayLike, var_post: ArrayLike,
                     clip_nats: float = 4.0) -> NDArray[np.float64]:
    r"""Per-cell information gain :math:`\tfrac12\ln(\text{var\_prior}/\text{var\_post})`, in nats.

    Additive across independent constraints and unbounded, so it distinguishes a cell pinned by several
    sensors from one grazed by one. Clipped for display (a fully resolved cell is +inf).
    """
    vp = np.asarray(var_prior, dtype="float64")
    vq = np.clip(np.asarray(var_post, dtype="float64"), 1e-12, None)
    return np.clip(0.5 * np.log(np.clip(vp, 1e-12, None) / vq), 0.0, clip_nats)


def marginal_resolution(prior_cov: NDArray[np.float64], G_added: NDArray[np.float64],
                        G_base: NDArray[np.float64], noise_added: ArrayLike,
                        noise_base: ArrayLike) -> NDArray[np.float64]:
    """Extra resolution that ``G_added`` provides **beyond** ``G_base``: ``R(base+added) - R(base)``.

    This is the "is it worth its cost" map — where the added network constrains the state that the base
    network cannot already reach. Non-negative up to numerical noise (more data never loses resolution).
    """
    base = np.atleast_2d(np.asarray(G_base, dtype="float64"))
    add = np.atleast_2d(np.asarray(G_added, dtype="float64"))
    res_base, _ = resolution(prior_cov, base, noise_base)
    both = np.vstack([base, add]) if base.shape[0] else add
    nv = np.concatenate([np.broadcast_to(np.asarray(noise_base, float), (base.shape[0],)),
                         np.broadcast_to(np.asarray(noise_added, float), (add.shape[0],))])
    res_both, _ = resolution(prior_cov, both, nv)
    return np.clip(res_both - res_base, 0.0, 1.0)
