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

import warnings
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import sparse
from scipy.sparse import linalg as sparse_linalg


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
    if not (np.isfinite(length_km) and length_km > 0):
        raise ValueError(f"length_km must be a positive finite number, got {length_km!r}")
    r = _SQRT3 if nu == 1.5 else (_SQRT5 if nu == 2.5 else 1.0)
    d = np.asarray(dist_km, dtype="float64") / length_km
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
    that scalability fault is closed separately by :class:`SparseMaternPrior`, the sparse GMRF/SPDE
    precision sibling of this class, which carries the same prior in ``O(n)`` rather than ``O(n^2)``
    storage. It is a *sibling*, not a drop-in: a *local* (sparse) precision exists in 2-D only for
    **integer** ``alpha``, i.e. ``nu = alpha - 1`` in {1, 2, ...}, so none exists at ``nu=1.5``. That
    sibling is the ``nu=1`` (``alpha=2``) version of this class's ``nu=1.5`` default -- ``nu=2``
    (``alpha=3``) does have a sparse precision but was rejected on other grounds: it is *smoother* than
    1.5, the wrong direction for issue #163, and costs a 25-point stencil. See its docstring for exactly
    what that costs. This class remains the reference on grids small enough to hold a dense ``C``.
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
    would be borrowed from the *spatial* kernel (:class:`GaussianPrior`, which is Matern since PR #181
    -- see :func:`matern_correlation` -- and was the squared-exponential :math:`\exp(-d^2/2L^2)` before
    that, the form the stray factor of 2 comes from; either way it describes a spatial random field,
    not a first-order Markov process in time) and does not belong here.
    """
    if not (np.isfinite(tau_days) and tau_days > 0):
        raise ValueError(f"tau_days must be a positive finite number, got {tau_days!r}")
    dt = np.asarray(lag_days, dtype="float64")
    if np.any(dt < 0):
        raise ValueError("lag_days must be >= 0 (a datum from the future is not a lag)")
    return np.exp(-dt / tau_days)


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
    - the **effective noise gains a drift term** :math:`\sigma_m^2(1-\rho^2)` on top of the instrument
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

    ``kind`` is the spatial geometry (point / volume / satellite / channel / flux). ``is_measurement``
    records whether the stream *measures* the state or *estimates* it through a retrieval model — a
    satellite soil-moisture product is the latter, and its noise is a model error, not an instrument
    error. ``employed`` is a SEPARATE axis from ``is_measurement``: whether this repo's pipeline
    actually ingests the stream today (``True``) or the entry is a design-catalog placeholder for a
    real, located network we don't yet pull data from (``False``) — the black/gray marker-edge
    convention on the network map follows this field, not ``is_measurement``.
    """

    name: str
    states: tuple[str, ...]          # which model states it informs (from TEMPORAL_TAU_DAYS keys)
    support_km: float                # spatial footprint (point ~ 0.1; SMAP 9; NISAR 0.2; dv/v ~ path)
    revisit_days: float              # sampling interval (0 = continuous)
    kind: str                        # "point" | "volume" | "satellite" | "channel" | "flux"
    noise: float                     # observation-error VARIANCE (sigma_d^2), in units of the prior variance
    is_measurement: bool             # True = measures the state; False = a retrieval / model estimate
    employed: bool = True            # True = this repo ingests it today; False = real network, not yet used


# The observing system, on both axes. Revisit is what the user's point turns on: soil moisture changes
# in days, so a weekly satellite ALIASES it however fine its pixels; the continuous seismic array and
# the sub-daily probes are the streams that resolve the events.
STREAMS: tuple[ObsStream, ...] = (
    ObsStream("NWIS wells", ("gwl",), 0.1, 30.0, "point", 0.02, True),
    ObsStream("SNOTEL / SCAN θ", ("soil_moisture",), 0.1, 0.04, "point", 0.03, True),   # hourly
    ObsStream("USCRN θ", ("soil_moisture",), 0.1, 0.04, "point", 0.03, True),           # hourly
    ObsStream("Seismic dv/v", ("soil_moisture", "gwl"), 8.0, 0.04, "volume", 0.12, True),  # ~continuous
    ObsStream("SMAP (retrieval)", ("soil_moisture",), 9.0, 2.5, "satellite", 0.10, False),
    ObsStream("NISAR Beta SM v1 (retrieval)", ("soil_moisture",), 0.2, 6.0, "satellite", 0.06, False,
              employed=False),   # real product since 2025-10-01 (issue #197), not yet ingested here
    # Cloud-limited optical revisit, not the nominal 5-day Sentinel-2 orbit: usable cloud-free passes
    # over this domain run roughly every 1-3 WEEKS, not days -- corrected from an earlier 6-day figure.
    # A time-lapse, geospatially distributed proxy for river/wetland extent (hence water HEIGHT at the
    # channel margin), not a point gauge.
    ObsStream("Sentinel surface water", ("gwl",), 0.1, 14.0, "channel", 0.04, False, employed=False),
    ObsStream("USGS gauges", ("gwl",), 5.0, 0.01, "flux", 0.05, True),                  # 15-min, basin
    # Real, located networks with no fetcher/assimilation path yet -- see the network map for
    # coordinates. Weather stations are what PRISM is itself built from; using them directly (rather
    # than only PRISM's finished grid) would let local station data correct/downscale the coarse
    # forcing instead of just consuming it as-is.
    ObsStream("GHCN-Daily weather stations", ("gwl", "soil_moisture"), 0.1, 1.0, "point", 0.05, True,
              employed=False),
    # GNSS-IR (reflectometry, near-surface soil moisture/snow/water level) and GNSS-TEC/ZTD-derived
    # precipitable water are two DIFFERENT retrievals from the same antennas; both unemployed.
    ObsStream("GNSS-IR / GNSS-TEC precipitable water", ("soil_moisture",), 0.1, 1.0, "point", 0.08,
              False, employed=False),
    # NOAA Stage IV is a gridded (4 km CONUS) radar+gauge precip analysis, not a point network -- no
    # station coordinates to plot; carried here only so it appears in the design catalog.
    ObsStream("NOAA Stage IV radar precip (gridded)", ("gwl", "soil_moisture"), 4.0, 0.25, "satellite",
              0.08, False, employed=False),
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


# --- the sparse GMRF/SPDE sibling of the dense prior (issue #163, the scalability fault) ----------
# Issue #163 raised two faults. Terrain-awareness (Matern kernel + ``region_id``) is closed above, on
# the dense path (PR #181). What follows closes the OTHER one: a dense ``(n, n)`` covariance is 85 GB
# at n = 1e5 and ~800 TB at the 90 m full-resolution domain (n ~ 1e7), which is why the twin only ever
# solves on a coarsened assimilation grid. The fix is to carry the SAME kind of prior by its
# **precision** Q = B^-1 rather than its covariance, because for a Matern field the precision is
# **sparse** -- 13 non-zeros per row, ~1.6 GB at n = 1e7 -- via the Whittle-Matern SPDE
#
#     tau (kappa^2 - Laplacian)^(alpha/2) x(u) = W(u),   nu = alpha - d/2 = alpha - 1  in 2-D.
#
# Nothing above this line changes. The dense path stays the small-grid reference, and the two are
# cross-checked against each other exactly (feed ``inv(Q)`` to the dense :func:`resolution`).

_SPLU_MAX_N = 2_000_000        # above this, splu fill (~134 nnz/row, O(log n)) costs > ~4 GB: use CG
_EXACT_MAX_N = 4096            # guard on the O(n) -solves / dense-inverse verification paths
_CG_RTOL = 1e-10               # CG on K~ is cheap (cond <= 7.9e3 at the repo's kappa*dx); solve tight
_STANDARDIZE_SEED = 0          # frozen dataclass => the standardization must be DETERMINISTIC
_STANDARDIZE_SAMPLES = 512
_KAPPA_DX_MAX = 0.36           # >= 8 cells per practical range; above this the discretization error of
                               # approximation 2 is extrapolated, not measured (see _warn_on_geometry)
_MC_CHUNK_BYTES = 2.5e8        # NOMINAL (8*n*k) size of one Monte-Carlo block. The realized peak is
                               # ~7x that (~1.8 GB here): z, the solve's output, the C-order copy that
                               # feeds the FFT, and the complex128 transform / quotient / inverse pair,
                               # which are 2 bytes-per-element each. O(n) in n, as claimed -- but do
                               # not read 2.5e8 as a resident-set figure.
_X_MAX_BYTES = 8.0e9           # PEAK budget for X = Q^-1 G^T, which is DENSE (n, n_obs) -- refuse
                               # rather than thrash (#9.10). Counted at _X_PEAK_MULT, not 1x.
_X_PEAK_MULT = 4               # (n, n_obs) arrays live simultaneously while X is formed: the C-order
                               # G^T copy, the two nested 5-point solves' outputs, and one more for the
                               # standardize=True rescale. Budgeting 1x would admit ~4x the memory.


def matern_spde_tau(kappa: float, dx_km: float, dy_km: float, sigma: float,
                    quad_n: int = 4096) -> float:
    r"""SPDE scaling :math:`\tau` giving a **discrete** marginal variance of exactly ``sigma**2``.

    The continuum SPDE (issue #163, :class:`SparseMaternPrior`) has marginal variance
    :math:`\sigma^2 = 1/(4\pi\kappa^2\tau^2)` in 2-D at :math:`\alpha=2`, i.e.
    :math:`\tau^2_\text{cont} = L^2/(8\pi\sigma^2)`. **The discretized operator does not reproduce
    that**: the 5-point stencil inflates the stationary variance over the continuum by a factor that
    depends only on :math:`\kappa\,dx` --

    ==========  ======  ======  ======  ======  =======  =======
    kappa*dx     0.5     0.25    0.1     0.05    0.02     0.01
    var ratio   1.0824  1.0325  1.0076  1.0023  1.00046  1.00013
    ==========  ======  ======  ======  ======  =======  =======

    -- negligible (0.1%) on the 90 m grid with L = 4 km, but **8% on the 2 km coarsened assimilation
    grid this repo actually solves on**. So :math:`\tau` is taken from the exact discrete
    (Brillouin-zone) marginal variance :math:`\bar I_\infty/(\tau^2 h)` of the infinite lattice,

    .. math::  \bar I_\infty = \frac{1}{4\pi^2}\iint_{[-\pi,\pi]^2}
               \frac{d\theta_1 d\theta_2}{\big[\kappa^2 + \tfrac{4}{dx^2}\sin^2\tfrac{\theta_1}{2}
               + \tfrac{4}{dy^2}\sin^2\tfrac{\theta_2}{2}\big]^2},
               \qquad \tau^2 = \frac{\bar I_\infty}{h\,\sigma^2},\quad h = dx\,dy .

    The :math:`\theta_2` integral is done in closed form (that is the difference between a fragile 2-D
    quadrature and a trivial 1-D one): with :math:`a(\theta)=\kappa^2+\tfrac{4}{dx^2}\sin^2(\theta/2)`,
    :math:`b=4/dy^2` and :math:`\int_{-\pi/2}^{\pi/2}du/(a+b\sin^2 u)^2 = \pi(2a+b)/(2[a(a+b)]^{3/2})`,

    .. math::  \bar I_\infty = \frac{1}{2\pi}\int_0^\pi
               \frac{2a(\theta)+b}{[a(\theta)(a(\theta)+b)]^{3/2}}\,d\theta ,

    evaluated by the **midpoint rule** with ``quad_n`` nodes: the integrand is smooth and periodic, so
    convergence is spectral (``quad_n=4096`` agrees with 8192 to < 1e-9, and with a direct 2-D
    quadrature to 10 significant figures). Anisotropy ``dx != dy`` is handled exactly. Cost:
    microseconds, independent of ``n``.

    With this normalization the interior marginal variance of the discrete field equals
    :math:`\sigma^2` to ~1e-11 relative. Two caveats remain, both documented on
    :class:`SparseMaternPrior`: this is the **infinite-lattice** value, so it is only attained
    :math:`\gtrsim` one practical range from every boundary and every severed edge; and a domain
    narrower than ~3 practical ranges has no such interior at all (the finite-torus ratio
    :math:`\bar I_N/\bar I_\infty` is 1.33 / 1.011 / 1.00001 at 1.3 / 2.6 / 5.1 ranges wide).
    """
    for name, val in (("kappa", kappa), ("dx_km", dx_km), ("dy_km", dy_km), ("sigma", sigma)):
        if not (np.isfinite(val) and val > 0):
            raise ValueError(f"{name} must be a positive finite number, got {val!r}")
    if int(quad_n) < 1:
        raise ValueError(f"quad_n must be a positive integer, got {quad_n!r}")
    m = int(quad_n)
    theta = (np.arange(m) + 0.5) * (np.pi / m)                  # midpoints of [0, pi]
    a = kappa ** 2 + (4.0 / dx_km ** 2) * np.sin(0.5 * theta) ** 2
    b = 4.0 / dy_km ** 2
    integrand = (2.0 * a + b) / (a * (a + b)) ** 1.5
    ibar_inf = float(integrand.mean()) / 2.0                     # (1/2pi) * (pi/m) * sum = mean/2
    return float(np.sqrt(ibar_inf / (dx_km * dy_km * sigma ** 2)))


@dataclass(frozen=True)
class SparseMaternPrior:
    r"""Sparse-precision (GMRF/SPDE) sibling of :class:`GaussianPrior`: **O(n) storage, not O(n^2)**.

    Same physics, different representation: instead of a dense covariance ``C`` this carries the
    **precision** :math:`Q = B^{-1}` of a Matern field on a regular grid, obtained as the discretized
    Whittle-Matern SPDE :math:`\tau(\kappa^2-\Delta)^{\alpha/2}x = W` (issue #163). It exists because
    the dense path cannot be run at full resolution: at n = 1e7 a dense ``C`` is ~800 TB, while ``Q``
    has ~13 non-zeros per row and fits in ~1.6 GB.

    **It is a consistent SIBLING, not a bit-identical replacement, of the dense nu=1.5 default.**
    A local (banded, hence sparse) precision exists in 2-D only for **integer** :math:`\alpha`, and
    :math:`\nu=\alpha-1`; there is no integer :math:`\alpha` giving :math:`\nu=1.5`. This class is
    :math:`\alpha=2\Rightarrow\nu=1` and refuses any other ``nu``. At matched ``length_km`` the two
    kernels differ by

    - :math:`\sup_r|\rho_{\nu=1}-\rho_{\nu=1.5}| = \mathbf{0.0538}` at :math:`r = 0.575\,L`;
    - relative :math:`L^2` difference in the plane **6.8%**;
    - **identical total correlation mass** :math:`\int\rho\,d^2r = 4\pi\nu/\kappa^2 = 2\pi L^2`,
      independent of :math:`\nu` -- so matching ``length_km`` matches the total covariance mass
      exactly and only redistributes it over lag (the strongest single argument that the mismatch is a
      redistribution, not a rescaling). Note this is a *DC* statement, :math:`S(k=0)`: what actually
      differs is the high-:math:`k` tail, :math:`k^{-4}` at :math:`\nu=1` against :math:`k^{-5}` at
      :math:`\nu=1.5` -- which is precisely the roughness issue #163 is about. The sup and :math:`L^2`
      figures above are what bound the magnitude of that difference;
    - the curves **cross at exactly the practical range** :math:`r=2L`, agreeing there to 6e-5;
      :math:`\nu=1` is slightly below inside the range and slightly above outside.

    :math:`\nu=1` is inside the band issue #163 itself asks for (``nu ~ 0.5-1.5``) and is *rougher*
    than 1.5 -- it moves in the direction the issue complains the prior is deficient (over-smoothness),
    not against it. Downstream, interior per-cell resolution (:func:`resolution_precision` against the
    dense :func:`resolution` at ``nu=1.5``, cells >= 1 practical range from every edge) is
    **layout-dependent and is quoted as a measured envelope, not a single number**. Over **5000 random
    sensor layouts** at the benchmark configuration -- 61x61, dx = 0.5 km, L = 3 km, 8 point
    footprints, noise 0.02 -- ``max|dres|`` runs **0.015-0.112** (median 0.090) and ``rms|dres|``
    **0.003-0.053** (median 0.033); against a dense ``nu=1`` Bessel kernel, which isolates
    discretization alone, ``max|dres|`` runs **0.007-0.025**. What sets the spread is how much of the
    interior a given layout actually informs: the low end of each range is a layout with no footprint
    in the interior at all. **Budget ~0.13 max / ~0.065 rms** -- what
    ``tests/test_observability_sparse.py`` asserts, ~16-22% above the worst of 5000 -- before deciding
    the sibling swap is acceptable for a given use. *An earlier version of this docstring quoted ~0.10
    max / ~0.045 rms from a six-layout sample; 3.3% and 1.3% of layouts respectively exceed those, so
    they were a ~97th percentile and not a budget.* The decomposition into a :math:`\nu`-mismatch part
    and a discretization part is **exact cell by cell** (``dres = d_disc + d_nu`` to 1e-12) but the
    three sup-norms are attained at **different cells**, so their maxima do **not** add: summing them
    overstates the true maximum by a median 1.9% and up to 9.9%. *A previous version of this paragraph
    instead quoted a single reference configuration -- 81x81, dx = 0.5 km, L = 4 km -- as 0.066 max, of
    which ~0.054 nu mismatch and ~0.012 discretization, taken from issue #163's spec (#7.5). Those
    three figures are NOT REPRODUCED by anything in this repo: re-measured at exactly that
    configuration over 200 random layouts, the total runs* **0.075-0.101**, *the nu part*
    **0.063-0.086** *and the discretization part* **0.012-0.018** *-- not one layout of the 200 reaches
    0.066. Its "0.054 + 0.012 = 0.066" was in any case never an identity, by the different-cells point
    above.* Rescaling ``length_km`` to hide the offset was considered and **rejected**: it would make
    ``length_km`` mean two different things in the two classes, a worse defect than a 5% correlation
    offset.

    **Convention.** ``kappa = sqrt(2*nu)/length_km``, matching :func:`matern_correlation` exactly (that
    function uses the Matern SCALE convention: its arguments are :math:`\sqrt{3}d/L`, :math:`d/L`,
    :math:`\sqrt{5}d/L`). ``length_km`` is therefore :math:`\ell`, **not** the practical range;
    the Lindgren practical range (correlation ~0.14) is :math:`\sqrt{8\nu}/\kappa = 2\cdot` ``length_km``
    for every :math:`\nu`. Using Lindgren's :math:`\kappa=\sqrt{8\nu}/\ell` here would make this prior
    **half as long-ranged** as the dense one at the same ``length_km``.

    **Boundary: Neumann (reflecting)**, implemented by folding an absent edge's weight into the
    diagonal. Physically right for a hydrologic state -- no-flux is exactly what a drainage divide is --
    and it is the *same* rule ``region_id`` severing uses, so the domain edge and a terrain divide are
    not two pieces of code. Its cost is a **variance inflation near the boundary**: measured
    :math:`\times 1.955` at a straight edge and :math:`\times 3.834` at a corner, decaying to +0.9% at
    one practical range and +0.07% at 1.5. **Mitigation: pad the analysis rectangle by >= 1 practical
    range = ``2*length_km`` beyond the region of interest**; the constructor warns if the domain is too
    small to hold that padding. (Dirichlet was considered: it is worse -- a variance *collapse* to
    0.117 sigma^2 at the face, which drives :func:`resolution`'s denominator toward zero.)

    **``region_id`` severs edges by folding, not deleting.** An edge is included iff its two cells
    share a label; otherwise its weight goes onto the diagonal. Consequences: cross-region covariance
    is **exactly, structurally zero** (bit-exact 0.0, not 1e-16), the operator is provably SPD for
    *any* labelling (:math:`L_G\succeq 0` and :math:`\tilde K\succeq\kappa^2 I`, including labellings
    that isolate single cells), and the severed face carries the *same* x1.955 inflation as a free
    edge -- which is what proves the fold was implemented rather than the deletion. Deleting instead
    (zeroing the off-diagonal, leaving the diagonal) is a Dirichlet-like internal boundary that
    *deflates* variance at the divide, i.e. claims near-certainty exactly where the terrain says the
    two sides are independent.

    **Why this is cleaner than masking a dense kernel.** :class:`GaussianPrior` forms
    :math:`\sigma^2\rho(d)\odot\mathbf 1[r_i=r_j]`, which is PSD only by a structural accident (a 0/1
    *equivalence-relation* mask is a permutation-similar block-diagonal restriction of a PSD matrix; a
    general or partial mask would break it), and it asserts something physically strange: that the
    field on each side of the divide is *exactly* the unmasked stationary field, as if the divide were
    not there at all except in the cross terms. Zeroing :math:`\tilde K_{ij}` instead asserts a
    **conditional-independence** statement -- :math:`x_i \perp x_j` given all other cells, i.e. the two
    cells do not communicate *locally*, which is the actual hydrologic claim -- and propagates it
    consistently, changing the field on both sides near the divide rather than pretending nothing
    happened. Positive-definiteness follows from the operator, not from the mask's combinatorics.

    **Small regions are the severe case and this class does not hide it.** Neumann folding at *every*
    boundary of a small patch compounds: for region area :math:`A \ll \kappa^{-2}` the field is
    essentially constant over it and :math:`\mathrm{Var}\approx\sigma^2\,4\pi/(\kappa^2 A)` (an exact
    prediction: 25.1 predicted vs 25.0 measured for a 2 km region at L = 4 km; **x395 for an isolated
    single cell**). Real HUC / HAND-derived units *will* be smaller than a practical range, so this is
    not hypothetical -- the dense masked kernel gives sigma^2 for such a cell, this gives up to
    hundreds of sigma^2. Mitigation: **``standardize=True``**, a diagonal congruence
    :math:`\tilde B = D B D`, :math:`D=\mathrm{diag}(\sigma/\sqrt{B_{ii}})`, which forces
    :math:`\mathrm{diag}(\tilde B)=\sigma^2` exactly, **preserves SPD**, **preserves every structural
    zero** (cross-region covariance stays exactly 0) and **leaves all correlations unchanged**. It is a
    modelling choice, not a gauge fix: :func:`resolution_precision` is *not* invariant to it (it
    reweights observation space through M). The constructor warns when any region is smaller than a
    practical range squared.

    **O(n) applies to the PRIOR REPRESENTATION, not to the whole estimator** (issue #163, approximation
    10). ``Q`` is 13 nnz/row -- measured nnz/n of 12.52 / 12.75 / 12.88 / 12.94 at n = 1681 / 6561 /
    25921 / 103041, versus a dense ``C`` of 0.023 / 0.34 / 5.4 / 85 GB -- so the prior is ~1.6 GB at
    n = 1e7 where dense is 800 TB. But :math:`X = Q^{-1}G^\top` in :func:`resolution_precision` **is
    dense** ``(n, n_obs)``: 8 GB at n = 1e7 with 100 observations. Those functions enforce an explicit
    ``n*n_obs`` budget and raise rather than thrash; chunk over observation columns above it. Also,
    ``splu`` fill grows as O(log n) per row (86.8 -> 134.1 nnz/row over n = 4e4 -> 6.4e5, 1.03 GB), so
    ``solver="auto"`` switches to preconditioned CG (O(n) memory) above n = 2e6.

    Parameters
    ----------
    sigma, length_km
        Marginal standard deviation and Matern **scale** (practical range = ``2*length_km``).
    shape
        ``(ny, nx)``. Cell ``(jy, jx)`` is index ``jy*nx + jx`` -- **C-order**, which is what
        ``coords_km`` raveled from a meshgrid gives, so ``G`` rows built for the dense path index this
        prior unchanged.
    dx_km, dy_km
        Uniform spacings in km; ``dy_km`` defaults to ``dx_km``. Anisotropy is supported exactly (the
        :math:`\tau` integral handles it); a **non-uniform** grid is not (see approximations below) and
        is refused by construction -- this class takes spacings, not coordinates.
    region_id
        ``(ny, nx)`` or ``(n,)`` labels; ``None`` for a single region.
    nu
        Must be ``1.0``. Any other value raises with the reason.
    standardize
        Opt-in per-cell variance renormalization (above). Recommended whenever ``region_id`` comes from
        real HUC/HAND units.
    solver
        ``"auto"`` (splu below n = 2e6, else CG), ``"splu"``, or ``"cg"``.

    Stated approximations (issue #163; each is measured, not asserted)
    ------------------------------------------------------------------
    1. **nu = 1, not 1.5** -- quantified above: sup|drho| = 0.0538, relative L2 6.8%, and interior
       per-cell resolution 0.015-0.112 max / 0.003-0.053 rms against the dense nu=1.5 path over 5000
       sensor layouts at the benchmark configuration (layout-dependent, quoted as an envelope).
    2. **Second-order 5-point finite differences.** The discrete interior correlation is a smooth,
       one-signed *deficit* relative to closed-form Matern nu=1, converging as O((kappa*dx)^1.4):
       max|drho| = 0.029 / 0.012 / 0.0043 at 8 / 16 / 32 cells per practical range. Requires **>= 8
       cells per practical range** for < 0.035; >= 16 recommended. One-signedness is an **isotropy**
       property, not a property of the operator: on an anisotropic grid the FINE axis *overshoots* the
       analytic correlation by up to +4.6e-4 at the two shortest lags (the coarse axis stays one-signed
       to 7e-7). The binding spacing is the **coarser** axis, so the constructor warns when
       ``kappa*max(dx, dy) > 0.36``; past that the error is extrapolated, not measured (nothing was
       benchmarked above kappa*dx = 0.354). ``max``, not ``min``: issue #163's spec (#9, approximation
       2) writes ``kappa*min(dx, dy) <= 0.36`` and the spec is **wrong** -- reconciling this code to it
       would silence the warning on exactly the anisotropic grids it exists to catch. Measured at
       kappa*dx = 0.088 with kappa*dy = 0.354: the coarse axis carries max|drho| = 0.0223, *better*
       than the 0.0292 of a fully-coarse isotropic grid, so ``kappa*max(dx, dy)`` is a CONSERVATIVE
       proxy and the 0.36 threshold is safe. But the axes are **coupled** -- the fine axis carries
       0.0089, 2.1x its own isotropic 0.0043 -- so refining one axis alone buys ~2.5x, not the ~7x the
       isotropic table above would suggest. Note the repo's own 2 km coarsened assimilation grid at
       L = 4 km sits at kappa*dx = 0.71, ~2x the limit, and *will* trip that warning. Because tau is
       normalized exactly, the error is *not* concentrated at short lags -- at 32 cells/range the
       1-cell error (0.0023) is smaller than the 6-cell error (0.0042).
    3. **Lumped mass matrix** (M = h*I, giving Q = tau^2 h K~^2). This is what *makes* the method
       sparse at all: with the consistent mass matrix M^-1 is dense and Q is not sparse. Its O(h^2)
       error is not separately identifiable and is already inside the numbers in (2).
    4. **Uniform rectangular grid**, C-order ravel matching ``coords_km``. On a non-uniform grid mass
       lumping breaks the exact self-adjointness of K~ and this construction is invalid.
    5. **Neumann boundary by diagonal folding** -- x1.955 / x3.834 inflation, above.
    6. **``region_id`` severing is a reflecting internal boundary** -- exact zeros, but the
       4*pi/(kappa^2 A) small-region inflation, above.
    7. **tau from the exact discrete Brillouin-zone integral**, not the continuum formula
       (:func:`matern_spde_tau`) -- 1e-11 interior accuracy instead of an 8% inflation on a 2 km grid.
    8. **diag(B) by Monte Carlo by default** (:meth:`marginal_var`) -- unbiased, per-cell relative rms
       sqrt(2/K) before the control variate (~2% at K = 512), **stochastic**: it depends on the seed,
       so pass an explicit ``rng`` and record it.
    9. **Two-stage solve through K~, never Q** (:meth:`solve`) -- exact, but a hard numerical
       requirement: cond(Q) = cond(K~)^2.
    10. **O(n) is the prior, not the estimator** -- above.
    """

    sigma: float
    length_km: float
    shape: tuple[int, int]
    dx_km: float
    dy_km: float | None = None
    region_id: NDArray[np.int64] | None = None
    nu: float = 1.0
    standardize: bool = False
    solver: str = "auto"

    # -- construction, validation, and the three mandated warnings ---------------------------------

    def __post_init__(self) -> None:
        object.__setattr__(self, "_cache", {})
        for name, val in (("sigma", self.sigma), ("length_km", self.length_km),
                          ("dx_km", self.dx_km)):
            if not (np.isfinite(val) and val > 0):
                raise ValueError(f"{name} must be a positive finite number, got {val!r}")
        if self.dy_km is not None and not (np.isfinite(self.dy_km) and self.dy_km > 0):
            raise ValueError(f"dy_km must be a positive finite number or None, got {self.dy_km!r}")
        if self.nu != 1.0:
            raise ValueError(
                f"SparseMaternPrior supports nu=1.0 only, got {self.nu!r}. A local (sparse) precision "
                "exists in 2-D only for integer alpha, and nu = alpha - 1: alpha=2 gives nu=1 (the "
                "5-point K~ / 13-point Q stencil with an exact symmetric square root). alpha=3 (nu=2) "
                "is smoother than the dense 1.5 default -- the wrong direction for issue #163 -- and "
                "needs a 25-point stencil; fractional alpha needs a Bolin-Kirchner rational "
                "approximation. Use the dense GaussianPrior for other nu.")
        if self.solver not in ("auto", "splu", "cg"):
            raise ValueError(f"solver must be one of 'auto', 'splu', 'cg', got {self.solver!r}")
        try:
            ny, nx = (int(self.shape[0]), int(self.shape[1]))
        except (TypeError, IndexError, ValueError):
            raise ValueError(f"shape must be a (ny, nx) pair of ints, got {self.shape!r}") from None
        if ny < 1 or nx < 1 or (ny, nx) != tuple(self.shape):
            raise ValueError(f"shape must be a (ny, nx) pair of positive ints, got {self.shape!r}")
        if self.region_id is not None:
            rid = np.asarray(self.region_id)
            if rid.ndim == 2 and rid.shape != (ny, nx):
                raise ValueError(f"region_id has shape {rid.shape}, expected {(ny, nx)}")
            if rid.size != ny * nx:
                raise ValueError(f"region_id has {rid.size} cells, expected n={ny * nx}")
            self._cache["region"] = rid.ravel()                  # C-order, matching the cell ordering
        self._warn_on_geometry(ny, nx)

    def _warn_on_geometry(self, ny: int, nx: int) -> None:
        """The four warnings issue #163's approximation list requires.

        Resolution (approximation 2), padding (5), interior (7) and small regions (6). Each names the
        measured artifact it is warning about, because the numbers still *look* plausible without it.
        """
        rng_km = 2.0 * self.length_km                            # practical range
        d_max = max(float(self.dx_km), self._dy)                 # the COARSER axis limits accuracy
        kdx = self.kappa * d_max
        if kdx > _KAPPA_DX_MAX:
            warnings.warn(
                f"kappa*max(dx,dy) = {kdx:.3g} exceeds {_KAPPA_DX_MAX}: the coarser grid axis resolves "
                f"the practical range ({rng_km:.3g} km) with only {rng_km / d_max:.3g} cells. The "
                "5-point discretization was measured at max|drho| = 0.029 / 0.012 / 0.0043 at "
                "kappa*dx = 0.354 / 0.177 / 0.088 (8 / 16 / 32 cells per practical range; empirical "
                f"convergence O((kappa*dx)^1.4)). Above {_KAPPA_DX_MAX} the correlation error is "
                "EXTRAPOLATED, not measured -- nothing was benchmarked past kappa*dx = 0.354. Use "
                f">= 8 cells per practical range (>= 16 preferred), i.e. dx, dy <= "
                f"{_KAPPA_DX_MAX / self.kappa:.3g} km (>= 16: "
                f"{_KAPPA_DX_MAX / 2.0 / self.kappa:.3g} km) at "
                f"length_km={self.length_km:.3g}.",
                UserWarning, stacklevel=4)
        ext_x, ext_y = nx * self.dx_km, ny * self._dy
        if min(ext_x, ext_y) < 2.0 * rng_km:
            warnings.warn(
                f"domain is {ext_x:.3g} x {ext_y:.3g} km but one practical range is {rng_km:.3g} km: "
                "it cannot hold the >= 1 practical range (= 2*length_km) of padding the reflecting "
                "(Neumann) boundary needs on each side of the region of interest. Marginal variance "
                "is inflated x1.95 at a straight edge and x3.83 at a corner, decaying to +0.9% at one "
                "practical range. Pad the analysis rectangle, or use standardize=True.",
                UserWarning, stacklevel=4)
        if min(ext_x, ext_y) < 3.0 * rng_km:
            warnings.warn(
                f"domain ({min(ext_x, ext_y):.3g} km across) is narrower than ~3 practical ranges "
                f"({3.0 * rng_km:.3g} km): it has no stationary interior, so the 'marginal variance = "
                "sigma^2' claim is meaningless anywhere on it (the finite-domain correction to the "
                "tau normalization is +33% at 1.3 ranges, +1.1% at 2.6, +1e-5 at 5.1).",
                UserWarning, stacklevel=4)
        rid = self._cache.get("region")
        if rid is not None:
            h = self.dx_km * self._dy
            _, counts = np.unique(rid, return_counts=True)
            areas = counts * h
            small = areas < rng_km ** 2
            if small.any():
                a_min = float(areas.min())
                warnings.warn(
                    f"{int(small.sum())} of {areas.size} region_id regions are smaller than one "
                    f"practical range squared ({rng_km ** 2:.3g} km^2); the smallest is {a_min:.3g} "
                    "km^2. Reflecting internal boundaries inflate the marginal variance of a small "
                    f"region by ~4*pi/(kappa^2 A) = x{4.0 * np.pi / (self.kappa ** 2 * a_min):.3g} "
                    "there (x395 in the isolated-single-cell limit). Pass standardize=True to "
                    "renormalize it away (correlations and structural zeros are preserved).",
                    UserWarning, stacklevel=4)

    # -- derived parameters ------------------------------------------------------------------------

    @property
    def _dy(self) -> float:
        """Effective ``dy_km`` (defaults to ``dx_km``)."""
        return float(self.dx_km if self.dy_km is None else self.dy_km)

    @property
    def _h(self) -> float:
        """Cell area ``dx*dy`` in km^2 -- the lumped mass (approximation 3)."""
        return float(self.dx_km) * self._dy

    @property
    def kappa(self) -> float:
        r""":math:`\kappa=\sqrt{2\nu}/L`, the repo's Matern SCALE convention (NOT Lindgren's
        :math:`\sqrt{8\nu}/L`) -- see the class docstring. Practical range = ``2*length_km``."""
        return float(np.sqrt(2.0 * self.nu) / self.length_km)

    @property
    def tau(self) -> float:
        r""":math:`\tau` from the exact discrete normalization -- see :func:`matern_spde_tau`."""
        if "tau" not in self._cache:
            self._cache["tau"] = matern_spde_tau(self.kappa, float(self.dx_km), self._dy,
                                                 float(self.sigma))
        return self._cache["tau"]

    @property
    def n(self) -> int:
        """Number of cells ``ny*nx``."""
        return int(self.shape[0]) * int(self.shape[1])

    # -- the operator ------------------------------------------------------------------------------

    def operator(self) -> "sparse.csr_matrix":
        r"""The **5-point square root** :math:`A=\tau\sqrt h\,\tilde K`, with :math:`Q=A^\top A`.

        :math:`\tilde K=\kappa^2 I + L_G` where :math:`L_G` is the weighted graph Laplacian of the
        4-neighbour grid graph with edge weights :math:`1/dx^2` (horizontal) and :math:`1/dy^2`
        (vertical). An edge is **present** iff both cells are in the grid and share a ``region_id``;
        an absent edge is omitted from the off-diagonal **and** from the diagonal sum together --
        which is simultaneously the second-order 5-point Laplacian, the reflecting (Neumann) domain
        boundary (the ghost cell :math:`x_{-1}=x_0` folds :math:`-1/dx^2` onto the diagonal), and the
        reflecting internal boundary at a terrain divide. One edge list, one rule.

        Interior diagonal :math:`\kappa^2+2/dx^2+2/dy^2`; straight edge :math:`\kappa^2+1/dx^2+2/dy^2`;
        corner :math:`\kappa^2+1/dx^2+1/dy^2`. Exact properties, all cheap to assert:
        :math:`\tilde K=\tilde K^\top` to the bit; :math:`L_G\succeq0` with :math:`L_G\mathbf 1=0` for
        *any* edge subset, so :math:`\lambda_\min(\tilde K)=\kappa^2` **exactly** (attained at the
        constant vector of each connected component) and :math:`Q\succeq\tau^2h\kappa^4 I\succ0` for
        every ``region_id`` labelling; Gershgorin gives
        :math:`\mathrm{cond}(\tilde K)\le1+(4/dx^2+4/dy^2)/\kappa^2`; <= 5 nnz per row.

        This -- not ``Q`` -- is what is stored and factorized (:meth:`solve`). Note that under
        ``standardize=True`` this still returns the **unstandardized** square root: the standardized
        operator has no 5-point square root (:meth:`precision` returns the standardized ``Q``, and
        nothing is lost computationally because the standardized solve is still two solves through
        this ``A``).
        """
        if "A" not in self._cache:
            self._cache["A"] = self._build_operator()
        return self._cache["A"]

    def _build_operator(self) -> "sparse.csr_matrix":
        ny, nx = int(self.shape[0]), int(self.shape[1])
        n = ny * nx
        wx, wy = 1.0 / float(self.dx_km) ** 2, 1.0 / self._dy ** 2
        rid = self._cache.get("region")
        idx = np.arange(n).reshape(ny, nx)
        pairs = []                                           # (i, j, weight) of every candidate edge
        if nx > 1:
            pairs.append((idx[:, :-1].ravel(), idx[:, 1:].ravel(), wx))     # horizontal, 1/dx^2
        if ny > 1:
            pairs.append((idx[:-1, :].ravel(), idx[1:, :].ravel(), wy))     # vertical,   1/dy^2
        ei, ej, ew = [], [], []
        for i_all, j_all, w in pairs:
            keep = slice(None) if rid is None else (rid[i_all] == rid[j_all])   # region_id severing
            ei.append(i_all[keep])
            ej.append(j_all[keep])
            ew.append(np.full(ei[-1].size, w, dtype="float64"))
        edge_i = np.concatenate(ei) if ei else np.empty(0, dtype=np.intp)
        edge_j = np.concatenate(ej) if ej else np.empty(0, dtype=np.intp)
        edge_w = np.concatenate(ew) if ew else np.empty(0, dtype="float64")
        # fold every present edge's weight onto BOTH its endpoints' diagonals (absent edges simply
        # never appear -- that omission IS the reflecting boundary condition)
        diag = (self.kappa ** 2
                + np.bincount(edge_i, edge_w, minlength=n)
                + np.bincount(edge_j, edge_w, minlength=n))
        cell = np.arange(n)
        rows = np.concatenate([edge_i, edge_j, cell])
        cols = np.concatenate([edge_j, edge_i, cell])
        data = np.concatenate([-edge_w, -edge_w, diag])
        k = sparse.coo_matrix((data, (rows, cols)), shape=(n, n)).tocsr()
        return (self.tau * np.sqrt(self._h)) * k

    def precision(self) -> "sparse.csr_matrix":
        r"""The precision :math:`Q=A^\top A=\tau^2h\tilde K^2`, a **13-point** stencil -- on demand.

        Offsets (0,0), (+-1,0), (0,+-1), (+-2,0), (0,+-2), (+-1,+-1); measured nnz/row 12.52 -> 12.94
        as n goes 1681 -> 103041 (boundary rows have fewer), so ~1.6 GB at n = 1e7 where a dense
        covariance would be 800 TB. Finite-volume derivation: the cell-averaged white noise has
        covariance :math:`h^{-1}I`, so :math:`\tau\tilde Kx=w` gives
        :math:`Q=\tau^2h\tilde K^\top\tilde K`; equivalently FEM with a **lumped** mass matrix
        (approximation 3 -- with the consistent mass matrix :math:`M^{-1}` is dense and there is no
        sparse Q at all).

        **Materialized on demand and not cached: do not build this to solve with it.** ``Q`` is only
        needed for structural tests and for the dense cross-check; every solve factors ``A`` instead
        (:meth:`solve`). Under ``standardize=True`` this returns the standardized
        :math:`\tilde Q=D^{-1}QD^{-1}`, which is SPD and has exactly the same sparsity pattern but is
        no longer :math:`A^\top A`.
        """
        a = self.operator()
        q = (a.T @ a).tocsr()
        if self.standardize:
            inv_d = sparse.diags(1.0 / self._scale())
            q = (inv_d @ q @ inv_d).tocsr()
        return q

    # -- solves ------------------------------------------------------------------------------------

    def _factor(self):
        """Cached solver for ``A x = b``. Never for ``Q`` -- see :meth:`solve`."""
        if "factor" not in self._cache:
            a = self.operator()
            use_splu = self.solver == "splu" or (self.solver == "auto" and self.n <= _SPLU_MAX_N)
            if use_splu:
                lu = sparse_linalg.splu(a.tocsc(), permc_spec="COLAMD")
                self._cache["factor"] = lu.solve
            else:
                self._cache["factor"] = self._make_cg_solver(a)
        return self._cache["factor"]

    @staticmethod
    def _make_cg_solver(a: "sparse.csr_matrix"):
        """Jacobi-preconditioned CG on the well-conditioned 5-point ``A`` (O(n) memory)."""
        d = a.diagonal()
        pre = sparse_linalg.LinearOperator(a.shape, matvec=lambda v: v / d)

        def solve_cg(b: NDArray[np.float64]) -> NDArray[np.float64]:
            b2 = b if b.ndim > 1 else b[:, None]
            out = np.empty_like(b2)
            for k in range(b2.shape[1]):
                try:
                    x, info = sparse_linalg.cg(a, b2[:, k], rtol=_CG_RTOL, atol=0.0, M=pre)
                except TypeError:                     # scipy < 1.12 spells it `tol`
                    x, info = sparse_linalg.cg(a, b2[:, k], tol=_CG_RTOL, atol=0.0, M=pre)
                if info != 0:
                    warnings.warn(f"CG on the 5-point operator did not converge (info={info}); "
                                  "results may be inaccurate. Try solver='splu'.",
                                  UserWarning, stacklevel=3)
                out[:, k] = x
            return out if b.ndim > 1 else out[:, 0]

        return solve_cg

    def _apply_ainv(self, b: NDArray[np.float64]) -> NDArray[np.float64]:
        """One solve through the 5-point square root: ``A^-1 b``."""
        return self._factor()(np.ascontiguousarray(b, dtype="float64"))

    def solve(self, rhs: ArrayLike) -> NDArray[np.float64]:
        r"""Apply the covariance without forming it: :math:`B\,\mathrm{rhs}=Q^{-1}\mathrm{rhs}`.

        ``rhs`` is ``(n,)`` or ``(n, m)``; the return has the same shape. **Two solves through the
        5-point** :math:`A`, never one through the 13-point :math:`Q`:

        .. math::  Q^{-1}v = A^{-1}(A^{-1}v) = \frac{1}{\tau^2h}\tilde K^{-1}(\tilde K^{-1}v).

        This is not a stylistic preference (issue #163, approximation 9).
        :math:`\mathrm{cond}(Q)=\mathrm{cond}(\tilde K)^2\approx64/(\kappa\,dx)^4`, which at the repo's
        :math:`\kappa\,dx=0.032` is 6e7 against 7.9e3 -- **~89x the CG iterations, and a 13-point
        rather than 5-point factorization**. Measured for ``splu`` on the 5-point operator at
        dx = 0.09 km, L = 4 km: 0.14 / 0.83 / 5.46 s to factor and 0.006 / 0.032 / 0.147 s per solve at
        n = 4e4 / 1.6e5 / 6.4e5, with fill 86.8 -> 134.1 nnz/row (O(log n), nested-dissection optimal)
        and 0.04 / 0.21 / 1.03 GB of factor. Above n ~ 2e6 ``solver="auto"`` falls back to
        Jacobi-preconditioned CG: O(n) memory, O(1/(kappa*min(dx,dy))) iterations.

        Under ``standardize=True`` this applies the standardized covariance
        :math:`\tilde B = DBD` -- still only two ``A`` solves, so nothing is lost.
        """
        b = np.asarray(rhs, dtype="float64")
        one_d = b.ndim == 1
        if b.ndim not in (1, 2) or b.shape[0] != self.n:
            raise ValueError(f"rhs must have shape (n,) or (n, m) with n={self.n}, got {b.shape}")
        if self.standardize:
            s = self._scale()
            b = b * (s if one_d else s[:, None])
        out = self._apply_ainv(self._apply_ainv(b))
        if self.standardize:
            s = self._scale()
            out = out * (s if one_d else s[:, None])
        return out

    def sample(self, n_samples: int, rng: np.random.Generator | int | None = None
               ) -> NDArray[np.float64]:
        r"""``n_samples`` **exact** draws from the prior, ``(n_samples, n)``.

        :math:`x=A^{-1}z`, :math:`z\sim\mathcal N(0,I)` -- **one** solve each, and exact (not
        approximate) because :math:`A` is a symmetric square root of :math:`Q`:
        :math:`\mathrm{Cov}(x)=A^{-1}A^{-\top}=Q^{-1}=B`. Having an exact square root in one solve is
        the decisive practical reason :math:`\alpha=2` was chosen (issue #163); it is also the
        machinery behind :meth:`marginal_var`'s default estimator.
        """
        gen = rng if isinstance(rng, np.random.Generator) else np.random.default_rng(rng)
        k = int(n_samples)
        if k < 1:
            raise ValueError(f"n_samples must be >= 1, got {n_samples!r}")
        x = self._apply_ainv(gen.standard_normal((self.n, k)))
        if self.standardize:
            x = x * self._scale()[:, None]
        return np.ascontiguousarray(x.T)

    # -- diag(B) -----------------------------------------------------------------------------------

    def marginal_var(self, method: str = "mc", n_samples: int = 512,
                     rng: np.random.Generator | int | None = None) -> NDArray[np.float64]:
        r"""``diag(B)`` -- the prior variance per cell, i.e. :func:`resolution_precision`'s denominator.

        This is the one genuinely awkward quantity in the precision formulation: the covariance is
        never formed, and its diagonal costs ``n`` solves to get exactly.

        **What does not work, so that nobody re-derives it.** Naive Hutchinson
        :math:`\mathrm{diag}(Q^{-1})\approx K^{-1}\sum_k z_k\odot(Q^{-1}z_k)` has per-cell variance
        :math:`K^{-1}\sum_{j\neq i}B_{ij}^2`, i.e. relative variance proportional to (cells per
        correlation area)/K -- ~1e4 cells per correlation area at 90 m with L = 4 km, hopeless. Colored
        probing is worse: it needs a stride of >~ 4 practical ranges, i.e. ~1.3e5 solves.

        **What works (``method="mc"``, the default): the split (square-root) estimator.** Since
        :math:`A` is symmetric, :math:`B_{ii}=\sum_j(A^{-1})_{ij}^2=\mathbb E[(A^{-1}z)_i^2]`, so
        averaging the squares of the exact prior draws of :meth:`sample` is **unbiased** with per-cell
        relative standard deviation :math:`\sqrt{2/K}` -- **independent of n and of the correlation
        length** (measured rms 0.210 / 0.090 / 0.043 at K = 64 / 256 / 1024 against a predicted
        0.177 / 0.088 / 0.044). It is then variance-reduced by an **exact periodic control variate**:
        on the torus of the same shape the operator is circulant with symbol
        :math:`\lambda_k=\kappa^2+\tfrac{4}{dy^2}\sin^2(\pi k_1/n_y)+\tfrac{4}{dx^2}\sin^2(\pi k_2/n_x)`
        and constant diagonal :math:`(\tau^2hn_yn_x)^{-1}\sum_k\lambda_k^{-2}` known in closed form, so
        with the **same** :math:`z_k` driving both operators
        :math:`\hat B_{ii}=B^\text{per}_{ii}+K^{-1}\sum_k(x_{k,i}^2-x^\text{per\,2}_{k,i})` is still
        unbiased and the difference -- hence the variance -- collapses exactly where the correction is
        zero. Measured rms error 0.063 / 0.0286 / 0.0100 at K = 64 / 256 / 1024 against 0.194 / 0.096 /
        0.0425 plain: 3-4x globally, and **1e-4 (four orders) in the deep interior**, with the residual
        concentrated near boundaries and divides where the correction is real.

        **It is unbiased but stochastic: the result depends on the seed.** Pass an explicit ``rng`` and
        record it (issue #163, approximation 8). ``n_samples=512`` gives ~2% rms, ~6% worst-case near a
        divide.

        ``method="analytic"`` returns ``sigma**2`` everywhere -- O(1), and **exact only >= 1 practical
        range from every boundary and every severed edge**; it is wrong by up to x3.8 (corner) or
        x25-395 (small ``region_id`` regions) otherwise, so it warns -- **except under
        ``standardize=True``, where sigma^2 everywhere is correct by construction and the warning would
        be misleading** -- and is legitimate only on a padded domain with no ``region_id``.
        ``method="exact"`` does the ``n`` solves (guarded at
        n <= 4096) and is the **verification reference, not a production path**.

        Under ``standardize=True`` the answer is ``sigma**2`` by construction for every method (that is
        what the standardization forces); note the standardization inherits the Monte-Carlo error of
        the ``diag(B)`` it was built from when n > 4096, so the *true* diagonal of the standardized
        covariance is ``sigma**2`` only to that accuracy.
        """
        if method not in ("mc", "analytic", "exact"):
            raise ValueError(f"method must be one of 'mc', 'analytic', 'exact', got {method!r}")
        if method == "analytic" and not self.standardize:        # under standardize it IS sigma^2
            warnings.warn(
                "marginal_var(method='analytic') returns sigma^2 everywhere: it ignores the "
                "reflecting-boundary inflation (x1.95 straight edge, x3.83 corner, +0.9% at one "
                "practical range) and the 4*pi/(kappa^2 A) small-region inflation. It is only "
                "legitimate >= 1 practical range from every boundary and every severed edge.",
                UserWarning, stacklevel=2)
        if self.standardize:
            return np.full(self.n, float(self.sigma) ** 2)
        return self._raw_marginal_var(method, n_samples, rng)

    def _raw_marginal_var(self, method: str, n_samples: int,
                          rng: np.random.Generator | int | None) -> NDArray[np.float64]:
        """``diag(B)`` of the UNstandardized covariance (the standardization is built from it)."""
        if method == "analytic":
            return np.full(self.n, float(self.sigma) ** 2)
        if method == "exact":
            if self.n > _EXACT_MAX_N:
                raise ValueError(
                    f"marginal_var(method='exact') needs n solves and an (n, n) intermediate; "
                    f"n={self.n} exceeds the {_EXACT_MAX_N} guard. It is the verification reference, "
                    "not a production path -- use method='mc'.")
            y = self._apply_ainv(np.eye(self.n))                 # A^-1, and B = A^-1 A^-1 (A sym)
            return np.einsum("ij,ij->i", y, y)
        return self._marginal_var_mc(int(n_samples), rng)

    def _periodic_symbol(self) -> NDArray[np.float64]:
        r"""Circulant eigenvalues :math:`\lambda_k` of the periodic 5-point operator, ``(ny, nx)``."""
        ny, nx = int(self.shape[0]), int(self.shape[1])
        sy = (4.0 / self._dy ** 2) * np.sin(np.pi * np.arange(ny) / ny) ** 2
        sx = (4.0 / float(self.dx_km) ** 2) * np.sin(np.pi * np.arange(nx) / nx) ** 2
        return self.kappa ** 2 + sy[:, None] + sx[None, :]

    def _marginal_var_mc(self, n_samples: int, rng: np.random.Generator | int | None
                         ) -> NDArray[np.float64]:
        if n_samples < 1:
            raise ValueError(f"n_samples must be >= 1, got {n_samples!r}")
        gen = rng if isinstance(rng, np.random.Generator) else np.random.default_rng(rng)
        ny, nx = int(self.shape[0]), int(self.shape[1])
        lam = self._periodic_symbol()
        scale_per = 1.0 / (self.tau * np.sqrt(self._h))
        b_per = float(np.sum(lam ** -2.0)) / (self.tau ** 2 * self._h * ny * nx)
        acc = np.zeros(self.n)
        chunk = max(1, min(n_samples, int(_MC_CHUNK_BYTES // (8 * max(self.n, 1)))))
        done = 0
        while done < n_samples:
            k = min(chunk, n_samples - done)
            z = gen.standard_normal((self.n, k))
            x = self._apply_ainv(z)                              # exact draws from THIS operator
            zp = np.ascontiguousarray(z.T).reshape(k, ny, nx)    # same z drives the torus: the
            xp = np.fft.ifft2(np.fft.fft2(zp, axes=(1, 2)) / lam, axes=(1, 2)).real  # control variate
            xp = xp.reshape(k, self.n).T * scale_per
            acc += np.einsum("ij,ij->i", x, x) - np.einsum("ij,ij->i", xp, xp)
            done += k
        est = b_per + acc / n_samples
        if np.any(est <= 0.0):
            floor = 1e-12 * float(self.sigma) ** 2
            warnings.warn(
                f"{int((est <= 0.0).sum())} cells got a non-positive Monte-Carlo variance estimate "
                f"(n_samples={n_samples}); clipped to {floor:.3g}. Increase n_samples.",
                UserWarning, stacklevel=3)
            est = np.maximum(est, floor)
        return est

    def _scale(self) -> NDArray[np.float64]:
        r"""``sigma/sqrt(diag(B))`` -- the diagonal congruence behind ``standardize=True``.

        :math:`\tilde B=DBD` with :math:`D=\mathrm{diag}(\sigma/\sqrt{B_{ii}})` forces
        :math:`\mathrm{diag}(\tilde B)=\sigma^2` exactly while leaving every correlation and every
        structural zero untouched. Because the class is frozen (and ``solve`` must not change answer
        between calls) the underlying ``diag(B)`` is computed **once, deterministically, and cached**:
        exactly when n <= 4096, otherwise by Monte Carlo with ``n_samples=512`` and the fixed seed
        ``_STANDARDIZE_SEED`` -- documented rather than seeded from entropy so a standardized prior is
        reproducible. Call :meth:`marginal_var` yourself if you need control over that estimate.
        """
        if "scale" not in self._cache:
            if self.n <= _EXACT_MAX_N:
                dvar = self._raw_marginal_var("exact", 0, None)
            else:
                dvar = self._raw_marginal_var("mc", _STANDARDIZE_SAMPLES,
                                              np.random.default_rng(_STANDARDIZE_SEED))
            self._cache["scale"] = float(self.sigma) / np.sqrt(dvar)
        return self._cache["scale"]

    def dense_cov(self) -> NDArray[np.float64]:
        """``inv(Q)`` as a dense ``(n, n)`` array. **Tests and small-grid cross-checks only.**

        Guarded at n <= 4096 (a 4096^2 float64 array is already 134 MB; the whole point of this class
        is that this object does not exist at scale -- 800 TB at n = 1e7). Its purpose is the mandatory
        verification of issue #163: feeding this to the **existing dense** :func:`resolution` /
        :func:`blue_update` must reproduce :func:`resolution_precision` / :func:`blue_update_precision`
        to ~1e-14, because both sides describe the same covariance.
        """
        if self.n > _EXACT_MAX_N:
            raise ValueError(
                f"dense_cov() materializes an (n, n) array; n={self.n} exceeds the {_EXACT_MAX_N} "
                f"guard ({self.n ** 2 * 8 / 1e9:.3g} GB). It exists for verification only -- use "
                "solve() / resolution_precision(), which never form B.")
        return np.linalg.inv(self.precision().toarray())


# --- estimator entry points: the dense formulas with `CG` -> `X = Q^-1 G^T` -----------------------

def _obs_operator(G) -> tuple[object, int]:
    """Accept a dense ``(n_obs, n_cell)`` array or any ``scipy.sparse`` matrix; return ``(G, n_obs)``."""
    if sparse.issparse(G):
        return G, int(G.shape[0])
    g = np.atleast_2d(np.asarray(G, dtype="float64"))
    return g, (0 if g.size == 0 else int(g.shape[0]))


def _prior_var(prior: SparseMaternPrior, var_prior: ArrayLike | None) -> NDArray[np.float64]:
    if var_prior is None:
        return prior.marginal_var()
    v = np.asarray(var_prior, dtype="float64").ravel()
    if v.size != prior.n:
        raise ValueError(f"var_prior has {v.size} cells, expected n={prior.n}")
    return v


def _cross_covariance(prior: SparseMaternPrior, G, n_obs: int) -> NDArray[np.float64]:
    r""":math:`X=BG^\top=Q^{-1}G^\top`, ``(n, n_obs)`` -- the ``CG`` of the dense path, formed by a
    sparse solve instead of a dense product. **This array is dense**: that is why issue #163's O(n)
    claim is about the prior representation and not the estimator."""
    one = 8.0 * prior.n * n_obs                       # ONE (n, n_obs) array...
    need = _X_PEAK_MULT * one                         # ...but this many are live while X is formed
    if need > _X_MAX_BYTES:
        raise ValueError(
            f"X = Q^-1 G^T is dense (n={prior.n}, n_obs={n_obs}) = {one / 1e9:.3g} GB, and forming it "
            f"holds ~{_X_PEAK_MULT} such arrays at once (the C-order G^T copy, the two nested 5-point "
            "solves, and the standardize=True rescale), i.e. a peak of "
            f"{need / 1e9:.3g} GB over the {_X_MAX_BYTES / 1e9:.3g} GB budget. The PRIOR is O(n) "
            "(13 nnz/row); this product is not. Chunk over observation columns, or coarsen the "
            "analysis grid.")
    gt = G.T.toarray() if sparse.issparse(G) else np.asarray(G, dtype="float64").T
    return prior.solve(np.ascontiguousarray(gt))


def resolution_precision(prior: SparseMaternPrior, G, noise_var: ArrayLike,
                         var_prior: ArrayLike | None = None
                         ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    r"""Per-cell resolution and posterior variance, computed **through the precision** (issue #163).

    The sparse counterpart of :func:`resolution`, and deliberately the *same formulas*: the dense path
    builds ``CG = C @ G.T``; this builds the same object :math:`X=BG^\top=Q^{-1}G^\top` by a sparse
    solve and never forms ``B``. Everything after that is character-for-character the dense code
    (including its ``np.clip(reduction, 0, var_prior)`` guard), which is what makes the two exactly
    cross-checkable: feeding ``prior.dense_cov()`` to :func:`resolution` reproduces this to ~5e-14.

    ``G`` is ``(n_obs, n_cell)``, dense or ``scipy.sparse``; ``noise_var`` is a scalar or ``(n_obs,)``;
    empty ``G`` returns zero resolution, as in the dense path. ``var_prior`` is ``diag(B)``: pass a
    :meth:`SparseMaternPrior.marginal_var` computed **once** and reuse it across several ``G`` sets
    (the common case). Omitting it runs a fresh, **unseeded** Monte-Carlo estimate on every call, so
    two calls will not agree to the last digit; pass an explicitly seeded one for a reproducible
    figure.

    **A Monte-Carlo ``var_prior``'s ~2% per-cell error does NOT cancel in the ratio.** Resolution is a
    ratio, but not of the *same* quantity twice: the numerator ``reduction`` is built from the exact
    :math:`X=Q^{-1}G^\top` (a sparse solve, no sampling), while only the denominator is the estimate, so
    a 2% low ``diag(B)`` gives a ~2% high resolution one for one. The ``np.clip(reduction, 0, vp)``
    guard then saturates that error **one-sidedly**: wherever the estimate falls below the true prior
    variance at a well-observed cell, ``res`` is pinned to exactly 1.0 (and ``var_post`` to 0). Where
    resolution near 1 is what the figure turns on, pass
    ``var_prior=prior.marginal_var(method="exact")`` (exact, guarded at n <= 4096) or raise
    ``n_samples``.

    Cost: ``2*n_obs`` solves for ``X``, then O(n_obs^3 + n*n_obs^2) exactly as in the dense path. The
    memory that binds is ``X`` itself, ``(n, n_obs)`` dense.
    """
    g, n_obs = _obs_operator(G)
    vp = _prior_var(prior, var_prior)
    if n_obs == 0:
        return np.zeros_like(vp), vp.copy()
    nv = np.broadcast_to(np.asarray(noise_var, dtype="float64"), (n_obs,))
    x = _cross_covariance(prior, g, n_obs)            # (n_cell, n_obs), the dense path's `CG`
    m = g @ x + np.diag(nv)                           # (n_obs, n_obs): obs-space covariance
    reduction = np.einsum("ij,ji->i", x, np.linalg.solve(m, x.T))
    reduction = np.clip(reduction, 0.0, vp)           # numerical guard
    var_post = vp - reduction
    res = np.where(vp > 0, reduction / vp, 0.0)
    return res, var_post


def blue_update_precision(prior: SparseMaternPrior, G, d: ArrayLike, noise_var: ArrayLike,
                          prior_mean: ArrayLike = 0.0, var_prior: ArrayLike | None = None
                          ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    r"""BLUE analysis mean and posterior variance through the precision -- see :func:`blue_update`.

    Identical estimator, identical validation, identical innovation semantics (``d - G m_b`` evaluated
    at each datum's own support); only :math:`BG^\top` is obtained by a sparse solve instead of a dense
    product, so the ``(n, n)`` covariance is never formed. ``G`` may be ``scipy.sparse``; ``var_prior``
    lets a once-computed ``diag(B)`` be reused (issue #163).
    """
    g, n_obs = _obs_operator(G)
    vp = _prior_var(prior, var_prior)
    mb = np.broadcast_to(np.asarray(prior_mean, dtype="float64"), (prior.n,)).astype("float64")
    if n_obs == 0:
        return mb.copy(), vp.copy()
    dd = np.asarray(d, dtype="float64").ravel()
    if dd.size != n_obs:                              # guard against silent broadcasting of a bad d
        raise ValueError(f"d has length {dd.size}, expected n_obs={n_obs}")
    nv = np.asarray(noise_var, dtype="float64")
    if nv.ndim != 0 and nv.size != n_obs:
        raise ValueError(f"noise_var must be scalar or length n_obs={n_obs}, got {nv.size}")
    nv = np.broadcast_to(nv, (n_obs,))
    x = _cross_covariance(prior, g, n_obs)            # (n_cell, n_obs)
    m = g @ x + np.diag(nv)                           # (n_obs, n_obs)
    innov = dd - g @ mb                               # data minus model-predicted data
    m_a = mb + x @ np.linalg.solve(m, innov)
    reduction = np.einsum("ij,ji->i", x, np.linalg.solve(m, x.T))
    reduction = np.clip(reduction, 0.0, vp)           # numerical guard: 0 <= reduction <= prior
    return m_a, vp - reduction
