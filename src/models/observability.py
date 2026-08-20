r"""Observability and information gain of the sensor networks (linear-Gaussian design).

This answers a question the sensitivity map (:mod:`src.models.dvv_sensitivity`) raises but does not
close: given *where* each instrument is sensitive, **how much does it actually reduce the uncertainty
of the state — the water-table-head anomaly and the soil-moisture anomaly — and where?**

## What the state is, precisely

The state field :math:`m(x)` carried here is an **anomaly / residual**, not an absolute level. For
groundwater it is the water-table-head anomaly :math:`\Delta h_{wt}` about the deterministic baseline
(the observation-anchored RF/HAND surface), not the absolute depth to water. That distinction is not
cosmetic: absolute DTW is :math:`D = z_s - h_{wt}`, so it inherits the whole deterministic
topographic and hydrogeologic structure of the land surface and is emphatically **not** a stationary
Gaussian Matérn random field over Puget Sound. The stationary Matérn prior below describes the
*residual* about that baseline, which is the standard drift-plus-residual decomposition of the
groundwater geostatistics literature (Varouchakis et al. 2019, 2022).

Because :math:`z_s` is time-invariant, :math:`\Delta D = -\Delta h_{wt}` exactly, so the DTW anomaly
and the head anomaly are one random field up to sign and share one covariance. They must never be
given separate :math:`(\sigma, L, \nu)` configurations — see :mod:`src.models.hydro_state`.

Distinct from both is the hydraulic head :math:`H = z + p/(\rho_w g)` measured by a **screened**
piezometer, which equals :math:`h_{wt}` only when the screen brackets the phreatic surface of an
unconfined aquifer (:mod:`src.features.well_hydrostratigraphy`,
:func:`water_table_point_footprint`).

## The framing

Each observation is a **linear functional** of the state,

.. math::  d_i = g_i^\top m + \varepsilon_i, \qquad \varepsilon_i \sim \mathcal N(0, \sigma_{d,i}^2),

where :math:`g_i` is the instrument's footprint (a weighting that sums to one, so every sensor observes
a weighted *average* of the state):

- a **well** or a **SNOTEL** site is a point sensor — :math:`g_i` is a narrow blob at the location;
- a **dv/v** station pair or autocorrelation is a *volume* sensor — :math:`g_i` is the coda kernel.

The states are observed by *different* instruments, and that separation is the whole point: the **deep
(low-frequency) dv/v band and the wells constrain the water table**; the **shallow (high-frequency)
dv/v band and SNOTEL constrain soil moisture**. dv/v is the only one of the three that is a *volume*
measurement, so it is the only one that fills the space *between* the point sensors. dv/v is an
**observation operator on the hydrologic state**, not a state with its own spatial prior: its
predicted covariance follows from the hydrologic prior pushed through :math:`G` plus observation
error, and the scalar :math:`k_{sat}\Delta h` / :math:`S_\theta\Delta\theta` gains are a local
linearization of a nonlinear, hysteretic petrophysical chain (issue #198), not first-principles
physics.

## What is computed

For a set of observations with operator matrix :math:`G` (rows :math:`g_i^\top`) and noise
:math:`C_d`, the Gaussian posterior covariance is

.. math::  C_\text{post} = C - C G^\top (G C G^\top + C_d)^{-1} G C .

Most of what follows is a **diagonal** of this, computed in observation space (an
:math:`n_\text{obs}\times n_\text{obs}` solve, not an :math:`n_\text{cell}` one):

- **variance-reduction ratio** :math:`R(x) = 1 - C_\text{post}(x,x)/C(x,x) \in [0,1]`
  (:func:`variance_reduction_ratio`, and its backward-compatible alias :func:`resolution`) — the
  fraction of the prior variance the network removes at each cell. 1 = fully constrained by data,
  0 = the model is on its own.
- **information gain** :math:`I(x) = \tfrac12 \ln\!\big(C(x,x)/C_\text{post}(x,x)\big)` nats — the
  local Kullback–Leibler gain, additive and unbounded, so a cell pinned by several sensors reads as
  more informed than one grazed by one.
- **marginal gain** of a sensor set *given* another: :math:`R(A\cup B) - R(B)` — where a network adds
  information the others do not already provide. This is the map that says *where dv/v is worth its
  cost*.

.. important::
   **Variance reduction is not spatial resolution.** :math:`R(x)` says how much of the prior variance
   at cell :math:`x` is removed; it says nothing about *which* cells the estimate at :math:`x` is
   actually averaging over. A single 8 km-footprint dv/v datum can drive :math:`R` high at a 90 m cell
   while the estimate there is a smooth average over kilometres. The quantity that answers the
   resolving-power question is a row of the **Bayesian resolution (averaging-kernel) operator**
   :math:`A = C G^\top (G C G^\top + C_d)^{-1} G`, whose row :math:`j` gives
   :math:`\partial \hat m_j / \partial m` — see :func:`averaging_kernel`,
   :func:`resolution_width_km`, and :func:`degrees_of_freedom_for_signal`. The function name
   ``resolution`` is kept for backward compatibility only; the quantity it returns is the
   variance-reduction ratio.

:math:`R` is a **ratio**, so it is independent of the absolute prior variance :math:`\sigma^2`; only
the correlation length, the smoothness, and the noise-to-prior ratio matter.

## Prior hyperparameters are calibratable, not measured constants

:math:`\sigma`, :math:`L` and :math:`\nu` are **prior hyperparameters** informed by physics and
literature, to be calibrated and diagnosed against the twin's out-of-fold residuals — not physical
constants. See :data:`PRIOR_HYPERPARAMETERS` for the per-state values in use and their status, and
``scripts/calibrate_spatial_prior.py`` for the residual-based profile-likelihood/CV experiment that
is meant to replace them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray


_SQRT3 = 3.0 ** 0.5
_SQRT5 = 5.0 ** 0.5

#: The range convention this module uses, stated once so every artifact can record it verbatim.
#: :math:`\kappa = \sqrt{2\nu}/L`, i.e. the argument of the Bessel function is
#: :math:`\sqrt{2\nu}\,r/L`. Other conventions in wide use (notably Lindgren et al. 2011's
#: :math:`\sqrt{8\nu}` "practical range") give a DIFFERENT distance for the same number.
RANGE_CONVENTION = "sqrt(2*nu)*r/L"


def matern_correlation(dist_km: ArrayLike, length_km: float, nu: float = 1.5) -> NDArray[np.float64]:
    r"""Whittle-Matérn correlation at separation ``dist_km``, range ``length_km``, smoothness ``nu``.

    .. math::
        \rho_\nu(r) = \frac{2^{1-\nu}}{\Gamma(\nu)}
                      \left(\frac{\sqrt{2\nu}\,r}{L}\right)^{\!\nu}
                      K_\nu\!\left(\frac{\sqrt{2\nu}\,r}{L}\right)

    **Convention (:data:`RANGE_CONVENTION`).** The Bessel argument is :math:`\sqrt{2\nu}\,r/L`.
    Under this convention and *only* under it:

    - :math:`\nu = 1/2` gives :math:`\rho(r) = e^{-r/L}` — the plain exponential/OU form, because
      :math:`\sqrt{2\nu} = 1` exactly. (It is **not** :math:`e^{-\sqrt{2}\,r/L}`; that error appeared
      in an earlier version of the assimilation chapter and is corrected there.)
    - :math:`\nu = 3/2` gives :math:`(1+\sqrt{3}r/L)e^{-\sqrt{3}r/L}`;
    - :math:`\nu = 5/2` gives :math:`(1+\sqrt{5}r/L+\tfrac53 r^2/L^2)e^{-\sqrt{5}r/L}`.

    A range quoted under a different convention is a different distance. Use
    :func:`convert_matern_range` before comparing with a published value.

    **Regularity.** A Matérn field is :math:`\lceil\nu\rceil - 1` times mean-square differentiable, so
    :math:`\nu = 1/2` is continuous but **nowhere** mean-square differentiable, :math:`\nu = 3/2` is
    once differentiable and no more, and :math:`\nu\to\infty` recovers the :math:`C^\infty`
    squared-exponential. Issue #163: the squared-exponential prior used everywhere before this was
    that :math:`\nu\to\infty` limit, which imposes an implausibly smooth field on a terrain-driven
    state.

    Half-integer :math:`\nu` uses the elementary closed form; any other positive :math:`\nu` (e.g. the
    1.0 and 2.0 candidates of the calibration grid) goes through
    :func:`scipy.special.kv`. Both branches agree to floating-point at the half-integers.

    ``nu`` is a **hyperparameter to be calibrated**, not a physical constant; see
    :data:`PRIOR_HYPERPARAMETERS`.
    """
    if not (np.isfinite(length_km) and length_km > 0):
        raise ValueError(f"length_km must be a positive finite number, got {length_km!r}")
    if not (np.isfinite(nu) and nu > 0):
        raise ValueError(f"nu must be a positive finite number, got {nu!r}")
    d = np.asarray(dist_km, dtype="float64") / length_km
    x = (2.0 * nu) ** 0.5 * d
    if nu == 0.5:
        return np.exp(-x)
    if nu == 1.5:
        return (1.0 + x) * np.exp(-x)
    if nu == 2.5:
        return (1.0 + x + x ** 2 / 3.0) * np.exp(-x)
    # general nu: 2^(1-nu)/Gamma(nu) * x^nu * K_nu(x), with the removable singularity at x=0 set to 1
    from scipy.special import gammaln, kv                 # local import: scipy only needed off the fast path

    out = np.ones_like(x, dtype="float64") if np.ndim(x) else np.float64(1.0)
    pos = np.asarray(x) > 0
    if np.any(pos):
        xp = np.asarray(x)[pos] if np.ndim(x) else np.asarray([x])
        val = np.exp((1.0 - nu) * np.log(2.0) - gammaln(nu) + nu * np.log(xp)) * kv(nu, xp)
        val = np.nan_to_num(val, nan=0.0, posinf=0.0, neginf=0.0)   # K_nu underflows to 0 at large x
        if np.ndim(x):
            out = np.asarray(out)
            out[pos] = val
        else:
            out = np.float64(val[0])
    return np.clip(out, 0.0, 1.0)


def convert_matern_range(length_km: float, nu: float, to: str = "lindgren") -> float:
    r"""Convert a range from this module's :math:`\sqrt{2\nu}` convention to another.

    ``to="lindgren"`` returns the @lindgren2011explicit *practical range* :math:`\rho`, defined so the
    Bessel argument is :math:`\sqrt{8\nu}\,r/\rho`; matching the two arguments gives
    :math:`\rho = 2L`. ``to="kappa"`` returns the SPDE inverse-range
    :math:`\kappa = \sqrt{2\nu}/L` (units km\ :sup:`-1`), the parameter that actually appears in the
    operator :math:`(\kappa^2-\Delta)^{\alpha/2}`.

    Reporting a range without its convention is the single easiest way to make two studies look like
    they disagree when they do not, which is why every calibration artifact records
    :data:`RANGE_CONVENTION` verbatim.
    """
    if not (np.isfinite(length_km) and length_km > 0):
        raise ValueError(f"length_km must be a positive finite number, got {length_km!r}")
    if to == "lindgren":
        return 2.0 * float(length_km)
    if to == "kappa":
        return float((2.0 * nu) ** 0.5 / length_km)
    raise ValueError(f"to must be 'lindgren' or 'kappa', got {to!r}")


def microergodic_parameter(sigma: float, length_km: float, nu: float) -> float:
    r"""The consistently-estimable Matérn combination, **written in this module's convention**.

    Under fixed-domain (infill) asymptotics @zhang2004inconsistent proves that :math:`\sigma^2` and the
    range are *not* separately consistently estimable at any sampling density; for known :math:`\nu`
    what is consistently estimable is the microergodic combination

    .. math::  \sigma^2 \kappa^{2\nu}, \qquad \kappa = \sqrt{2\nu}/L .

    Writing it as a bare :math:`\sigma^2/L^{2\nu}` is convention-dependent and drops the
    :math:`(2\nu)^{\nu}` factor — harmless when comparing two fits at the *same* :math:`\nu`, wrong as
    soon as :math:`\nu` varies, which is exactly what the calibration experiment does. This function
    is the convention-aware form; its value also has :math:`\nu`-dependent units
    (m\ :sup:`2` km\ :sup:`-2ν`), so it is comparable across fits only at fixed :math:`\nu`.
    """
    return float(sigma ** 2 * convert_matern_range(length_km, nu, to="kappa") ** (2.0 * nu))


@dataclass(frozen=True)
class GaussianPrior:
    r"""A stationary prior on the state **anomaly/residual**: variance ``sigma^2``, Matérn ``length_km``.

    This is a prior on :math:`\delta h` in :math:`h_{wt} = h_{\text{baseline}} + \delta h` (or the
    equivalent soil-moisture anomaly), **not** on the absolute water-table/DTW landscape — see the
    module docstring.

    ``nu`` is the Matérn smoothness (any positive value; default 1.5). The default exists so old call
    sites keep working, but **groundwater and soil moisture must not silently share it**: pass ``nu``
    explicitly, or build the prior with :func:`prior_for_state`, which reads the per-state values and
    their calibration status from :data:`PRIOR_HYPERPARAMETERS`.

    ``region_id`` (aliased ``barrier_id``), if given -- one label per cell -- forces correlation to
    zero between cells with different labels, regardless of Euclidean distance. Its scientific status
    matters and has been overstated before:

    - It **is** a hydrographic **localization / barrier approximation**. It stops a stationary
      isotropic kernel from letting a ridge cell and a valley cell 90 m apart correlate as strongly as
      two valley cells, and it is a cheap, exact anti-leakage device (issue #163).
    - It is **not** a hydrogeologic truth. A surface drainage divide is not necessarily a groundwater
      divide: groundwater crosses topographic basin boundaries wherever aquifer geometry and hydraulic
      gradients say it does, and whether the water table follows topography at all is itself
      conditional [@haitjema2005subdued]. A hard zero is an infinitely strong statement about a
      boundary that is usually only partial.
    - Preferred labels are therefore **hydrogeologic domains**
      (:mod:`src.features.hydrogeologic_domains`) rather than drainage basins, and the longer-term fix
      is a *soft* connectivity/barrier weight rather than a 0/1 mask (issues #163, #188, #192).

    It does not by itself solve the separate scalability problem of a dense ``(n, n)`` ``C`` at full
    90 m domain scale, which the twin avoids by solving on a coarsened assimilation grid
    (`notebooks/make_twin_gif.py`); an operator-form representation is issue #154/#163 work, and the
    statistical model must be chosen independently of which backend carries it.
    """

    sigma: float
    length_km: float
    nu: float = 1.5
    region_id: NDArray[np.int64] | None = None
    barrier_id: NDArray[np.int64] | None = None

    def __post_init__(self) -> None:
        # ``barrier_id`` is the semantically honest name (a localization barrier, not a physical
        # region); ``region_id`` is kept because every existing call site uses it. Accept either,
        # store one, and refuse a contradictory pair rather than silently preferring one.
        if self.barrier_id is not None and self.region_id is not None:
            if not np.array_equal(np.asarray(self.region_id), np.asarray(self.barrier_id)):
                raise ValueError("pass region_id OR barrier_id (they are aliases), not two different arrays")
        elif self.barrier_id is not None:
            object.__setattr__(self, "region_id", self.barrier_id)
        object.__setattr__(self, "barrier_id", self.region_id)

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


# --- per-state prior hyperparameters ---------------------------------------------------------------
# STATUS LABELS ARE PART OF THE SCIENCE. Every value below is a prior hyperparameter -- informed by
# physics and literature, to be calibrated from out-of-fold residuals -- not a measured constant.
# Nothing here is empirically calibrated for Puget Sound yet; `scripts/calibrate_spatial_prior.py`
# is the experiment that is meant to replace these numbers, and it writes the artifact that
# docs/twin/04-assimilation.qmd and 05-state-evaluation.qmd should cite.
#
# Why a registry at all: before this, both states were built from ONE `GaussianPrior` default, so a
# single `nu=1.5` silently governed the water table AND soil moisture. The literature does not
# support that (see below). Separating them here is a configuration change, not a numerical one --
# the values in use are unchanged, so no production output moves; only their status and their
# independence do.

#: Candidate smoothness grids for the residual-based calibration experiment (issue #192).
#: Groundwater: 1.0/1.5/2.0 as the working region, 0.5 retained as a rough comparison.
#: Soil moisture: 0.5/1.0/1.5, with 0.5-1 the literature-motivated rougher region.
NU_CANDIDATES = {
    "water_table_head_anomaly": (0.5, 1.0, 1.5, 2.0),
    "soil_moisture_anomaly": (0.5, 1.0, 1.5),
}


@dataclass(frozen=True)
class PriorHyperparameters:
    """Provisional :math:`(\\sigma, L, \\nu)` for one state, with an explicit calibration status.

    ``status`` is one of ``"working_hypothesis"`` (physically plausible, argued, not estimated),
    ``"inherited_default"`` (in use because a shared default put it there; NOT argued for this
    state), or ``"calibrated"`` (estimated from residuals, with an artifact to point at). Nothing in
    this repo is ``"calibrated"`` today.
    """

    state: str
    sigma: float
    length_km: float
    nu: float
    units: str
    status: str
    note: str
    range_convention: str = RANGE_CONVENTION

    def prior(self, region_id: NDArray[np.int64] | None = None) -> GaussianPrior:
        """Build the :class:`GaussianPrior` these hyperparameters describe."""
        return GaussianPrior(sigma=self.sigma, length_km=self.length_km, nu=self.nu,
                             region_id=region_id)


PRIOR_HYPERPARAMETERS: dict[str, PriorHyperparameters] = {
    # The water-table-head anomaly. Delta D = -Delta h_wt, so the DTW anomaly is THE SAME field up to
    # sign and deliberately has no separate entry -- adding one would be the error
    # src.models.hydro_state.assert_anomaly_covariance_identity exists to catch.
    "water_table_head_anomaly": PriorHyperparameters(
        state="water_table_head_anomaly",
        sigma=0.5, length_km=12.0, nu=1.5, units="m",
        status="working_hypothesis",
        note=(
            "nu=1.5 is a moderately smooth WORKING REGULARITY PRIOR, not a published hydrogeologic "
            "constant. The defensible argument is directional only: head is a filtered functional of "
            "log-K under steady flow, so head residuals are expected to be SMOOTHER than the "
            "material-property field, which places nu above 1/2; stream/contact breaks in slope place "
            "it below the C-infinity limit. That argument does not select 1.5 over 1.0 or 2.0. "
            "sigma and L are prior specifications; under fixed-domain asymptotics only the "
            "microergodic combination sigma^2 kappa^(2nu) is consistently estimable "
            "(@zhang2004inconsistent), and nothing here has been estimated for Puget Sound."),
    ),
    # Soil moisture. Kept at the value currently in production so this audit changes no output, but
    # the status is honest: it is inherited, not argued.
    "soil_moisture_anomaly": PriorHyperparameters(
        state="soil_moisture_anomaly",
        sigma=0.03, length_km=8.0, nu=1.5, units="m3 m-3",
        status="inherited_default",
        note=(
            "nu=1.5 here is INHERITED from the shared GaussianPrior default and is NOT supported by "
            "the soil-moisture literature, which describes rougher, strongly state-, scale-, "
            "support-, depth- and season-dependent spatial structure (@vereecken2014soilmoisture); "
            "@minasny2005matern recover low Matern smoothness (~0.25-0.50) for several measured SOIL "
            "PROPERTIES, which is evidence about Matern behaviour of soil variables, NOT a "
            "determination of nu for monthly Puget Sound soil moisture. No single literature value "
            "-- including 0.5 -- is established. Changing this default would move production "
            "products, so it is left in place and flagged: it must be set by the residual "
            "calibration, reported as a before/after scientific change, not by this audit."),
    ),
}


def prior_for_state(state: str, region_id: NDArray[np.int64] | None = None,
                    nu: float | None = None, sigma: float | None = None,
                    length_km: float | None = None) -> GaussianPrior:
    """Build the prior for a named state from :data:`PRIOR_HYPERPARAMETERS`, with optional overrides.

    Use this instead of ``GaussianPrior(sigma, L)`` so that the water table and soil moisture cannot
    silently inherit one another's smoothness. Overrides are for sensitivity runs and for the
    calibration experiment, which sweeps ``nu`` and re-estimates ``sigma``/``length_km`` at each.
    """
    if state not in PRIOR_HYPERPARAMETERS:
        raise KeyError(f"unknown state {state!r}; known: {sorted(PRIOR_HYPERPARAMETERS)}")
    hp = PRIOR_HYPERPARAMETERS[state]
    return GaussianPrior(
        sigma=hp.sigma if sigma is None else sigma,
        length_km=hp.length_km if length_km is None else length_km,
        nu=hp.nu if nu is None else nu,
        region_id=region_id,
    )


# --- the temporal axis --------------------------------------------------------------------------
# Spatial resolution is only half the design. A state that changes fast is observed well only by a
# stream that samples fast: soil moisture responds to a storm within DAYS, so a satellite that revisits
# once a week aliases the very events dv/v or an hourly probe resolves. The two states have very
# different temporal correlation times, which is why the same sensor is worth different amounts for each.
#
# STATUS: these are PROVISIONAL HYPERPARAMETERS, not universal physical constants (issue #205). Each
# is an order-of-magnitude reading of a decorrelation timescale, and both are known to be
# state-dependent -- soil-moisture memory is far shorter in a draining wet soil than in a dry one, and
# a water-table tau depends on specific yield and drainage geometry, which vary across the domain by
# more than the difference between these two numbers. They should be ESTIMATED from the autocovariance
# of the twin's own residuals (per state, and stratified wet/dry), not quoted. Until they are, do not
# describe "5 d" and "120 d" as measured properties of the Puget Sound subsurface.
#
# Key naming: "gwl" is a LEGACY label meaning the water-table-head anomaly (equivalently, up to sign,
# the DTW anomaly -- see src.models.hydro_state). It is deliberately NOT the groundwater storage
# state of the target architecture, and it is NOT a screened-aquifer hydraulic head. The key string
# is kept because ObsStream.states, effective_observability() and several notebooks index on it;
# STATE_LABELS maps it to the unambiguous name.
TEMPORAL_TAU_DAYS = {
    "soil_moisture": 5.0,     # a storm wets, then drains, over days -- provisional
    "gwl": 120.0,             # the water table integrates months (snowmelt-clocked) -- provisional
}

#: Legacy state key -> the unambiguous quantity it denotes, and the matching
#: :data:`PRIOR_HYPERPARAMETERS` entry. Kept as a crosswalk rather than a rename so no call site
#: breaks while the vocabulary is being cleaned up.
STATE_LABELS = {
    "gwl": "water_table_head_anomaly",
    "soil_moisture": "soil_moisture_anomaly",
}


def ou_correlation(lag_days: ArrayLike, tau_days: float) -> NDArray[np.float64]:
    r"""Ornstein-Uhlenbeck correlation :math:`\rho(\Delta t)=\exp(-\Delta t/\tau)` at lag ``lag_days``.

    The state's temporal covariance is modelled as a stationary OU process with correlation time
    :math:`\tau`: :math:`\mathrm{corr}(m(t), m(t-\Delta t)) = \exp(-\Delta t/\tau)`. This is the single
    building block both :func:`temporal_resolution` and a lagged datum's effective operator/noise
    (:func:`lagged_observation`) are derived from -- there is no independent factor of 2 anywhere; that
    would be borrowed from a *spatial* squared-exponential kernel (whose :math:`\exp(-d^2/2L^2)` form
    is for a smooth Gaussian random field, not a first-order Markov process in time) and does not
    belong here. Note that the spatial prior is no longer squared-exponential: :class:`GaussianPrior`
    is Matern (:func:`matern_correlation`), and its :math:`\nu=1/2` case is the *spatial* analogue of
    this OU form.

    ``tau_days`` is a provisional hyperparameter -- see :data:`TEMPORAL_TAU_DAYS`.
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


def water_table_point_footprint(coords_km: NDArray[np.float64], loc_km: ArrayLike,
                                measurement_target: str, width_km: float = 0.5
                                ) -> NDArray[np.float64]:
    r"""Point operator for the **shallow water-table head** state — gated on the observation semantic.

    A water level in a well is a hydraulic head :math:`H = z + p/(\rho_w g)` for the well's *screened
    interval*. It equals :math:`h_{wt}` only when that interval brackets the phreatic surface of an
    unconfined aquifer. The exact linear point operator is therefore correct for a shallow
    water-table well and **wrong** for a confined, semiconfined, perched, deep or artesian one: such a
    well would pin the shallow water table to a potentiometric surface set somewhere else entirely,
    and the error is a category error, not extra noise.

    ``measurement_target`` must be ``"water_table"``
    (:func:`src.features.well_hydrostratigraphy.measurement_target`). ``"aquifer_head"`` and
    ``"unknown"`` both raise: a deep well may be extremely valuable, but it needs a depth/aquifer
    operator or its own hydraulic-head state, and an unclassifiable well must be flagged rather than
    silently assigned to :math:`h_{wt}` (issue #189).

    :func:`point_footprint` remains available and ungated for states where the semantic does not
    apply (soil-moisture probes, and callers that have already screened their wells).
    """
    from src.features.well_hydrostratigraphy import MEASUREMENT_TARGETS

    if measurement_target not in MEASUREMENT_TARGETS:
        raise ValueError(f"measurement_target must be one of {MEASUREMENT_TARGETS}, "
                         f"got {measurement_target!r}")
    if measurement_target != "water_table":
        raise ValueError(
            f"refusing to build a shallow water-table point operator for a "
            f"measurement_target={measurement_target!r} observation. A screened/deep/confined well "
            "measures the hydraulic head of ITS OWN interval, which is not h_wt; route it through a "
            "depth/aquifer operator or a separate hydraulic-head diagnostic. An 'unknown' well must "
            "be flagged, not assigned to the water table (issue #189).")
    return point_footprint(coords_km, loc_km, width_km)


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


def variance_reduction_ratio(prior_cov: NDArray[np.float64], G: NDArray[np.float64],
                             noise_var: ArrayLike) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    r"""Per-cell **fractional posterior variance reduction** and posterior variance.

    .. math::  R(j) = 1 - \frac{\mathrm{Var}_\text{post}(j)}{\mathrm{Var}_\text{prior}(j)} \in [0,1]

    ``G`` is ``(n_obs, n_cell)`` (each row a footprint summing to 1); ``noise_var`` is a scalar or an
    ``(n_obs,)`` array of :math:`\sigma_{d,i}^2` in the same units as the prior variance. Returns
    ``(R, var_post)``, both length ``n_cell``. Empty ``G`` returns zero reduction.

    .. important::
       This is **not** spatial resolution and does not by itself establish spatial resolving power.
       :math:`R(j)` is a statement about the *variance* at cell :math:`j`, not about *which* part of
       the field the estimate at :math:`j` averages. A dv/v datum whose coda kernel spans kilometres
       can push :math:`R` toward 1 at a 90 m cell while the estimate there is a broad volume average;
       reading that as "resolved at 90 m" is precisely the inference this docstring exists to block.
       For resolving power use :func:`averaging_kernel` (rows of the Bayesian resolution operator),
       :func:`resolution_width_km` (an effective localization width), and
       :func:`degrees_of_freedom_for_signal` (how many independent things the data actually
       determine).

       :func:`resolution` is a backward-compatible alias of this function and returns the same
       quantity.
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


#: Backward-compatible alias. The name is kept because it is used across notebooks, figures and
#: tests; the QUANTITY is the fractional posterior variance reduction, not spatial resolution. See
#: :func:`variance_reduction_ratio`.
resolution = variance_reduction_ratio


def averaging_kernel(prior_cov: NDArray[np.float64], G: NDArray[np.float64], noise_var: ArrayLike,
                     rows: ArrayLike | None = None) -> NDArray[np.float64]:
    r"""Rows of the Bayesian **resolution (averaging-kernel) operator** :math:`A`.

    .. math::  \hat m - m_b = A\,(m - m_b) + \text{noise}, \qquad
               A = C G^\top \big(G C G^\top + C_d\big)^{-1} G .

    Row :math:`j` of :math:`A` is :math:`\partial \hat m_j/\partial m` — the weighting over the *true*
    field that the estimate at cell :math:`j` actually forms. This is the quantity that answers "what
    does this network resolve, and over what footprint", which a diagonal variance ratio cannot:
    a delta-like row means cell :math:`j` is genuinely resolved at grid scale; a broad row means the
    estimate there is a smooth average however small :math:`\mathrm{Var}_\text{post}(j)` is.

    ``rows`` selects which cells to return (default: all — an ``(n_cell, n_cell)`` array, so pass a
    subset on any real grid). Returns ``(len(rows), n_cell)``.

    Note that :math:`\mathrm{diag}(A)` and the variance-reduction ratio are *different* numbers: for a
    single point observation of cell :math:`j` with noise :math:`\sigma_d^2` and prior variance
    :math:`\sigma^2`, :math:`A_{jj} = R(j) = \sigma^2/(\sigma^2+\sigma_d^2)`, but as soon as
    observations are correlated with neighbouring cells the two diverge, and only :math:`A` says where
    the information came from.
    """
    C = np.asarray(prior_cov, dtype="float64")
    G = np.atleast_2d(np.asarray(G, dtype="float64"))
    n = C.shape[0]
    idx = np.arange(n) if rows is None else np.atleast_1d(np.asarray(rows, dtype=int))
    if G.size == 0 or G.shape[0] == 0:
        return np.zeros((idx.size, n), dtype="float64")
    nv = np.broadcast_to(np.asarray(noise_var, dtype="float64"), (G.shape[0],))
    CG = C @ G.T                                      # (n_cell, n_obs)
    M = G @ CG + np.diag(nv)                          # (n_obs, n_obs)
    return CG[idx, :] @ np.linalg.solve(M, G)         # (len(idx), n_cell)


def resolution_width_km(prior_cov: NDArray[np.float64], G: NDArray[np.float64], noise_var: ArrayLike,
                        coords_km: NDArray[np.float64], rows: ArrayLike | None = None
                        ) -> NDArray[np.float64]:
    r"""Effective spatial width (km) of the averaging kernel at the selected cells.

    For row :math:`j` of :math:`A` (:func:`averaging_kernel`), the width is the
    :math:`|A_{j\cdot}|`-weighted RMS distance from cell :math:`j`,

    .. math::  W_j = \sqrt{\frac{\sum_k |A_{jk}|\,\|x_k-x_j\|^2}{\sum_k |A_{jk}|}} ,

    i.e. the radius of gyration of the weighting the estimate at :math:`j` applies to the true field.
    Absolute values are used because an averaging kernel can carry small negative side-lobes, which
    are spread, not cancellation.

    A cell with a *high* variance-reduction ratio and a *large* :math:`W_j` is well constrained in
    variance but poorly localized — the case the "90 m resolution" reading gets wrong. Cells with no
    constraint at all (all-zero row) return NaN rather than 0, because "unconstrained" is not
    "perfectly localized".
    """
    A = averaging_kernel(prior_cov, G, noise_var, rows=rows)
    c = np.asarray(coords_km, dtype="float64")
    n = c.shape[0]
    idx = np.arange(n) if rows is None else np.atleast_1d(np.asarray(rows, dtype=int))
    w = np.abs(A)
    tot = w.sum(axis=1)
    d2 = np.sum((c[None, :, :] - c[idx][:, None, :]) ** 2, axis=-1)     # (len(idx), n_cell)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.sqrt(np.sum(w * d2, axis=1) / tot)
    return np.where(tot > 0, out, np.nan)


def degrees_of_freedom_for_signal(prior_cov: NDArray[np.float64], G: NDArray[np.float64],
                                  noise_var: ArrayLike) -> float:
    r"""Degrees of freedom for signal, :math:`\mathrm{DFS} = \mathrm{tr}(A)`.

    The number of independent linear combinations of the state the data actually determine. Bounded
    above by ``n_obs`` (the data cannot determine more numbers than they contain) and by ``n_cell``.
    Where the variance-reduction map says *where* uncertainty fell, DFS says *how much* was learned in
    total — the honest scalar summary of an observing system, and the one that does not inflate when a
    broad-footprint sensor lowers the variance of many correlated cells at once.

    Computed as :math:`\mathrm{tr}\big((GCG^\top+C_d)^{-1}GCG^\top\big)`, an ``n_obs`` solve, so it is
    cheap even on a large grid.
    """
    C = np.asarray(prior_cov, dtype="float64")
    G = np.atleast_2d(np.asarray(G, dtype="float64"))
    if G.size == 0 or G.shape[0] == 0:
        return 0.0
    nv = np.broadcast_to(np.asarray(noise_var, dtype="float64"), (G.shape[0],))
    S = G @ (C @ G.T)                                 # (n_obs, n_obs) = G C G^T
    return float(np.trace(np.linalg.solve(S + np.diag(nv), S)))


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
