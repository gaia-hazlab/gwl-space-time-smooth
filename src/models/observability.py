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


_SQRT3 = 3.0 ** 0.5
_SQRT5 = 5.0 ** 0.5


def matern_correlation(dist_km: ArrayLike, length_km: float, nu: float = 1.5) -> NDArray[np.float64]:
    r"""Matern correlation at distance ``dist_km`` (smoothness ``nu``, closed forms for 0.5/1.5/2.5).

    ``nu=0.5`` is the (rough, once-differentiable-in-expectation) exponential/OU form
    :math:`\exp(-r)`; ``nu=2.5`` is close to the :math:`C^\infty` squared-exponential without actually
    being infinitely smooth. Issue #163: the squared-exponential ``GaussianPrior`` used everywhere
    before this was the :math:`\nu\to\infty` limit, which imposes an implausibly smooth field on a
    terrain-driven state (real hydraulic head/soil moisture fields have kinks at drainage divides and
    lithologic contacts); ``nu=1.5`` (the default here) is the standard practical compromise —
    once-differentiable, not analytic.
    """
    r = _SQRT3 if nu == 1.5 else (_SQRT5 if nu == 2.5 else 1.0)
    d = np.asarray(dist_km, dtype="float64") / max(length_km, 1e-12)
    x = r * d
    if nu == 0.5:
        return np.exp(-x)
    if nu == 1.5:
        return (1.0 + x) * np.exp(-x)
    if nu == 2.5:
        return (1.0 + x + x ** 2 / 3.0) * np.exp(-x)
    raise ValueError(f"nu must be one of 0.5, 1.5, 2.5 (closed-form only), got {nu!r}")


@dataclass(frozen=True)
class GaussianPrior:
    """A stationary prior over the state field: variance ``sigma^2``, Matern correlation ``length_km``.

    ``nu`` is the Matern smoothness (0.5 / 1.5 / 2.5; default 1.5 -- see :func:`matern_correlation`).
    ``region_id``, if given (one label per cell, e.g. a drainage-basin or HAND-derived hydrologic-unit
    ID), makes the prior **terrain-aware**: correlation is forced to zero between cells in different
    regions, regardless of their Euclidean distance. Without it, a stationary isotropic kernel lets a
    ridge cell and a valley cell 90 m apart correlate exactly as strongly as two valley cells 90 m
    apart, leaking constraint across a divide the two sides of which do not hydraulically communicate
    (issue #163) -- ``region_id`` is the cheap, exact fix for that leakage; it does not by itself solve
    the separate scalability problem of a dense ``(n, n)`` ``C`` at full 90 m domain scale, which the
    twin currently avoids by solving on a coarsened assimilation grid (`notebooks/make_twin_gif.py`) --
    a sparse GMRF/SPDE precision representation remains future work for the full-resolution solve.
    """

    sigma: float
    length_km: float
    nu: float = 1.5
    region_id: NDArray[np.int64] | None = None

    def _mask(self, region_a: NDArray | None, region_b: NDArray | None) -> NDArray[np.float64] | float:
        if region_a is None or region_b is None:
            return 1.0
        return (np.asarray(region_a)[:, None] == np.asarray(region_b)[None, :]).astype("float64")

    def cov(self, coords_km: NDArray[np.float64]) -> NDArray[np.float64]:
        """Dense prior covariance ``C`` for cell centres ``coords_km`` (``(n, 2)`` array, km)."""
        c = np.asarray(coords_km, dtype="float64")
        d = np.sqrt(np.sum((c[:, None, :] - c[None, :, :]) ** 2, axis=-1))
        corr = matern_correlation(d, self.length_km, self.nu) * self._mask(self.region_id, self.region_id)
        return (self.sigma ** 2) * corr

    def cross(self, coords_km: NDArray[np.float64], pts_km: NDArray[np.float64],
             region_id_pts: NDArray[np.int64] | None = None) -> NDArray[np.float64]:
        """Prior cross-covariance between every cell and every point in ``pts_km`` (``(n, m)``).

        ``region_id_pts`` (one label per point in ``pts_km``) applies the same terrain-aware masking as
        :attr:`region_id`; omit it (or leave ``self.region_id`` unset) to skip masking here.
        """
        c = np.asarray(coords_km, dtype="float64")
        p = np.asarray(pts_km, dtype="float64")
        d = np.sqrt(np.sum((c[:, None, :] - p[None, :, :]) ** 2, axis=-1))
        corr = matern_correlation(d, self.length_km, self.nu) * self._mask(self.region_id, region_id_pts)
        return (self.sigma ** 2) * corr


# --- the temporal axis --------------------------------------------------------------------------
# Spatial resolution is only half the design. A state that changes fast is observed well only by a
# stream that samples fast: soil moisture responds to a storm within DAYS, so a satellite that revisits
# once a week aliases the very events dv/v or an hourly probe resolves. The two states have very
# different temporal correlation times, which is why the same sensor is worth different amounts for each.
TEMPORAL_TAU_DAYS = {
    "soil_moisture": 5.0,     # a storm wets, then drains, over days
    "gwl": 120.0,             # the water table integrates months (the snowmelt-clocked seasonal cycle)
}


def ou_correlation(lag_days: ArrayLike, tau_days: float) -> NDArray[np.float64]:
    r"""Ornstein-Uhlenbeck correlation :math:`\rho(\Delta t)=\exp(-\Delta t/\tau)` at lag ``lag_days``.

    The state's temporal covariance is modelled as a stationary OU process with correlation time
    :math:`\tau`: :math:`\mathrm{corr}(m(t), m(t-\Delta t)) = \exp(-\Delta t/\tau)`. This is the single
    building block both :func:`temporal_resolution` and a lagged datum's effective operator/noise
    (:func:`lagged_observation`) are derived from -- there is no independent factor of 2 anywhere; that
    would be borrowed from the *spatial* squared-exponential kernel (:class:`GaussianPrior`, whose
    :math:`\exp(-d^2/2L^2)` form is for a smooth Gaussian random field, not a first-order Markov process
    in time) and does not belong here.
    """
    dt = np.asarray(lag_days, dtype="float64")
    return np.exp(-np.clip(dt, 0.0, None) / max(tau_days, 1e-6))


def temporal_resolution(revisit_days: ArrayLike, tau_days: float) -> NDArray[np.float64]:
    r"""Fraction of a state's temporal variability a stream with ``revisit_days`` sampling resolves.

    A perfect (zero-noise) sample taken :math:`\Delta t` in the past explains a fraction
    :math:`\rho(\Delta t)^2=\exp(-2\Delta t/\tau)` of the current state's variance under the OU model
    (:func:`ou_correlation`) -- the same identity :func:`resolution` uses elsewhere
    (:math:`R = 1 - \mathrm{var\_post}/\mathrm{var\_prior}`, and for one perfectly-measured correlated
    datum :math:`\mathrm{var\_post}/\mathrm{var\_prior} = 1-\rho^2`), evaluated here in closed form for a
    single lag rather than via the general observation-space solve. ~1 when the stream samples far
    faster than the state changes, ~0 when it aliases (revisit :math:`\gg \tau`). Continuous streams
    (``revisit_days`` :math:`\to 0`) give 1.

    This is the temporal analogue of the spatial resolution, and the two multiply: a stream's
    observability of a *dynamic* field is ``spatial_resolution * temporal_resolution``. It is why a
    weekly satellite with domain-wide coverage still misses the soil-moisture *event* a continuous
    seismic array or an hourly probe catches — great space, poor time.
    """
    return ou_correlation(revisit_days, tau_days) ** 2


def lagged_observation(g: ArrayLike, lag_days: ArrayLike, tau_days: float, state_var: ArrayLike,
                       obs_noise_var: ArrayLike) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    r"""Effective footprint and noise variance for a datum taken ``lag_days`` before the analysis time.

    A raw observation is :math:`y = m(t-\Delta t) + \varepsilon`. Under the OU model, the state at the
    analysis time relates to its past value as :math:`m(t-\Delta t) = \rho\, m(t) + w`, with
    :math:`\rho=\exp(-\Delta t/\tau)` (:func:`ou_correlation`) and independent drift noise
    :math:`w\sim\mathcal N(0,\ \sigma_m^2(1-\rho^2))` (``state_var`` :math:`=\sigma_m^2`, the field's own
    variance at that location). So :math:`y = \rho\, g^\top m(t) + \eta`, :math:`\eta\sim\mathcal
    N(0,\ \sigma_m^2(1-\rho^2)+\sigma_\varepsilon^2)`:

    - the **operator gain shrinks** to :math:`\rho\, g` (a stale datum is weak evidence about the
      *current* state, not full-strength evidence with merely larger noise);
    - the **effective noise gains a drift term** :math:`\sigma_m^2(1-\rho^2)$ on top of the instrument
      noise (uncertainty accrued while the state evolved, unobserved, over :math:`\Delta t`).

    This replaces the earlier "inflate :math:`\sigma_\varepsilon^2` by :math:`1/\exp(-\Delta t/2\tau)`,
    leave :math:`g` at unit gain" treatment, which had no state-noise term and so silently overweighted
    stale data through the untouched gain. Returns ``(g_eff, noise_var_eff)``, ready to feed a row (or
    rows) of ``G``/``noise_var`` into :func:`resolution` or :func:`blue_update`.
    """
    rho = ou_correlation(lag_days, tau_days)
    g = np.asarray(g, dtype="float64")
    g_eff = rho * g if g.ndim == 1 else rho[:, None] * g
    noise_eff = np.asarray(state_var, dtype="float64") * (1.0 - rho ** 2) + np.asarray(
        obs_noise_var, dtype="float64")
    return g_eff, noise_eff


@dataclass(frozen=True)
class ObsStream:
    """One observation stream, characterised on BOTH axes of the design and by what it truly is.

    ``kind`` is the spatial geometry (point / volume / satellite / channel). ``is_measurement`` records
    whether the stream *measures* the state or *estimates* it through a retrieval model — a satellite
    soil-moisture product is the latter, and its noise is a model error, not an instrument error.
    """

    name: str
    states: tuple[str, ...]          # which model states it informs (from TEMPORAL_TAU_DAYS keys)
    support_km: float                # spatial footprint (point ~ 0.1; SMAP 9; NISAR 0.2; dv/v ~ path)
    revisit_days: float              # sampling interval (0 = continuous)
    kind: str                        # "point" | "volume" | "satellite" | "channel"
    noise: float                     # observation-error VARIANCE (sigma_d^2), in units of the prior variance
    is_measurement: bool             # True = measures the state; False = a retrieval / model estimate


# The observing system, on both axes. Revisit is what the user's point turns on: soil moisture changes
# in days, so a weekly satellite ALIASES it however fine its pixels; the continuous seismic array and
# the sub-daily probes are the streams that resolve the events.
STREAMS: tuple[ObsStream, ...] = (
    ObsStream("NWIS wells", ("gwl",), 0.1, 30.0, "point", 0.02, True),
    ObsStream("SNOTEL / SCAN θ", ("soil_moisture",), 0.1, 0.04, "point", 0.03, True),   # hourly
    ObsStream("USCRN θ", ("soil_moisture",), 0.1, 0.04, "point", 0.03, True),           # hourly
    ObsStream("Seismic dv/v", ("soil_moisture", "gwl"), 8.0, 0.04, "volume", 0.12, True),  # ~continuous
    ObsStream("SMAP (retrieval)", ("soil_moisture",), 9.0, 2.5, "satellite", 0.10, False),
    ObsStream("NISAR (retrieval, future)", ("soil_moisture",), 0.2, 12.0, "satellite", 0.06, False),
    ObsStream("Sentinel surface water", ("gwl",), 0.1, 6.0, "channel", 0.04, False),    # cloud-limited
    ObsStream("USGS gauges", ("gwl",), 5.0, 0.01, "flux", 0.05, True),                  # 15-min, basin
)


def effective_observability(spatial_res: ArrayLike, revisit_days: float, state: str) -> NDArray[np.float64]:
    """Observability of a **dynamic** state: spatial resolution discounted by temporal resolution.

    ``spatial_res * temporal_resolution(revisit, tau_state)``. A stream with perfect coverage but a
    revisit slower than the state's correlation time is discounted toward zero — the space-time
    tradeoff, per cell.
    """
    return np.asarray(spatial_res, dtype="float64") * temporal_resolution(
        revisit_days, TEMPORAL_TAU_DAYS[state])


def point_footprint(coords_km: NDArray[np.float64], loc_km: ArrayLike,
                    width_km: float = 0.5) -> NDArray[np.float64]:
    """Footprint of a point sensor: a narrow normalised blob at ``loc_km``.

    A finite width (rather than a hard one-hot) keeps the operator stable on a coarse grid and encodes
    the small but non-zero support of a real point measurement. **Always sums to 1**: if the Gaussian
    underflows to zero everywhere (a width far below the cell size, or a location outside the grid),
    the unit mass is placed on the nearest cell rather than returning an all-zero row, so a point
    sensor is never silently dropped from the design.
    """
    c = np.asarray(coords_km, dtype="float64")
    loc = np.asarray(loc_km, dtype="float64")
    d2 = np.sum((c - loc) ** 2, axis=-1)
    g = np.exp(-d2 / (2.0 * width_km ** 2))
    tot = g.sum()
    if tot > 0:
        return g / tot
    out = np.zeros(c.shape[0], dtype="float64")          # underflow: one-hot on the nearest cell
    out[int(np.argmin(d2))] = 1.0
    return out


def normalise_footprint(g: ArrayLike) -> NDArray[np.float64]:
    """Normalise a footprint (e.g. a coda kernel sampled on the grid) to sum to 1.

    A footprint with **no support on the grid** — all-zero or all-NaN, e.g. a kernel that falls
    entirely outside the domain — has nothing to normalise and is returned as **all zeros**: a *null
    observation* that contributes no constraint. That is the intended semantics (``resolution`` treats
    such a row as observing nothing), not a silent failure; unlike a point sensor, a footprint that
    genuinely misses the grid has no natural cell to fall back to.
    """
    g = np.asarray(g, dtype="float64").ravel()
    tot = np.nansum(g)
    return np.nan_to_num(g / tot) if tot > 0 else np.zeros_like(g)


def satellite_footprints(coords_km: NDArray[np.float64], pixel_km: float,
                         land: ArrayLike | None = None) -> NDArray[np.float64]:
    """Footprints of a gridded satellite product with a ``pixel_km`` pixel over the whole domain.

    A satellite differs from a ground network in two decisive ways. It observes **everywhere**, not at a
    handful of sites -- each pixel is a footprint that **averages the state uniformly over the cells that
    fall within it** (a top-hat pixel average, not a Gaussian): assigning every grid cell to the pixel
    it lands in tiles the domain exactly, so it is robust whether the pixel is coarser than the grid
    (SMAP, 9 km: many cells per pixel) or finer (NISAR L-band SAR, ~0.2 km: one). But it is also **not a
    measurement of the state** -- a satellite retrieves soil moisture by inverting L-band brightness
    temperature or radar backscatter through a retrieval model, so it is a spatially-resolved *estimate*
    carrying retrieval and vegetation/roughness error. Its noise here is therefore a MODEL error, larger
    than a probe's instrument error, and it must not be treated as ground truth.

    ``land`` (an ``(n_cell,)`` mask, 1-D or a raster flattened to match) drops all-water pixels.
    Returns ``(n_pixels, n_cell)``.
    """
    if not (np.isfinite(pixel_km) and pixel_km > 0):
        raise ValueError(f"pixel_km must be a positive finite number, got {pixel_km!r}")
    c = np.asarray(coords_km, dtype="float64")
    n = c.shape[0]
    if land is None:
        keep = np.ones(n, dtype=bool)
    else:
        keep = np.asarray(land, dtype=bool).ravel()          # accept a 2-D raster mask, flattened
        if keep.size != n:
            raise ValueError(f"land mask has {keep.size} cells but coords_km has {n}")
    x, y = c[:, 0], c[:, 1]
    # assign each cell to the pixel it falls in, then average uniformly over a pixel's member cells
    ix = np.floor((x - x.min()) / pixel_km).astype(np.int64)
    iy = np.floor((y - y.min()) / pixel_km).astype(np.int64)
    pix = ix * (iy.max() + 1) + iy
    rows = []
    for pid in np.unique(pix):
        g = (pix == pid) & keep
        tot = int(g.sum())
        if tot > 0:                                          # skip pixels with no land in them
            rows.append(g.astype("float64") / tot)
    return np.vstack(rows) if rows else np.empty((0, n))


def channel_footprints(coords_km: NDArray[np.float64], hand_m: ArrayLike,
                       land: ArrayLike, hand_max_m: float = 2.0,
                       width_km: float = 0.5) -> NDArray[np.float64]:
    """Footprints of a **surface-water** observation, on the cells where the water table can outcrop.

    Surface-water extent (from optical differencing, e.g. Sentinel-2 NDWI) observes the *variable source
    area*: where the water table reaches the surface and quickflow is generated. Those cells are the
    valley floors and riparian corridors — ``HAND <= hand_max_m``. Each becomes a point-like observation
    that pins the shallow water table where the gauges only see the *integrated* discharge.

    ``hand_m`` and ``land`` may be 1-D or a raster flattened to match ``coords_km``; both must have one
    value per cell. Returns ``(n_channel_cells, n_cell)``.
    """
    c = np.asarray(coords_km, dtype="float64")
    n = c.shape[0]
    hand = np.asarray(hand_m, dtype="float64").ravel()
    lnd = np.asarray(land, dtype=bool).ravel()
    if hand.size != n or lnd.size != n:
        raise ValueError(f"hand_m ({hand.size}) and land ({lnd.size}) must both match n_cells ({n})")
    chan = lnd & np.isfinite(hand) & (hand <= hand_max_m)
    return np.vstack([point_footprint(c, c[i], width_km) for i in np.flatnonzero(chan)]) \
        if chan.any() else np.empty((0, c.shape[0]))


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


def blue_update(prior_cov: NDArray[np.float64], G: NDArray[np.float64], d: ArrayLike,
                noise_var: ArrayLike, prior_mean: ArrayLike = 0.0
                ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    r"""The analysis MEAN and posterior variance — the estimate itself, not only how well-resolved it is.

    Minimises the misfit

    .. math::  J(m) = (d - Gm)^\top R^{-1} (d - Gm) + (m - m_b)^\top B^{-1} (m - m_b),

    the weighted **data misfit** ``d - Gm`` plus the deviation from the model prior ``m_b``. For a
    linear operator ``G`` the minimiser is the BLUE / Kalman update

    .. math::  m_a = m_b + B G^\top (G B G^\top + R)^{-1} (d - G m_b),

    where ``d - G m_b`` is the **innovation** — the data minus the *model-predicted* data, evaluated for
    each datum at ITS OWN support (``G m_b`` upscales the fine prior to the datum's footprint). The
    heterogeneous resolution of the streams therefore enters only through ``G`` (space) and ``R``
    (time / error), never by regridding the data.

    ``prior_cov`` is ``B`` (n_cell x n_cell); ``G`` is ``(n_obs, n_cell)``; ``d`` and ``noise_var`` are
    length ``n_obs``; ``prior_mean`` is ``m_b`` (scalar or n_cell). Returns ``(m_a, var_post)``.
    """
    B = np.asarray(prior_cov, dtype="float64")
    G = np.atleast_2d(np.asarray(G, dtype="float64"))
    mb = np.broadcast_to(np.asarray(prior_mean, dtype="float64"), (B.shape[0],)).astype("float64")
    if G.size == 0 or G.shape[0] == 0:
        return mb.copy(), np.diag(B).copy()
    d = np.asarray(d, dtype="float64").ravel()
    if d.size != G.shape[0]:                          # guard against silent broadcasting of a bad d
        raise ValueError(f"d has length {d.size}, expected n_obs={G.shape[0]}")
    nv = np.asarray(noise_var, dtype="float64")
    if nv.ndim != 0 and nv.size != G.shape[0]:
        raise ValueError(f"noise_var must be scalar or length n_obs={G.shape[0]}, got {nv.size}")
    nv = np.broadcast_to(nv, (G.shape[0],))
    BG = B @ G.T                                     # (n_cell, n_obs)
    M = G @ BG + np.diag(nv)                          # (n_obs, n_obs)
    innov = d - G @ mb                               # data minus model-predicted data
    m_a = mb + BG @ np.linalg.solve(M, innov)
    var_prior = np.diag(B)
    reduction = np.einsum("ij,ji->i", BG, np.linalg.solve(M, BG.T))   # diag(BG M^-1 BG^T)
    reduction = np.clip(reduction, 0.0, var_prior)   # numerical guard: 0 <= reduction <= prior
    var_post = var_prior - reduction
    return m_a, var_post


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
