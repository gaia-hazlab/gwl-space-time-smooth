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

## Scale: the matrix-free prior operator (issue #154)

A dense :math:`(n, n)` prior is the wall. At the twin's full 90 m domain (1889 x 1567 = 2 960 063
cells) ``C`` alone is ~70 TB, and :meth:`GaussianPrior.cov`'s transient peak is several times that.
:func:`resolution` and :func:`blue_update` never need ``C`` as a matrix, though -- they consume it
through exactly four things: ``.shape[0]``, ``diag(C)``, ``C @ G.T``, and ``G @ (C @ G.T)``. So the
prior is treated here as an **operator protocol**: anything with ``.shape``, ``.diagonal()`` and
``__matmul__`` is accepted (``np.ndarray`` already satisfies all three, which is why the existing
dense path is untouched and bit-for-bit unchanged).

:class:`StationaryGridPrior` -- built by :meth:`GaussianPrior.operator` -- is the matrix-free backend.
On a complete uniform raster in row-major (``y`` outer, ``x`` inner) order, which is exactly what
every caller's ``np.meshgrid(x, y)`` + ``.ravel()`` produces, a stationary isotropic kernel matrix is
block-Toeplitz-with-Toeplitz-blocks, so ``C @ V`` is an **exact** 2-D convolution evaluated by
circulant embedding (``scipy.fft``, threaded). This is not an approximation and not a taper: measured
agreement with the dense ``cov()`` is 3e-15 relative in the worst case over ``nu`` in {0.5, 1.5, 2.5}
x {plain, ``scale``, ``region_id``, both} -- i.e. double-precision rounding, and on real domain
coordinates the operator is the MORE accurate of the two (see the class docstring). Cost is
:math:`O(K\, n \log n)` per column instead of :math:`O(n^2)`, with ``K`` the number of ``region_id``
regions (1 when unset).

**Measured** on a 48-vCPU host with ``workers=-1``, ``nu=1.5``, ``L=12`` km, 90 m cells:

===================  ==========  =============================  ==================================
``n_cell``           build       ``C @ G.T``, ``n_obs = 100``   dense ``C`` would be
===================  ==========  =============================  ==================================
99 856               0.01 s      0.24 s                         0.08 TB
490 000              0.05 s      0.90 s                         1.9 TB
2 960 063 (full)     0.31 s      5.62 s                         70.1 TB
===================  ==========  =============================  ==================================

A full-domain :func:`resolution` with 40 point sensors runs end-to-end in 5.8 s at a 5.9 GB process
peak -- of which 4.7 GB is ``G`` (0.95 GB) plus the ``(n, n_obs)`` cross-covariance and its transpose,
i.e. the observation side, not the prior. Including construction the operator overtakes the dense path
at ~2 000 cells and is 160x faster at 20 000 (16.7 s -> 0.10 s for a 100-column product); below ~2 000
cells a dense BLAS ``GEMM`` is still the quicker matvec, which is exactly why the dense path is kept
and left untouched.

What the operator **requires**, and what it does **not** do -- both matter, because a scalability claim
that quietly changes the answer is worse than no claim at all:

- It requires a **complete uniform raster** and a kernel that is **stationary and isotropic within each
  region**. Per-cell ``scale`` (a prior-sigma multiplier, :math:`C = D C_0 D`) and ``region_id``
  masking are carried **exactly**, not approximated -- the region partition identity
  :math:`C = K \circ \sum_k u_k u_k^\top` is applied term by term. Coordinates that are not such a
  raster **raise** :class:`ValueError` with a specific message; they never silently degrade to a
  wrong answer.
- **The prior is no longer the binding constraint -- the observation side is.** ``C @ G.T`` is a real
  dense ``(n, n_obs)`` array (2.4 GB at ``n_obs = 100``, full domain), and the analysis needs an
  ``(n_obs, n_obs)`` solve. A whole-domain 0.2 km satellite product (~6e5 rows) or a per-riparian-cell
  :func:`channel_footprints` set (1e4-1e5 rows) is therefore still infeasible **regardless of the
  prior representation**. Nothing here changes that.
- **Sparsifying ``G`` would not rescue the dv/v rows.** A coda-sensitivity row is genuinely dense: the
  diffusion footprint width is :math:`\sqrt{4Dt} \approx 17.9` km and the kernel is normalised over
  the whole grid with no truncation, so those rows have support everywhere.
- ``K`` regions multiply the FFT cost by up to ``K`` (each region is a separate transform pair). A
  per-region bounding-box restriction would recover most of that and is deliberately **not** in scope:
  no production caller sets ``region_id`` today.
- Only :math:`\mathrm{diag}(C_\text{post})` is available through this path -- **no posterior samples
  and no cross-cell posterior covariance**. (Sampling would additionally need the circulant embedding
  to be PSD, which it need not be; see :class:`StationaryGridPrior`.)
- A resolution map at 90 m is **oversampled** relative to a 3-12 km prior correlation length. It
  should be read as a smooth field, not as 90 m information -- the fine grid buys geometry, not
  independent degrees of freedom.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.fft import irfft2, next_fast_len, rfft2


_SQRT3 = 3.0 ** 0.5
_SQRT5 = 5.0 ** 0.5

# Largest ``n_cell`` for which :meth:`GaussianPrior.cov` will build a dense ``(n, n)`` covariance.
# 20_000 cells is ~3.2 GB for the final array and ~19 GB peak (``cov`` transiently holds the
# ``(n, n, 2)`` coordinate difference, its square, the distance, the Matern temporaries and the region
# mask at once). Above it, use :meth:`GaussianPrior.operator` -- see the module docstring.
DENSE_MAX_CELLS = 20_000


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
    (issue #163) -- ``region_id`` is the cheap, exact fix for that leakage.

    :meth:`cov` builds the **dense** ``(n, n)`` covariance and is capped at :data:`DENSE_MAX_CELLS`
    cells; above that it raises rather than attempt a 70 TB allocation. The scalable path is
    :meth:`operator`, which returns a matrix-free :class:`StationaryGridPrior` carrying the same
    ``sigma``/``length_km``/``nu``/``region_id`` **exactly** (issue #154). No sparse GMRF/SPDE
    precision approximation is needed for the full-resolution solve: on the uniform analysis raster
    the covariance operator is exactly diagonalised by an FFT. What remains infeasible at full
    resolution is the *observation* side (a dense ``(n, n_obs)`` cross-covariance and an
    ``(n_obs, n_obs)`` solve), not the prior -- see the module docstring.
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
        """Dense prior covariance ``C`` for cell centres ``coords_km`` (``(n, 2)`` array, km).

        Raises :class:`ValueError` above :data:`DENSE_MAX_CELLS` cells -- see :meth:`operator` for the
        matrix-free path that has no such limit.
        """
        c = np.asarray(coords_km, dtype="float64")
        n = c.shape[0]
        if n > DENSE_MAX_CELLS:
            raise ValueError(
                f"dense prior covariance refused: {n} cells would need "
                f"{n * n * 8 / 1e9:.1f} GB for C alone (and several times that at peak), over the "
                f"DENSE_MAX_CELLS={DENSE_MAX_CELLS} limit (a module-level constant in "
                f"{__name__}, raise it deliberately if you really mean it). Use "
                "GaussianPrior.operator(coords_km) instead: it returns a matrix-free "
                "StationaryGridPrior that resolution()/blue_update() accept directly and that is "
                "EXACT, not an approximation (issue #154).")
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

    def operator(self, coords_km: NDArray[np.float64],
                 scale: ArrayLike | None = None) -> "StationaryGridPrior":
        r"""Matrix-free prior operator for ``coords_km``, which MUST be a complete uniform raster.

        Returns a :class:`StationaryGridPrior` carrying this prior's ``sigma``, ``length_km``, ``nu``
        and ``region_id`` exactly, usable anywhere a dense ``C`` is (``resolution``, ``blue_update``,
        ``marginal_resolution``) at :math:`O(n \log n)` per column instead of :math:`O(n^2)`.

        ``coords_km`` must be ``(n, 2)`` ``[x, y]`` cell centres laid out **row-major with ``y``
        outer and ``x`` inner** -- i.e. exactly ``np.column_stack([gx.ravel(), gy.ravel()])`` for
        ``gx, gy = np.meshgrid(x_km, y_km)``. A DESCENDING ``y`` (the north-up raster convention every
        caller in this repo uses) is fine and handled deliberately: the kernel is isotropic, so only
        ``|dy|`` enters. ``scale``, if given, is an ``(n,)`` per-cell multiplier on the prior standard
        deviation (:math:`C = D C_0 D`, ``D = diag(scale)``), carried exactly.

        Anything that is not such a raster -- ragged rows, a masked/subset domain, non-uniform
        spacing, a column-major (``x`` outer) layout -- raises :class:`ValueError`. It is NOT inferred,
        tapered or silently fixed up: an irregular coordinate array quietly getting a
        stationary-grid answer is the worst failure mode this module could have.
        """
        c = np.asarray(coords_km, dtype="float64")
        if c.ndim != 2 or c.shape[1] != 2:
            raise ValueError(f"coords_km must be (n, 2) [x, y] in km, got shape {c.shape}")
        n = c.shape[0]
        if n == 0:
            raise ValueError("coords_km is empty; there is no raster to infer")
        x, y = c[:, 0], c[:, 1]

        # nx = length of the first row, i.e. the run of leading cells sharing y[0]
        differs = np.flatnonzero(y != y[0])
        nx = int(differs[0]) if differs.size else n
        if nx <= 0 or n % nx != 0:
            raise ValueError(
                f"coords_km is not a complete raster: inferred nx={nx} from the leading run of "
                f"constant y, which does not divide n={n}. GaussianPrior.operator() requires the "
                "FULL uniform grid in row-major (y outer, x inner) order, as produced by "
                "np.column_stack([gx.ravel(), gy.ravel()]) with gx, gy = np.meshgrid(x_km, y_km); "
                "it cannot represent a masked or ragged subset. Use .cov() for irregular coordinates "
                f"(dense, capped at DENSE_MAX_CELLS={DENSE_MAX_CELLS} cells).")
        ny = n // nx
        X, Y = x.reshape(ny, nx), y.reshape(ny, nx)

        dx = _uniform_step(X[0], "x", "within a row")
        dy = _uniform_step(
            Y[:, 0], "y", "down the first column",
            hint=(" (this is also what a COLUMN-major layout looks like: meshgrid(..., indexing='ij')"
                  " or a transposed ravel puts y on the inner axis, which reads back as a jumping y"
                  " spacing.)")) if ny > 1 else 0.0
        tol = 1e-9 * max(abs(dx), abs(dy), 1.0)
        if not np.allclose(Y, Y[:, :1], rtol=0.0, atol=tol):
            raise ValueError(
                "coords_km is not in row-major (y outer, x inner) order: y is not constant along "
                "each row. Did you build it with meshgrid(..., indexing='ij') or transpose it? "
                "Expected np.column_stack([gx.ravel(), gy.ravel()]) from np.meshgrid(x_km, y_km).")
        if not np.allclose(X, X[:1, :], rtol=0.0, atol=tol):
            raise ValueError(
                "coords_km is not a uniform raster: the x coordinates are not identical from row to "
                "row (x must be nx-periodic). GaussianPrior.operator() needs the full rectangular "
                "grid; use .cov() for irregular coordinates.")

        return StationaryGridPrior(
            ny=ny, nx=nx, dy_km=abs(dy), dx_km=abs(dx), sigma=float(self.sigma),
            length_km=float(self.length_km), nu=float(self.nu),
            scale=None if scale is None else np.asarray(scale, dtype="float64").ravel(),
            region_id=self.region_id)


def _uniform_step(v: NDArray[np.float64], axis: str, where: str, hint: str = "") -> float:
    """Single uniform spacing of ``v``, or :class:`ValueError` naming what was wrong.

    The step is the **span average** ``(v[-1] - v[0]) / (len(v) - 1)``, NOT the first difference.
    That matters on real projected coordinates: EPSG:5070 x is ~2e3 km, so a single differenced
    90 m step carries ~1e-12 RELATIVE error from catastrophic cancellation (float64 spacing at
    2005 is 4.5e-13 km), and because every lag in :class:`StationaryGridPrior` is that one step
    times an integer, the error propagates coherently into every kernel entry. Dividing the whole
    span by ``len(v) - 1`` spreads the same absolute cancellation over ``len(v) - 1`` steps, so the
    relative error falls by that factor (100x on a 100-cell axis, ~1900x on the full domain's
    1889-cell axis) and the operator matches an exact-lag extended-precision reference as closely
    as it does on origin-centred coordinates. The uniformity check below still compares every
    individual difference, so a genuinely irregular axis is still refused.
    """
    a = np.asarray(v, dtype="float64")
    dv = np.diff(a)
    if dv.size == 0:
        return 0.0
    step = float((a[-1] - a[0]) / dv.size)
    if not np.isfinite(step) or step == 0.0:
        raise ValueError(
            f"coords_km has a zero or non-finite {axis} spacing ({step!r}) {where}; "
            "GaussianPrior.operator() requires a uniform raster.")
    if not np.allclose(dv, step, rtol=1e-9, atol=0.0):
        worst = float(np.max(np.abs(dv - step)))
        raise ValueError(
            f"coords_km has non-uniform {axis} spacing {where}: mean step {step:.9g} km, worst "
            f"deviation {worst:.3g} km (tolerance rtol=1e-9). GaussianPrior.operator() is a "
            "stationary-grid (FFT) representation and is only exact on a uniform raster; it will "
            "NOT approximate an irregular one. Use .cov() (dense, capped at "
            f"DENSE_MAX_CELLS={DENSE_MAX_CELLS} cells) for irregular coordinates.{hint}")
    return step


@dataclass(frozen=True, eq=False)
class StationaryGridPrior:
    r"""Matrix-free prior covariance on a uniform raster: ``C @ V`` by FFT, never an ``(n, n)`` array.

    Built by :meth:`GaussianPrior.operator` (use that; the fields here are the raster geometry it
    infers). Satisfies the operator protocol :func:`resolution` and :func:`blue_update` need --
    ``.shape``, ``.diagonal()``, ``__matmul__`` -- so it is a drop-in for a dense ``C``.

    ## Why this is EXACT, not an approximation

    Cells are laid out row-major (``y`` outer, ``x`` inner) on a complete uniform ``ny x nx`` raster,
    so a stationary isotropic kernel entry depends only on the index lag ``(i - i', j - j')``: the
    matrix is block-Toeplitz-with-Toeplitz-blocks. Embedding it in a circulant of size
    ``py x px`` with ``py >= 2*ny - 1``, ``px >= 2*nx - 1`` and applying it by FFT reproduces the
    Toeplitz product on the leading block exactly, because the zero-padded input cannot alias.
    Measured against the dense :meth:`GaussianPrior.cov` on a non-square 23 x 17 raster with
    ``dy != dx`` and a descending ``y``, the relative matvec error is <= 3.1e-15 across every
    supported ``nu`` and every combination of ``scale`` and ``region_id``, and <= 1.1e-14 end to end
    through :func:`resolution` / :func:`blue_update` / :func:`marginal_resolution`. ``diagonal()``
    matches ``np.diag(cov(...))`` to <= 8.9e-16.

    On the *real* domain the operator is in fact the more accurate of the two: EPSG:5070 coordinates
    are ~2e3 km in magnitude, and ``cov()`` differences them to get a ~0.09 km lag, losing ~1e-13
    relative to cancellation. The operator never forms a coordinate difference -- it works from the
    integer lag and the spacing -- so it does not pay that. (The 1.4e-13 seen when comparing the two
    on domain coordinates is the dense path's error, not the FFT's.)

    ``region_id`` is honoured through the partition identity :math:`C = K \circ \sum_k u_k u_k^\top`
    with ``u_k`` the region indicator vectors, so

    .. math::  CV = \sum_k (s \odot u_k) \odot K\big[(s \odot u_k) \odot V\big],

    ``s`` the per-cell ``scale`` (1 if unset). Each term is an independent FFT apply -- ``K`` regions
    therefore cost up to ``K`` transforms per column. Dropping ``region_id`` here would silently
    reintroduce the cross-divide constraint leakage issue #163 exists to prevent, so it is carried
    through, not optimised away.

    ## Two things that look like bugs and are not

    - **The embedded circulant need not be positive semi-definite, and that is harmless.** Its minimum
      eigenvalue is measurably negative for these Matern kernels on this padding (-42.03 for a
      40 x 31 raster at 90 m with ``L = 3`` km, ``nu = 1.5``, padded to 80 x 63). The identity
      :math:`Cv = P^\top(\hat C (Pv))` restricted to the leading block holds regardless of the sign of
      :math:`\hat C`'s eigenvalues -- it is an algebraic statement about the embedding, not a spectral
      one. (PSD of the embedding is required only to *draw samples* by FFT, which this class does not
      do and which is out of scope.) With that negative eigenvalue present the matvec still agrees
      with the dense product to 2.3e-15 relative.
    - **``next_fast_len`` is not cosmetic.** ``1889`` -- one of the full-domain axis lengths -- is
      prime, so a literal ``2*n`` transform length would be ``2 x 1889``, which drops ``scipy.fft``
      into a Bluestein/Rader path and is pathologically slow. ``next_fast_len(2*1889 - 1) = 3780 =
      2^2 x 3^3 x 5 x 7``.

    ## Cost

    ``block`` columns of ``V`` are transformed per batch, so the transform working set is roughly
    ``2 * block * py * px * 8`` bytes and does NOT grow with ``n_obs`` -- ~1.5 GB at the default
    ``block=8`` on the full 3780 x 3136 padded domain (measured: 5.9 GB process peak for a
    100-column full-domain product, of which 4.7 GB is ``G`` and the result). ``workers=-1`` hands the
    transforms to every available core. The **returned** ``C @ G.T`` is a real dense ``(n, n_obs)``
    array (2.4 GB at ``n = 2.96e6``, ``n_obs = 100``); that intermediate is deliberately kept -- see
    the module docstring for why the observation side, not the prior, is now the binding constraint.
    """

    ny: int
    nx: int
    dy_km: float
    dx_km: float
    sigma: float
    length_km: float
    nu: float = 1.5
    scale: NDArray[np.float64] | None = None      # (n,) per-cell sigma multiplier -> C = D C0 D
    region_id: NDArray[np.int64] | None = None    # (n,) integer labels; correlation 0 across labels
    block: int = 8                                # columns of V transformed per FFT batch
    workers: int = -1                             # scipy.fft thread count (-1 = all cores)

    def __post_init__(self) -> None:
        ny, nx = int(self.ny), int(self.nx)
        if ny < 1 or nx < 1:
            raise ValueError(f"ny and nx must both be >= 1, got ({self.ny}, {self.nx})")
        n = ny * nx
        for name, v in (("scale", self.scale), ("region_id", self.region_id)):
            if v is not None and np.asarray(v).size != n:
                raise ValueError(
                    f"{name} has {np.asarray(v).size} entries but the raster has {n} cells")
        py, px = next_fast_len(2 * ny - 1), next_fast_len(2 * nx - 1)
        # wrap-around lag: the circulant's (a, b) entry is the kernel at lag min(a, p - a)
        ly = np.minimum(np.arange(py), py - np.arange(py)) * abs(float(self.dy_km))
        lx = np.minimum(np.arange(px), px - np.arange(px)) * abs(float(self.dx_km))
        k = (self.sigma ** 2) * matern_correlation(
            np.hypot(ly[:, None], lx[None, :]), self.length_km, self.nu)
        object.__setattr__(self, "_pad", (py, px))
        object.__setattr__(self, "_khat", rfft2(k, workers=self.workers))
        # the (scale * region-indicator) weight vectors of the partition identity; None = all-ones
        s = None if self.scale is None else np.asarray(self.scale, dtype="float64").ravel()
        if self.region_id is None:
            w = None if s is None else (s,)
        else:
            lab = np.asarray(self.region_id).ravel()
            ones = np.ones(n, dtype="float64") if s is None else s
            w = tuple(ones * (lab == u) for u in np.unique(lab))
        object.__setattr__(self, "_weights", w)

    @property
    def shape(self) -> tuple[int, int]:
        n = int(self.ny) * int(self.nx)
        return (n, n)

    def diagonal(self) -> NDArray[np.float64]:
        """``diag(C)`` = ``sigma**2 * scale**2``, exactly.

        The Matern correlation is bitwise ``1.0`` at zero lag for all three closed forms and the
        region mask is 1 on the diagonal, so this is exact rather than an FFT evaluation. It is NOT
        ``sigma**2`` in general -- ``scale`` makes the prior variance heterogeneous, and callers that
        read the prior variance off the diagonal must see that.
        """
        d = np.full(int(self.ny) * int(self.nx), float(self.sigma) ** 2, dtype="float64")
        if self.scale is not None:
            d *= np.asarray(self.scale, dtype="float64").ravel() ** 2
        return d

    def _apply_kernel(self, V: NDArray[np.float64]) -> NDArray[np.float64]:
        """Unweighted stationary apply ``K @ V`` (``V`` is ``(n, m)``), by circulant embedding."""
        ny, nx = int(self.ny), int(self.nx)
        py, px = self._pad
        out = np.empty_like(V)
        blk = max(1, int(self.block))
        for a in range(0, V.shape[1], blk):
            cols = V[:, a:a + blk]
            m = cols.shape[1]
            buf = np.zeros((m, py, px), dtype="float64")
            buf[:, :ny, :nx] = cols.T.reshape(m, ny, nx)
            f = rfft2(buf, workers=self.workers)
            f *= self._khat
            z = irfft2(f, s=(py, px), workers=self.workers)
            out[:, a:a + blk] = z[:, :ny, :nx].reshape(m, ny * nx).T
        return out

    def __matmul__(self, V: ArrayLike) -> NDArray[np.float64]:
        """``C @ V`` for ``V`` of shape ``(n,)`` or ``(n, m)``; returns the same rank."""
        v = np.asarray(V, dtype="float64")
        flat = v.ndim == 1
        if flat:
            v = v[:, None]
        if v.ndim != 2 or v.shape[0] != self.shape[0]:
            raise ValueError(
                f"cannot apply a {self.shape} prior operator to an array of shape "
                f"{np.shape(V)}; expected leading dimension {self.shape[0]}")
        w = self._weights
        if w is None:                                    # no scale, one region: a plain apply
            out = self._apply_kernel(v)
        else:
            out = np.zeros_like(v)
            for wk in w:
                out += wk[:, None] * self._apply_kernel(wk[:, None] * v)
        return out[:, 0] if flat else out


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


def _as_prior(P):
    """The prior as either a dense ``float64`` array (unchanged legacy path) or an operator backend.

    A prior is consumed by :func:`resolution` / :func:`blue_update` through only ``.shape``,
    ``.diagonal()`` and ``__matmul__``. ``np.ndarray`` already satisfies all three, so the dense path
    below is exactly what it always was. Anything else that satisfies the protocol (notably
    :class:`StationaryGridPrior`) is passed through **untouched**: calling ``np.asarray`` on it would
    either densify a 70 TB matrix or raise, which is the whole point of having it.
    """
    if isinstance(P, np.ndarray):
        return np.asarray(P, dtype="float64")            # existing behaviour, unchanged
    if hasattr(P, "diagonal") and hasattr(P, "__matmul__") and hasattr(P, "shape"):
        return P                                          # matrix-free operator backend
    return np.asarray(P, dtype="float64")                 # lists, nested sequences, etc.


def resolution(prior_cov: NDArray[np.float64], G: NDArray[np.float64],
               noise_var: ArrayLike) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    r"""Per-cell resolution and posterior variance for observations ``G`` with noise ``noise_var``.

    ``G`` is ``(n_obs, n_cell)`` (each row a footprint summing to 1); ``noise_var`` is a scalar or an
    ``(n_obs,)`` array of :math:`\sigma_{d,i}^2` in the same units as the prior variance. Returns
    ``(resolution, var_post)``, both length ``n_cell``. Empty ``G`` returns zero resolution.

    ``prior_cov`` may be a dense ``(n_cell, n_cell)`` array **or** any operator satisfying the prior
    protocol (``.shape``, ``.diagonal()``, ``__matmul__``) -- e.g. a :class:`StationaryGridPrior` from
    :meth:`GaussianPrior.operator`, which never materialises ``C`` (issue #154). Memory note: the
    ``C @ G.T`` cross-covariance below is a real dense ``(n_cell, n_obs)`` array either way (2.4 GB at
    the full 2.96e6-cell domain with ``n_obs = 100``); the operator removes the ``(n, n)`` prior, not
    that intermediate.
    """
    C = _as_prior(prior_cov)
    var_prior = C.diagonal().copy()
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

    ``prior_cov`` may equally be a matrix-free prior operator (``.shape``, ``.diagonal()``,
    ``__matmul__``), e.g. :meth:`GaussianPrior.operator` -- see :func:`resolution` for the memory
    caveat on the ``(n_cell, n_obs)`` cross-covariance, which is dense on both paths.
    """
    B = _as_prior(prior_cov)
    G = np.atleast_2d(np.asarray(G, dtype="float64"))
    mb = np.broadcast_to(np.asarray(prior_mean, dtype="float64"), (B.shape[0],)).astype("float64")
    if G.size == 0 or G.shape[0] == 0:
        return mb.copy(), B.diagonal().copy()
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
    var_prior = B.diagonal().copy()               # .copy(): ndarray.diagonal() is a read-only view
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
