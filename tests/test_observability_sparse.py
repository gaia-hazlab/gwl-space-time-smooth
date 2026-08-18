"""V&V for the sparse GMRF/SPDE precision prior (issue #163, the *scalability* fault).

`tests/test_observability.py` pins the dense linear-Gaussian core and is left untouched; this file
implements the falsification benchmarks §7.1-§7.8 of the theory spec for
:class:`src.models.observability.SparseMaternPrior`, :func:`matern_spde_tau`,
:func:`resolution_precision` and :func:`blue_update_precision`.

Why a separate file, and why these particular numbers: the sparse path replaces a dense ``(n, n)``
covariance with a 13-non-zeros-per-row precision, so almost every claim it makes is either an *exact
structural* claim (a bit-exact zero, an eigenvalue known in closed form) or a *measured approximation*
with a stated size. Both kinds are falsifiable, and the whole point of this file is that they are
actually falsified-or-not by running code rather than asserted in a docstring. The single most
load-bearing test is :func:`test_7_4_...`: the precision estimator versus ``inv(Q)`` fed to the
EXISTING dense estimator. Both sides describe the same covariance, so that one is a bit-identity and
catches any implementation error in the estimator independently of every modelling approximation in
the prior.

Conventions used throughout (spec §0/§4.1): ``kappa = sqrt(2*nu)/length_km``, so ``length_km`` is the
Matern SCALE and the Lindgren practical range is ``2*length_km``. The closed-form nu=1 correlation is
``rho(r) = kappa*r*K_1(kappa*r)``; the repo's :func:`matern_correlation` does NOT support nu=1, so the
reference is built directly from :func:`scipy.special.kv` here.
"""

from __future__ import annotations

import os
import tracemalloc
import warnings
from contextlib import contextmanager

import numpy as np
import pytest
from scipy import sparse
from scipy.linalg import eigvalsh
from scipy.sparse import linalg as sparse_linalg
from scipy.special import gamma, kv

from src.models import observability as _obs
from src.models.observability import (
    GaussianPrior,
    SparseMaternPrior,
    blue_update,
    blue_update_precision,
    matern_correlation,
    matern_spde_tau,
    point_footprint,
    resolution,
    resolution_precision,
)


# --- helpers --------------------------------------------------------------------------------------

@contextmanager
def _quiet():
    """Silence the class's (correct, deliberate) geometry UserWarnings inside a benchmark.

    Several benchmarks *require* a geometry the class warns about -- a small isolated ``region_id``
    patch is exactly what §7.6 measures, and the anisotropic tau test below deliberately uses a coarse
    axis. The warnings themselves are asserted separately in
    :func:`test_the_four_mandated_geometry_warnings_fire` and
    :func:`test_the_kappa_dx_resolution_warning_fires_on_the_COARSER_axis`, so suppressing them here is
    not hiding anything.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        yield


@contextmanager
def _patched(name: str, value):
    """Temporarily set a module-level constant of ``src.models.observability``, then restore it.

    Written by hand rather than with pytest's ``monkeypatch`` fixture so that these tests stay callable
    outside a pytest session (the sibling ``tests/test_observability.py`` is runnable as ``__main__``).
    """
    old = getattr(_obs, name)
    setattr(_obs, name, value)
    try:
        yield
    finally:
        setattr(_obs, name, old)


def _coords(ny: int, nx: int, dx: float, dy: float | None = None) -> np.ndarray:
    """Cell-centre coordinates in the prior's own C-order ravel: index ``jy*nx + jx``."""
    dy = dx if dy is None else dy
    jy, jx = np.divmod(np.arange(ny * nx), nx)
    return np.column_stack([jx * dx, jy * dy]).astype("float64")


def _rho_nu1(r: np.ndarray, kappa: float) -> np.ndarray:
    """Closed-form Matern nu=1 correlation ``kappa*r*K_1(kappa*r)`` (=1 at r=0)."""
    r = np.asarray(r, dtype="float64")
    out = np.ones_like(r)
    m = r > 0
    x = kappa * r[m]
    out[m] = x * kv(1.0, x)
    return out


def _bessel_cov_nu1(coords: np.ndarray, kappa: float) -> np.ndarray:
    """Dense nu=1 Matern covariance (unit sigma) -- the reference the SPDE prior is *supposed* to be."""
    d = np.sqrt(np.sum((coords[:, None, :] - coords[None, :, :]) ** 2, axis=-1))
    return _rho_nu1(d, kappa)


def _ktilde(prior: SparseMaternPrior) -> sparse.csr_matrix:
    """The bare 5-point operator ``K~ = A/(tau*sqrt(h))`` -- what the exact eigenvalue claims are about."""
    return prior.operator() / (prior.tau * np.sqrt(prior.dx_km * (prior.dy_km or prior.dx_km)))


# --- matern_spde_tau, independently ----------------------------------------------------------------

def test_matern_spde_tau_matches_a_brute_force_2d_brillouin_quadrature():
    """The 1-D closed-form theta2 reduction (spec eq. 5) must equal the raw 2-D zone integral.

    tau is what makes the DISCRETE marginal variance equal sigma^2 (the continuum formula is wrong by
    8% on a 2 km grid). The implementation does the theta2 integral analytically and midpoint-quadratures
    only theta1; if that reduction were wrong, every marginal variance in the class is silently
    mis-scaled -- and, crucially, isotropically-wrong-in-the-same-way, so §7.2 alone would not localise
    it. The brute-force 2-D quadrature is an independent derivation, including for dx != dy.
    """
    def brute_ibar(kappa, dx, dy, m=2000):
        th = (np.arange(m) + 0.5) * (2.0 * np.pi / m) - np.pi          # midpoints of [-pi, pi]
        a = kappa ** 2 + (4.0 / dx ** 2) * np.sin(th / 2.0) ** 2
        b = (4.0 / dy ** 2) * np.sin(th / 2.0) ** 2
        return float((1.0 / (a[:, None] + b[None, :]) ** 2).mean())     # (1/4pi^2)(2pi/m)^2 sum = mean

    cases = [(0.35355, 1.0, 1.0), (np.sqrt(2) / 4, 0.5, 0.5),
             (np.sqrt(2) / 4, 0.5, 0.25), (np.sqrt(2) / 4, 0.25, 1.0),   # anisotropic, both directions
             (0.7, 2.0, 0.5), (1.0, 0.1, 3.0)]                          # extreme aspect ratios
    for kappa, dx, dy in cases:
        tau = matern_spde_tau(kappa, dx, dy, sigma=1.0)
        ibar = tau ** 2 * dx * dy                                       # tau^2 = Ibar/(h sigma^2)
        assert abs(ibar / brute_ibar(kappa, dx, dy) - 1.0) < 1e-9, (kappa, dx, dy)
        # spectral convergence: doubling the node count must not move the answer
        assert abs(tau / matern_spde_tau(kappa, dx, dy, 1.0, quad_n=8192) - 1.0) < 1e-9
    # sigma enters as a pure 1/sigma scaling (tau^2 = Ibar/(h sigma^2))
    t1 = matern_spde_tau(0.5, 0.5, 0.5, sigma=1.0)
    t2 = matern_spde_tau(0.5, 0.5, 0.5, sigma=4.0)
    assert abs(t1 / t2 - 4.0) < 1e-12


def test_matern_spde_tau_rejects_nonsense_arguments():
    for bad in ({"kappa": 0.0}, {"kappa": np.nan}, {"dx_km": -1.0}, {"dy_km": 0.0},
                {"sigma": -2.0}, {"sigma": np.inf}):
        kw = {"kappa": 0.35, "dx_km": 0.5, "dy_km": 0.5, "sigma": 1.0} | bad
        with pytest.raises(ValueError):
            matern_spde_tau(**kw)
    with pytest.raises(ValueError):
        matern_spde_tau(0.35, 0.5, 0.5, 1.0, quad_n=0)


# --- THE kappa-convention guard (read this before loosening anything below) ------------------------

def test_the_kappa_convention_is_sqrt_2nu_over_L_and_the_practical_range_is_2L():
    """**This is the test that pins ``kappa = sqrt(2*nu)/length_km``.** Nothing else pins it head-on.

    Read this before touching test_7_5 or test_7_6. Two comparisons in this file *look* like kappa
    checks and are not:

    * :func:`test_7_1_...` builds its reference as ``_rho_nu1(r, p.kappa)`` -- the IMPLEMENTATION'S OWN
      kappa. Mutate the convention and operator and reference move together; the comparison is
      invariant to it. It does fail under a mutation, but only as collateral (kappa*dx doubles from
      0.354 to 0.707 and the discretization error breaches the 0.035 bound), which is a resolution
      check wearing a convention check's clothes.
    * :func:`test_7_5_...`'s ``d1`` diagnostic is blind to the convention for exactly the same reason
      (``cov_1`` is ``_bessel_cov_nu1(coords, p.kappa)``), *despite* being the tighter of that test's
      two bounds. Under the mutation below it does trip -- but on collateral discretization again, at
      0.040 against its 0.03 bound, while ``d15`` on the same run reads 0.49 against its 0.10: an order
      of magnitude apart, and only one of them is measuring the convention. It is ``d15``, against
      ``GaussianPrior``, whose kappa comes from the repo's own dense :func:`matern_correlation`, that
      carries an independent convention -- together with :func:`test_7_6_...`'s hardcoded
      ``np.sqrt(2.0)/L`` fed to the 4pi/(kappa^2 A) law.

    So the guard used to be real but incidental and undocumented, one refactor away from being deleted
    by someone trusting the wrong docstring. Everything below is an INDEPENDENT literal.

    What a regression to Lindgren's ``kappa = sqrt(8*nu)/length_km`` (the convention the original task
    brief assumed) would do: double kappa, halving the range, so the sparse prior would be half as
    long-ranged as the dense sibling at the same ``length_km`` -- the two classes' ``length_km`` would
    silently mean different things.
    """
    L = 4.0
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=L, shape=(9, 9), dx_km=0.5)

    # 1. the parameter itself, against a literal written out here and not imported from anywhere
    assert abs(p.kappa - np.sqrt(2.0 * 1.0) / L) < 1e-15 * p.kappa, p.kappa
    assert p.nu == 1.0                                       # sqrt(2*nu) with nu pinned at 1
    # ...and it is NOT Lindgren's, which is exactly a factor of two away
    assert abs(p.kappa - np.sqrt(8.0 * 1.0) / L) > 0.4 * p.kappa, p.kappa

    # 2. the OPERATOR realises that kappa, not just the property: lambda_min(K~) = kappa^2 exactly
    #    (L_G 1 = 0 for any edge subset, so the constant vector attains it). A 2x kappa moves this 4x.
    assert abs(eigvalsh(_ktilde(p).toarray()).min() / (2.0 / L ** 2) - 1.0) < 1e-12

    # 3. the practical range really is 2*length_km: rho(2L) = 0.1397, rho(L) = 0.4443 (spec §1.3 table,
    #    reproduced here from scipy.special.kv with the literal kappa, not with p.kappa)
    kappa_lit = np.sqrt(2.0) / L
    assert abs(_rho_nu1(np.array([2.0 * L]), kappa_lit)[0] - 0.1397) < 1e-3
    assert abs(_rho_nu1(np.array([1.0 * L]), kappa_lit)[0] - 0.4443) < 1e-3

    # 4. the same convention the repo's DENSE kernel already uses -- which is what makes length_km mean
    #    the same thing in both siblings. matern_correlation has no nu=1, so this is checked at the
    #    three nu it does support, against the closed form with kappa = sqrt(2*nu)/L.
    d = np.linspace(0.01, 4.0 * L, 60)
    for nu in (0.5, 1.5, 2.5):
        x = (np.sqrt(2.0 * nu) / L) * d
        ref = (2.0 ** (1.0 - nu) / gamma(nu)) * x ** nu * kv(nu, x)
        assert np.max(np.abs(matern_correlation(d, L, nu) - ref)) < 1e-14, nu

    # 5. end-to-end, through the actual solve: the DISCRETE correlation at r = 2L must be ~0.14.
    #    Measured 0.1389 (analytic 0.1397 less the 0.004 discretization deficit) at kappa*dx = 0.088.
    #    Under the sqrt(8*nu)/L mutation the same lag would read 0.011 -- a 12x miss.
    n, dx = 161, 0.25
    with _quiet():
        big = SparseMaternPrior(sigma=1.0, length_km=L, shape=(n, n), dx_km=dx)
    c = (n // 2) * n + n // 2
    e = np.zeros(big.n)
    e[c] = 1.0
    col = big.solve(e)
    corr = col.reshape(n, n)[n // 2, n // 2:] / col[c]
    assert 0.130 < corr[int(round(2.0 * L / dx))] < 0.145, corr[int(round(2.0 * L / dx))]
    assert 0.430 < corr[int(round(1.0 * L / dx))] < 0.455, corr[int(round(1.0 * L / dx))]


# --- §7.1 interior correlation vs the closed-form Matern nu=1 ---------------------------------------

def test_7_1_interior_correlation_matches_the_closed_form_matern_nu1_and_converges():
    """The discrete field must actually BE a Matern nu=1 field in the interior, and converge as dx->0.

    A column of ``Q^-1`` at the domain centre, normalised by its own diagonal, is the discrete
    correlation function. Compared against ``rho(r) = kappa*r*K_1(kappa*r)`` along a grid axis it must
    (a) be within the stated tolerance at each resolution, (b) be a smooth ONE-SIGNED DEFICIT -- because
    tau is normalised exactly, the error is *not* a short-lag pathology, so short lags are NOT excluded
    (only lags where the reflecting boundary contaminates, r > half-width - 1 practical range), and
    (c) shrink by >= 2x per halving of dx.

    **What this does NOT pin: the kappa convention.** The reference is ``_rho_nu1(r, p.kappa)`` -- the
    implementation's own kappa -- so under a convention mutation the operator and the reference move
    together and this comparison is invariant to it. What survives is only the collateral: kappa*dx
    doubles and the discretization error breaches the bound. That is a resolution check, not a
    convention check. The convention is pinned deliberately, and only, in
    :func:`test_the_kappa_convention_is_sqrt_2nu_over_L_and_the_practical_range_is_2L`.
    """
    L = 4.0
    errs = {}
    for n, dx in ((81, 1.0), (161, 0.5), (241, 0.25)):
        with _quiet():
            p = SparseMaternPrior(sigma=1.0, length_km=L, shape=(n, n), dx_km=dx)
        c = (n // 2) * n + n // 2
        e = np.zeros(p.n)
        e[c] = 1.0
        col = p.solve(e)
        corr = col.reshape(n, n)[n // 2, n // 2:] / col[c]              # along +x from the centre
        r = np.arange(corr.size) * dx
        keep = r <= (n // 2) * dx - 2.0 * L          # drop lags contaminated by the Neumann boundary
        assert keep.sum() > 20
        signed = corr[keep] - _rho_nu1(r[keep], p.kappa)
        errs[dx] = float(np.abs(signed).max())
        # the error is a one-signed DEFICIT (discrete correlation never above analytic), spec §7.1
        assert signed.max() < 1e-12, f"dx={dx}: discrete correlation exceeds analytic by {signed.max()}"
        # and short lags are NOT the worst place -- the peak sits near r ~ 0.5 L, not at r = 1 cell
        assert abs(signed[1]) < errs[dx]
    # measured 0.0292 / 0.0122 / 0.00426 at kappa*dx = 0.354 / 0.177 / 0.088
    assert errs[1.0] < 0.035, errs                    # kappa*dx = 0.354 (8 cells per practical range)
    assert errs[0.5] < 0.015, errs                    # kappa*dx = 0.177 (16 cells per range)
    assert errs[0.25] < 0.015, errs
    assert errs[1.0] / errs[0.5] >= 2.0, errs         # >= 2x error reduction per halving of dx
    assert errs[0.5] / errs[0.25] >= 2.0, errs



def test_7_1_on_an_ANISOTROPIC_grid_the_correlation_error_is_PER_AXIS_but_the_axes_are_COUPLED():
    """Every other §7.1 correlation benchmark is isotropic, so "the coarser axis limits accuracy" was
    an *inference* from single-resolution runs, not a measurement.

    The class warns on ``kappa * max(dx, dy)`` -- see
    :func:`test_the_kappa_dx_resolution_warning_fires_on_the_COARSER_axis` -- and the two existing
    anisotropic tests cover the marginal variance (:func:`test_7_2_..._ANISOTROPIC_...`) and the FFT
    symbol's axis association (:func:`test_the_periodic_control_variate_uses_the_right_axis_convention`).
    Neither of those sees correlation error at all: tau normalises the variance exactly at any
    kappa*h, so the variance test passes whatever the correlation is doing. This measures the thing
    the warning is actually about.

    Configuration: L = 4, dx = 0.25, dy = 1.0, i.e. kappa*dx = 0.088 and kappa*dy = 0.354 -- exactly
    the finest and coarsest resolutions §7.1 measures isotropically (0.00426 and 0.0292), so the two
    axes of one grid can be read against two isotropic runs directly.

    **What it shows, and it is not quite either simple story.** The coarse axis carries 0.0223 -- a bit
    *better* than the 0.0292 it would carry on a fully-coarse isotropic grid, so ``kappa*max(dx, dy)``
    is a conservative proxy and the warning's threshold is safe. But the fine axis carries 0.0089,
    **2.1x its own isotropic value of 0.00426**, so the error is NOT purely per-axis: refining one axis
    alone buys you a factor of 2.5 over the coarse axis, not the factor of 7 the isotropic table would
    suggest. "The coarser axis limits accuracy" is right about which axis binds and wrong if read as
    "the fine axis is unaffected".

    Two further anisotropy-specific facts pinned here:

    * §7.1's **one-signed deficit** is an isotropy property. On the fine axis of an anisotropic grid the
      discrete correlation *exceeds* the analytic one at the two shortest lags, by +4.6e-4. Small, but
      strictly positive, and :func:`test_7_1_...` would fail its ``signed.max() < 1e-12`` if pointed at
      this grid. The coarse axis stays one-signed to 7e-7.
    * The **transpose is identical to 3e-15**: (dx, dy) = (0.25, 1.0) on an (81, 241) grid and
      (1.0, 0.25) on a (241, 81) grid give the same two numbers with the axes swapped. A dx/dy
      transposition anywhere in the operator, the tau integral, or the ravel would break this, and it
      would break it *without* changing any isotropic test.
    """
    L = 4.0
    iso_fine, iso_coarse = 0.00426, 0.0292            # §7.1's measured isotropic values, as literals

    def axis_errors(ny, nx, dx, dy):
        """max|drho| along +x and along +y from the centre cell, boundary-contaminated lags dropped."""
        with _quiet():                                # kappa*dy = 0.354 is just under the 0.36 warning
            p = SparseMaternPrior(sigma=1.0, length_km=L, shape=(ny, nx), dx_km=dx, dy_km=dy)
        cy, cx = ny // 2, nx // 2
        e = np.zeros(p.n)
        e[cy * nx + cx] = 1.0
        f = p.solve(e).reshape(ny, nx)
        out = []
        for prof, h, half in ((f[cy, cx:], dx, cx), (f[cy:, cx], dy, cy)):
            corr = prof / f[cy, cx]
            r = np.arange(corr.size) * h
            keep = r <= half * h - 2.0 * L            # drop lags the Neumann boundary contaminates
            assert keep.sum() > 20
            out.append(corr[keep] - _rho_nu1(r[keep], p.kappa))
        return out

    sx, sy = axis_errors(81, 241, 0.25, 1.0)          # x FINE (kappa*dx=0.088), y COARSE (0.354)
    e_fine, e_coarse = float(np.abs(sx).max()), float(np.abs(sy).max())

    # 1. the coarse axis binds: it carries several times the fine axis's error...
    assert 0.020 < e_coarse < 0.025, e_coarse                     # measured 0.02227
    assert e_coarse > 2.0 * e_fine, (e_coarse, e_fine)
    # ...and kappa*max(dx, dy) is a CONSERVATIVE proxy: no axis is worse than the fully-coarse grid
    assert e_coarse < iso_coarse, (e_coarse, iso_coarse)
    # 2. but the axes are COUPLED -- the fine axis is dragged well above its isotropic value
    assert 0.008 < e_fine < 0.010, e_fine                         # measured 0.00892
    assert e_fine > 1.8 * iso_fine, (e_fine, iso_fine)            # 2.1x, not 1.0x: not purely per-axis
    assert e_fine < 0.5 * iso_coarse, (e_fine, iso_coarse)        # ...but nowhere near dragged to 0.029
    # 3. the one-signed deficit is an ISOTROPY property, not a property of the operator
    assert sx.max() > 1e-5, sx.max()                              # fine axis genuinely OVERSHOOTS
    assert sx.max() < 1e-3, sx.max()                              # ...but only by 4.6e-4
    assert sy.max() < 1e-6, sy.max()                              # coarse axis still one-signed
    # 4. the transpose is the same grid with the axes swapped, to 3e-15
    tx, ty = axis_errors(241, 81, 1.0, 0.25)
    assert np.max(np.abs(sx - ty)) < 1e-12, np.max(np.abs(sx - ty))
    assert np.max(np.abs(sy - tx)) < 1e-12, np.max(np.abs(sy - tx))


# --- §7.2 marginal variance ------------------------------------------------------------------------

def test_7_2_interior_marginal_variance_equals_sigma_squared():
    """``diag(B)`` in the deep interior must be sigma^2 -- this is what the exact tau normalization buys.

    Run against ``method="exact"`` (n solves), not ``"analytic"`` (which returns sigma^2 by definition
    and so cannot fail). The continuum tau would fail this by 3% at kappa*dx = 0.354. The residual here
    is the finite-domain reflection, not the quadrature: the same grid widened from 8 to 10.7 practical
    ranges drops the deviation from 4e-9 to 3e-12.
    """
    sigma = 2.0
    p = SparseMaternPrior(sigma=sigma, length_km=4.0, shape=(64, 64), dx_km=1.0)   # 8 practical ranges
    v = p.marginal_var(method="exact")
    centre = (64 // 2) * 64 + 64 // 2
    assert abs(v[centre] / sigma ** 2 - 1.0) < 1e-8
    # the Neumann artifact is real and in the predicted direction: ~x2 at a straight edge, ~x4 at a
    # corner (spec §3). Asserting this pins that the boundary is REFLECTING, not Dirichlet (which
    # would DEFLATE the variance toward 0.117 sigma^2 and wreck resolution()'s denominator).
    assert 1.7 < v[(64 // 2) * 64] / sigma ** 2 < 2.1
    assert 3.2 < v[0] / sigma ** 2 < 4.1


def test_7_2_marginal_variance_is_exact_on_an_ANISOTROPIC_grid_too():
    """dx != dy on a non-square grid: the tau integral's anisotropy handling, end to end.

    An isotropic test passes whether or not the (dx, dy) <-> (nx, ny) axis association is right. This
    one does not: it uses dx = 4*dy on a 128x32 grid, where swapping the axes anywhere in the chain
    would leave the marginal variance visibly off sigma^2.

    The coarse axis here is deliberately coarse -- kappa*max(dx,dy) = 1.41, four times the class's
    kappa*dx <= 0.36 resolution limit, so the constructor (correctly) warns. That warning is true and
    irrelevant *to this assertion*: tau comes from the exact infinite-lattice Brillouin-zone integral,
    which is exact at every kappa*dx, so the marginal variance is sigma^2 to 1e-10 however coarse the
    grid is. Coarse is the point: a 4:1 aspect ratio is what makes an axis swap visible. The resolution
    warning itself is asserted in
    :func:`test_the_kappa_dx_resolution_warning_fires_on_the_COARSER_axis`.
    """
    sigma = 1.5
    with _quiet():
        p = SparseMaternPrior(sigma=sigma, length_km=1.0, shape=(128, 32), dx_km=1.0, dy_km=0.25)
    v = p.marginal_var(method="exact")
    centre = (128 // 2) * 32 + 32 // 2
    assert abs(v[centre] / sigma ** 2 - 1.0) < 1e-10


# --- §7.3 region_id severing -----------------------------------------------------------------------

def test_7_3_cross_region_covariance_is_a_STRUCTURAL_zero_and_the_boundary_is_a_fold():
    """Two claims, and they are different in kind.

    (1) Cross-region covariance is EXACTLY 0.0, not 1e-16 -- that is the whole point of severing edges
    in the precision rather than masking a dense kernel, so it is asserted with ``== 0.0`` (and also
    structurally, on Q's sparsity graph, which cannot be luck of a LAPACK rounding).

    (2) The severed face carries the SAME variance inflation as a free domain edge. That is what proves
    the edge weight was FOLDED onto the diagonal rather than DELETED: deletion is a Dirichlet-like
    internal boundary that *deflates* variance at the divide -- i.e. claims near-certainty exactly where
    the terrain says the two sides are independent.
    """
    n, dx, L = 64, 1.0, 4.0
    rid = np.zeros((n, n), dtype=np.int64)
    rid[:, n // 2:] = 1                                        # a vertical divide down the middle
    p = SparseMaternPrior(sigma=1.0, length_km=L, shape=(n, n), dx_km=dx, region_id=rid)
    r = rid.ravel()

    q = p.precision().tocoo()                                  # structural: no Q entry crosses regions
    assert not np.any(r[q.row] != r[q.col])

    b = p.dense_cov()
    assert np.max(np.abs(b[np.ix_(r == 0, r == 1)])) == 0.0    # exact equality, deliberately
    j = int(np.flatnonzero(r == 1)[0])                          # and through the solve path, not inv()
    e = np.zeros(p.n)
    e[j] = 1.0
    assert np.max(np.abs(p.solve(e)[r == 0])) == 0.0

    v = np.diag(b)
    mid = n // 2
    free_edge = v[mid * n + 0]                                  # left domain edge, mid-height
    severed = v[mid * n + (mid - 1)]                            # cell against the divide, mid-height
    assert abs(severed - free_edge) < 1e-10 * free_edge
    assert free_edge > 1.7                                      # ...and both are the ~x2 fold, not a
    assert abs(v[mid * n + mid] - free_edge) < 1e-10 * free_edge   # deletion's deflation to ~0.12


# --- §7.4 THE MANDATORY ONE ------------------------------------------------------------------------

@pytest.mark.parametrize("region_id,standardize", [(None, False), ("split", False), ("split", True)])
def test_7_4_precision_estimator_is_bit_identical_to_the_dense_estimator_on_inv_Q(region_id, standardize):
    """MANDATORY (spec §7.4): the precision path vs ``inv(Q)`` fed to the EXISTING dense estimator.

    This is the strongest verification available, and it is a bit-identity rather than an agreement
    test: both sides describe *the same covariance*, so any difference beyond round-off is an
    implementation error in the sparse estimator -- the two-stage solve, the ``X = Q^-1 G^T`` assembly,
    the observation-space M, the clip, or the standardization congruence. It is independent of every
    modelling approximation in the prior (nu=1, the 5-point stencil, the Neumann boundary), which is
    what makes it the test that has to pass before any of the others mean anything.

    Parametrized over a plain grid, a severed grid, and a STANDARDIZED severed grid, because
    ``standardize=True`` changes Q by a diagonal congruence and it would be easy to apply that
    congruence in one place (``precision()``) and its inverse in another (``solve()``).
    """
    n, dx, L, sigma = 41, 0.5, 2.5, 1.3
    rid = None
    if region_id == "split":
        rid = np.zeros((n, n), dtype=np.int64)
        rid[:, n // 2:] = 1
    with _quiet():
        p = SparseMaternPrior(sigma=sigma, length_km=L, shape=(n, n), dx_km=dx,
                              region_id=rid, standardize=standardize)
    coords = _coords(n, n, dx)
    rng = np.random.default_rng(3)
    g = np.vstack([point_footprint(coords, loc, 0.7)
                   for loc in rng.uniform(1.0, (n - 1) * dx - 1.0, size=(6, 2))])
    noise, d = 0.02, rng.normal(size=6)

    cov = p.dense_cov()                                        # inv(Q.toarray()), the same covariance
    v_exact = p.marginal_var(method="exact")
    res_dense, vp_dense = resolution(cov, g, noise)
    res_sparse, vp_sparse = resolution_precision(p, g, noise, var_prior=v_exact)
    assert np.max(np.abs(res_dense - res_sparse)) < 1e-10
    assert np.max(np.abs(vp_dense - vp_sparse)) < 1e-10

    ma_dense, _ = blue_update(cov, g, d, noise, prior_mean=0.7)
    ma_sparse, _ = blue_update_precision(p, g, d, noise, prior_mean=0.7, var_prior=v_exact)
    assert np.max(np.abs(ma_dense - ma_sparse)) < 1e-10


# --- §7.5 agreement-in-behaviour with the dense path ------------------------------------------------

# The layout seeds :func:`test_7_5_...` runs. NOT an arbitrary six: seeds 0-25 are a contiguous,
# unbiased block, and the four appended seeds are the extremes of an OUT-OF-BAND sweep of 5000
# layouts at this exact configuration (61x61, dx = 0.5, L = 3, 8 point footprints, noise 0.02) --
# 2825 is the worst max|d15| (0.1120), 3271 the worst rms|d15| (0.0533), 1857 the worst max|d1|
# (0.0248), and 3638 the DEGENERATE layout (0/8 footprints in the interior box; worst correlation
# 0.99201 and the only one of 5000 whose discretization/nu ratio exceeds 0.5).
#
# Why the appended four exist at all: an earlier version of this test ran ``range(6)`` and asserted
# max < 0.10 / rms < 0.045, which the six seeds cleared with ~1% of headroom. Six seeds are a SAMPLE,
# not a bound: over 5000 layouts 3.28% breach 0.10 and 1.32% breach 0.045 (the first breach is at
# seed 63). Both the bounds and the docstring figure they came from were one unlucky layout from
# being wrong. Pinning the measured extremes here means the CI assertion is exercised by the worst
# case actually known to exist, not merely by whatever the first six seeds happened to give.
_SEEDS_7_5 = tuple(range(26)) + (1857, 2825, 3271, 3638)

# The 5000-layout envelope those bounds are set from, quoted so a future change can be compared to it
# rather than re-derived: max|d15| 0.0147-0.1120, rms|d15| 0.0027-0.0533, max|d1| 0.0070-0.0248,
# correlation >= 0.99201. The bounds below sit 16-22% above the worst of 5000.
_ENVELOPE_7_5 = {"max15": (0.0147, 0.1120), "rms15": (0.0027, 0.0533),
                 "max1": (0.0070, 0.0248), "corr_min": 0.99201, "n_layouts": 5000}


def test_7_5_agrees_in_behaviour_with_the_dense_matern_paths_on_interior_cells():
    """Not a bit-identity: nu=1 (sparse) vs nu=1.5 (dense default) is a REAL, quantified difference.

    Restricted to cells >= 1 practical range (= 2*length_km) from every edge, because the reflecting
    boundary is an artifact of the GMRF that the dense kernel simply does not have -- including boundary
    cells would measure the boundary condition, not the agreement.

    The decomposition is the informative part and is asserted as such: the discrepancy against the dense
    nu=1.5 reference is *mostly the nu mismatch*, and the sharper diagnostic against a dense nu=1 Bessel
    kernel isolates discretization alone. Note the decomposition is exact POINTWISE and only pointwise:
    ``d15 = d1 + dnu`` holds cell by cell to 1e-12 (asserted below), but the three *sup-norms* are
    attained at different cells -- over 200 layouts at the docstring's reference configuration all
    three argmaxes coincide in 2 cases out of 200, and ``sup|d1| + sup|dnu|`` overstates ``sup|d15|``
    by a median 1.9% and up to 9.9%. Any "a + b = c" written about those three numbers is indicative,
    not an identity.

    **Which of the two comparisons carries an independent kappa, and it is not the obvious one.** It is
    ``d15``: its reference is ``GaussianPrior(length_km=L)``, built by the repo's own dense
    :func:`matern_correlation`, whose kappa is derived independently of this class -- so a sparse-side
    convention regression shows up there (measured 0.399-0.499 across these layouts against its 0.13
    bound under a sqrt(8nu)/L mutation, i.e. the widened bound still trips on every seed with >= 3.1x
    margin). ``d1`` is blind to the convention as such, despite being the tighter bound, because
    ``cov_1 = _bessel_cov_nu1(coords, p.kappa)`` uses the implementation's own kappa and moves with it;
    under the same mutation it reads 0.040-0.046 against its 0.03 bound, i.e. it trips only on the
    collateral discretization error at the doubled kappa*dx. (An earlier version of this docstring
    asserted these two the other way round.) Neither is the *advertised* guard; that is
    :func:`test_the_kappa_convention_is_sqrt_2nu_over_L_and_the_practical_range_is_2L`.

    **The bounds are the 5000-layout envelope plus headroom, not six seeds' luck** -- see the comment
    on :data:`_SEEDS_7_5`. What sets the discrepancy is how much of the interior a given layout
    actually informs, and that is not bounded away from zero: layout 3638 puts none of its eight
    footprints in the interior box, leaves the interior at 1.0% mean resolution, and drives every
    quantity here toward zero *including* the nu mismatch -- which is why the "discretization is much
    smaller than the nu mismatch" claim is asserted only where the interior is actually informed. Only
    3 of 5000 layouts fall below that gate; above it the ratio never exceeds 0.265.
    """
    n, dx, L = 61, 0.5, 3.0                                    # 5 practical ranges wide, n = 3721
    p = SparseMaternPrior(sigma=1.0, length_km=L, shape=(n, n), dx_km=dx)
    v = p.marginal_var(method="exact")
    coords = _coords(n, n, dx)
    span = (n - 1) * dx
    rngkm = 2.0 * L
    interior = np.all((coords >= rngkm) & (coords <= span - rngkm), axis=1)
    assert interior.sum() > 1000

    cov_15 = GaussianPrior(sigma=1.0, length_km=L, nu=1.5).cov(coords)     # the dense default
    cov_1 = _bessel_cov_nu1(coords, p.kappa)                               # the nu=1 Bessel reference

    rms_15, seen_degenerate = [], False
    for seed in _SEEDS_7_5:
        locs = np.random.default_rng(seed).uniform(0.0, span, size=(8, 2))
        g = np.vstack([point_footprint(coords, loc) for loc in locs])
        r_sparse, _ = resolution_precision(p, g, 0.02, var_prior=v)
        r_15, _ = resolution(cov_15, g, 0.02)
        r_1, _ = resolution(cov_1, g, 0.02)

        d15 = (r_sparse - r_15)[interior]
        assert np.abs(d15).max() < 0.13, (seed, np.abs(d15).max())
        assert np.sqrt((d15 ** 2).mean()) < 0.065, (seed, np.sqrt((d15 ** 2).mean()))
        assert np.corrcoef(r_sparse[interior], r_15[interior])[0, 1] > 0.985, seed
        rms_15.append(float(np.sqrt((d15 ** 2).mean())))

        # the sharper diagnostic: against the SAME nu, the only difference left is discretization
        d1 = (r_sparse - r_1)[interior]
        assert np.abs(d1).max() < 0.03, (seed, np.abs(d1).max())

        # the decomposition itself: exact cell by cell, for every layout, degenerate or not
        d_nu = (r_1 - r_15)[interior]
        assert np.max(np.abs(d15 - (d1 + d_nu))) < 1e-12, seed

        # ...and discretization is much smaller than the nu mismatch -- but only where the layout
        # actually informs the interior. Below the gate every term collapses toward zero together and
        # the RATIO is unbounded (3 layouts of 5000; 3638 is the one carried here, at 0.741).
        informed = float(r_sparse[interior].mean())
        if informed >= 0.02:
            assert np.abs(d1).max() < 0.5 * np.abs(d15).max(), (seed, informed)
        else:
            seen_degenerate = True
            assert np.abs(d15).max() < 0.03, (seed, informed)   # everything collapses, not just d1
    assert seen_degenerate, "seed 3638 must still exercise the uninformed-interior branch"
    assert float(np.mean(rms_15)) < 0.04, rms_15               # the spec's single-layout figure


@pytest.mark.skipif(
    not os.environ.get("GAIA_SLOW_TESTS"),
    reason="the 5000-layout envelope the bounds in test_7_5 are set from; ~60 s. Measured out of "
           "band: max|d15| 0.0147-0.1120 (3.28% of layouts exceed 0.10), rms|d15| 0.0027-0.0533 "
           "(1.32% exceed 0.045), max|d1| 0.0070-0.0248, correlation >= 0.99201. "
           "Set GAIA_SLOW_TESTS=1 to run it in-suite.")
def test_7_5_the_bounds_are_an_envelope_over_5000_layouts_not_a_handful_of_seeds():
    """The evidential basis for :func:`test_7_5_...`'s bounds, run in full rather than quoted.

    :func:`test_7_5_...` runs 30 layouts because CI has to stay quick, and the four appended ones are
    the extremes *found here*. That is only honest if the sweep those extremes came from is itself
    reproducible, which is what this does. It re-derives :data:`_ENVELOPE_7_5` and re-confirms the
    finding that motivated the widening: the old ``max < 0.10 / rms < 0.045`` bounds are breached by a
    few percent of layouts, so they were a ~97th percentile of the layout distribution and not a bound.

    It is deliberately *not* the same assertion as the fast test. The fast test asks "is any layout
    outside the envelope?"; this asks "is the envelope still the envelope?", i.e. it will fail if the
    extremes MOVE, in either direction, by more than the tolerance -- including if they get better,
    because a silent improvement means the quoted docstring figures have gone stale.
    """
    n, dx, L = 61, 0.5, 3.0
    p = SparseMaternPrior(sigma=1.0, length_km=L, shape=(n, n), dx_km=dx)
    v = p.marginal_var(method="exact")
    coords = _coords(n, n, dx)
    span = (n - 1) * dx
    interior = np.all((coords >= 2.0 * L) & (coords <= span - 2.0 * L), axis=1)
    cov_15 = GaussianPrior(sigma=1.0, length_km=L, nu=1.5).cov(coords)
    cov_1 = _bessel_cov_nu1(coords, p.kappa)

    n_layouts = _ENVELOPE_7_5["n_layouts"]
    m15 = np.empty(n_layouts)
    r15 = np.empty(n_layouts)
    m1 = np.empty(n_layouts)
    cc = np.empty(n_layouts)
    for seed in range(n_layouts):
        locs = np.random.default_rng(seed).uniform(0.0, span, size=(8, 2))
        g = np.vstack([point_footprint(coords, loc) for loc in locs])
        r_sparse, _ = resolution_precision(p, g, 0.02, var_prior=v)
        a, _ = resolution(cov_15, g, 0.02)
        b, _ = resolution(cov_1, g, 0.02)
        d15 = (r_sparse - a)[interior]
        m15[seed] = np.abs(d15).max()
        r15[seed] = np.sqrt((d15 ** 2).mean())
        m1[seed] = np.abs((r_sparse - b)[interior]).max()
        cc[seed] = np.corrcoef(r_sparse[interior], a[interior])[0, 1]

    for key, arr in (("max15", m15), ("rms15", r15), ("max1", m1)):
        lo, hi = _ENVELOPE_7_5[key]
        assert abs(arr.min() - lo) < 0.002, (key, arr.min(), lo)
        assert abs(arr.max() - hi) < 0.002, (key, arr.max(), hi)
    assert abs(cc.min() - _ENVELOPE_7_5["corr_min"]) < 0.002, cc.min()

    # ...and the finding that forced the widening, stated as an assertion so it cannot quietly rot:
    # the OLD bounds were not bounds. If a future change makes them true again, this fails and the
    # docstring figures must be tightened rather than left conservative.
    assert (m15 >= 0.10).mean() > 0.02, (m15 >= 0.10).mean()
    assert (r15 >= 0.045).mean() > 0.005, (r15 >= 0.045).mean()
    # ...while the bounds actually asserted have real headroom over all 5000
    assert m15.max() < 0.13 and r15.max() < 0.065 and m1.max() < 0.03 and cc.min() > 0.985


# --- §7.6 the small-region variance law -------------------------------------------------------------

def test_7_6_small_isolated_region_follows_the_4pi_over_kappa2_A_law():
    """An isolated ``region_id`` patch of area A << kappa^-2 must inflate to sigma^2 * 4pi/(kappa^2 A).

    This is the severe consequence of reflecting internal boundaries, and it is a hard analytic
    prediction rather than a bound -- which makes it the sharpest available test of the SEVERING RULE.
    Deleting the edge instead of folding it fails this badly and in the wrong direction (deletion
    *deflates*). Note the asymptotic law needs BOTH A << kappa^-2 and a resolved patch: at
    kappa*dx = 0.177 the discretization offset alone is ~1.8%, so the law is checked at
    kappa*dx = 0.088 where it holds to 0.6%.
    """
    L, dx, N = 4.0, 0.25, 161
    kappa = np.sqrt(2.0) / L        # an INDEPENDENT literal: predicted below is ~4x off under a
                                    # kappa mutation, so this test is a real (if incidental) second
                                    # guard on the convention -- see the dedicated one above.
    w = 4                                                       # 1 km patch: A = 1 km^2 << 8 km^2
    rid = np.zeros((N, N), dtype=np.int64)
    y0 = x0 = N // 2 - w // 2
    rid[y0:y0 + w, x0:x0 + w] = 1
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=L, shape=(N, N), dx_km=dx, region_id=rid)
    idx = np.flatnonzero(rid.ravel() == 1)
    area = (w * dx) ** 2
    assert area * kappa ** 2 < 0.2                              # we really are in the A << kappa^-2 limit
    predicted = 4.0 * np.pi / (kappa ** 2 * area)
    for cell in (idx[0], idx[len(idx) // 2]):                   # corner and centre of the patch
        e = np.zeros(p.n)
        e[cell] = 1.0
        assert abs(p.solve(e)[cell] / predicted - 1.0) < 0.01


def test_7_6_single_cell_region_hits_the_exact_isolated_cell_limit():
    """The isolated-cell limit ``sigma^2/(Ibar_inf * kappa^4)`` is EXACT, not asymptotic: 1e-6.

    An isolated cell's precision is exactly ``tau^2 h kappa^4`` (every edge folded away), so its
    variance is a closed-form number with no discretization error at all. It is therefore the single
    cheapest test that the fold is a fold -- a deletion would leave the 4-neighbour diagonal in place
    and give a *different*, smaller variance.
    """
    L, dx, N = 4.0, 0.5, 41
    rid = np.zeros((N, N), dtype=np.int64)
    rid[N // 2, N // 2] = 1                                     # one cell, its own region
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=L, shape=(N, N), dx_km=dx, region_id=rid)
    ibar_inf = p.tau ** 2 * dx * dx                             # tau^2 = Ibar/(h sigma^2), sigma = 1
    predicted = 1.0 / (ibar_inf * p.kappa ** 4)
    assert abs(predicted - 394.5976) < 1e-3                     # the spec's measured x395
    cell = (N // 2) * N + N // 2
    v = p.marginal_var(method="exact")
    assert abs(v[cell] / predicted - 1.0) < 1e-6
    b = p.dense_cov()                                           # and it is decoupled from everything
    assert np.max(np.abs(np.delete(b[cell], cell))) == 0.0


# --- §7.7 structure ---------------------------------------------------------------------------------

def test_7_7_precision_structure_symmetry_bandwidth_and_the_exact_eigenvalue():
    """Four structural facts, three of them exact to the bit.

    ``lambda_min(K~) == kappa^2`` is the sharpest: ``L_G`` is a graph Laplacian for ANY subset of edges,
    so ``L_G 1 = 0`` and the constant vector of every connected component is an eigenvector with
    eigenvalue exactly kappa^2. A diagonal-folding bug (folding the wrong number of edges, or folding a
    severed edge's weight twice) breaks the row-sum identity and moves this eigenvalue immediately --
    which is why it is a better bug detector than any variance comparison.
    """
    n, dx, L = 24, 1.0, 4.0
    rid = np.zeros((n, n), dtype=np.int64)
    rid[:, n // 2:] = 1
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=L, shape=(n, n), dx_km=dx, region_id=rid)
    q = p.precision()
    assert abs(q - q.T).max() == 0.0                                    # exact symmetry, not allclose
    assert np.diff(q.tocsr().indptr).max() <= 13                        # the 13-point stencil
    assert eigvalsh(q.toarray()).min() > 0.0                            # SPD on a severed grid

    k = _ktilde(p).toarray()
    assert abs(eigvalsh(k).min() / p.kappa ** 2 - 1.0) < 1e-12          # exact analytic prediction
    assert np.allclose(k @ np.ones(p.n), p.kappa ** 2 * np.ones(p.n))   # L_G 1 = 0, the fold identity
    # Gershgorin bound on the condition number (spec §2.1) -- what justifies solving through K~, not Q
    assert eigvalsh(k).max() <= p.kappa ** 2 + 4.0 / dx ** 2 + 4.0 / dx ** 2 + 1e-9


def test_7_7_the_stencil_is_the_expected_five_and_thirteen_point_operator():
    """The bare operator is 5-point and its square is 13-point, with the documented diagonals.

    Interior kappa^2 + 2/dx^2 + 2/dy^2, straight edge kappa^2 + 1/dx^2 + 2/dy^2, corner
    kappa^2 + 1/dx^2 + 1/dy^2 -- i.e. absent edges are omitted from the off-diagonal AND the diagonal
    together. Checked on an anisotropic grid so that a dx/dy swap cannot pass.
    """
    ny, nx, dx, dy = 9, 7, 0.5, 0.25
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=0.5, shape=(ny, nx), dx_km=dx, dy_km=dy)
    k = _ktilde(p)
    assert np.diff(k.tocsr().indptr).max() <= 5
    diag = k.diagonal()
    kap2, wx, wy = p.kappa ** 2, 1.0 / dx ** 2, 1.0 / dy ** 2
    assert abs(diag[(ny // 2) * nx + nx // 2] - (kap2 + 2 * wx + 2 * wy)) < 1e-9   # interior
    assert abs(diag[(ny // 2) * nx + 0] - (kap2 + wx + 2 * wy)) < 1e-9             # left edge
    assert abs(diag[0] - (kap2 + wx + wy)) < 1e-9                                  # corner
    dense = k.toarray()
    assert abs(dense[(ny // 2) * nx + nx // 2, (ny // 2) * nx + nx // 2 + 1] + wx) < 1e-9   # x neighbour
    assert abs(dense[(ny // 2) * nx + nx // 2, (ny // 2 + 1) * nx + nx // 2] + wy) < 1e-9   # y neighbour


# --- §7.8 scalability, MEASURED -------------------------------------------------------------------

def test_7_8a_nonzeros_per_cell_are_bounded_by_13_and_grow_linearly():
    """The O(n) claim, measured over two decades of n rather than asserted.

    nnz/n must stay below 13 at every size (boundary rows have fewer than the interior's 13) and the
    total must grow LINEARLY -- a fitted slope of 13 +- 0.1. A non-local precision (which is what a
    fractional alpha or a consistent mass matrix would give) would show a slope that drifts with n.
    """
    sizes, nnz = [], []
    for side in (41, 81, 161, 321):
        with _quiet():
            p = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(side, side), dx_km=0.5)
        q = p.precision()
        assert q.nnz / p.n < 13.0, (p.n, q.nnz / p.n)
        assert np.diff(q.tocsr().indptr).max() <= 13
        sizes.append(p.n)
        nnz.append(q.nnz)
    assert nnz == sorted(nnz) and sizes == sorted(sizes)
    assert nnz[0] / sizes[0] < nnz[-1] / sizes[-1] < 13.0          # monotone up toward the 13 limit
    slope = float(np.polyfit(np.array(sizes, float), np.array(nnz, float), 1)[0])
    assert abs(slope - 13.0) < 0.1, slope
    # a dense covariance at the largest size here would be 85 GB; this one is a few MB
    assert sizes[-1] ** 2 * 8 > 8e10
    assert nnz[-1] * 8 < 2e7


def test_7_8b_builds_factorizes_and_solves_a_grid_whose_dense_covariance_cannot_be_held():
    """n = 103 041 (321x321). The dense covariance would be 85 GB; no ``(n, n)`` NUMPY array is made.

    **Read the tracemalloc number for exactly what it is.** ``tracemalloc`` instruments CPython's own
    allocator, so it sees numpy arrays created in Python and *not* memory malloc'd inside a C
    extension. SuperLU's L and U factors are allocated inside SciPy's C code and are therefore
    INVISIBLE to it -- and they are not small: measured 1.08e7 non-zeros, ~129 MB, i.e. more than 3x
    the 39 MB traced peak, which the test asserts below so the two figures cannot be confused. So the
    peak traced memory is evidence for the claim it is used to make -- *no ``(n, n)`` numpy array is
    allocated*, 39 MB against 84.9 GB -- and is **not** the total memory cost of factoring, which is
    dominated by the factor. (``resource.getrusage().ru_maxrss`` would see the factor but is a
    process-lifetime high-water mark that earlier tests in the session have already inflated, so it
    cannot bracket a single test; the factor's own nnz is the honest measurement.)

    The two ``(n, n)`` escape hatches must also refuse at this size -- they are verification paths.
    """
    side = 321
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(side, side), dx_km=0.09)
    dense_bytes = p.n ** 2 * 8
    assert dense_bytes > 8e10                                     # 85 GB: this is the point of the test

    tracemalloc.start()
    try:
        a = p.operator()
        q = p.precision()
        x = p.solve(np.ones(p.n))                                 # build + splu factor + two solves
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert np.all(np.isfinite(x))
    assert a.data.nbytes < 2e7
    assert q.data.nbytes < 200e6                                  # spec's threshold; measured ~10.7 MB
    assert peak < 2e8, peak / 1e6      # measured 39.4 MB of numpy peak vs 84.9 GB dense: 4.6e-4x
    assert peak < 1e-3 * dense_bytes

    # ...and the part tracemalloc CANNOT see, measured separately so the 39 MB is not misread as the
    # cost of factoring: SuperLU's L+U at this n is ~1.08e7 nnz (12 bytes each: float64 + int32 index),
    # ~129 MB -- O(n log n), still 660x smaller than the dense covariance, but 3x the traced peak.
    lu = sparse_linalg.splu(p.operator().tocsc(), permc_spec="COLAMD")
    factor_bytes = (lu.L.nnz + lu.U.nnz) * 12
    assert 60.0 < (lu.L.nnz + lu.U.nnz) / p.n < 200.0, (lu.L.nnz + lu.U.nnz) / p.n   # fill, per row
    assert factor_bytes > 2.0 * peak, (factor_bytes, peak)     # the point: tracemalloc missed this
    assert factor_bytes < 1e-2 * dense_bytes                   # and it is still nothing like dense

    with pytest.raises(ValueError):
        p.dense_cov()
    with pytest.raises(ValueError):
        p.marginal_var(method="exact")


@pytest.mark.skipif(
    not os.environ.get("GAIA_SLOW_TESTS"),
    reason="800x800 (n=640000, dense-equivalent 3.3 TB) takes ~6 s and ~1.3 GB of splu factor; "
           "measured out of band: build 0.13 s, solve 5.8 s, Q.data 66.4 MB, nnz/n 12.975. "
           "Set GAIA_SLOW_TESTS=1 to run it in-suite.")
def test_7_8b_extreme_the_dense_equivalent_is_3_3_terabytes():
    """The spec's headline scalability case: n = 640 000, dense C = 3.3 TB."""
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(800, 800), dx_km=0.09)
    assert p.n ** 2 * 8 > 3e12
    q = p.precision()
    assert q.nnz / p.n < 13.0
    assert q.data.nbytes < 200e6
    x = p.solve(np.ones(p.n))
    assert np.all(np.isfinite(x)) and x.shape == (p.n,)


def test_7_8c_monte_carlo_diagonal_error_scales_as_K_to_the_minus_half():
    """diag(B) by the split estimator must converge at the Monte-Carlo rate and no slower.

    The rate is the load-bearing claim (it is what makes ``n_samples`` a knob with a known price);
    the constant is *better* than the plain sqrt(2/K) because the implementation applies the exact
    periodic control variate by default, which can only reduce variance. So the assertions are
    (a) rms <= **0.6 x** sqrt(2/K) at every K, and (b) the rms halves per 4x samples, averaged over
    seeds (a single seed's rms is itself noisy).

    **Why 0.6 and not 1.0.** A bound of plain sqrt(2/K) has 2-4x of slack here and is passed by an
    implementation with **no control variate at all**: measured without it, this grid gives mean rms
    0.170 / 0.0785 / 0.0463 at K = 64 / 256 / 1024, i.e. 0.96 / 0.89 / 1.05 x sqrt(2/K) -- so deleting
    the variance reduction outright would have slipped through at two of the three K. With the control
    variate the measured ratios are 0.454 / 0.460 / 0.453, so 0.6 keeps ~30% headroom against seed
    noise while failing decisively (by ~1.6x) if the control variate is removed. It is a smaller
    reduction than the spec's 3-4x because a 41x41 grid at L = 4 km is nearly all boundary, which is
    exactly where the correction is *not* zero; the anisotropic test below uses the same 0.6.
    (b) is deliberately kept as a separate assertion: it is rate, not constant, and the no-CV
    implementation passes it -- the two together are what make the claim.
    """
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(41, 41), dx_km=0.5)
    exact = p.marginal_var(method="exact")
    mean_rms = {}
    for k in (64, 256, 1024):
        rms = []
        for seed in range(4):
            est = p.marginal_var(method="mc", n_samples=k, rng=np.random.default_rng(seed))
            rms.append(float(np.sqrt((((est - exact) / exact) ** 2).mean())))
        mean_rms[k] = float(np.mean(rms))
        assert mean_rms[k] < 0.6 * np.sqrt(2.0 / k), (k, mean_rms[k])  # the CV must actually be there
        assert mean_rms[k] > 0.1 * np.sqrt(2.0 / k), (k, mean_rms[k])  # ...and not suspiciously zero
    for lo, hi in ((64, 256), (256, 1024)):
        ratio = mean_rms[lo] / mean_rms[hi]
        assert 1.5 < ratio < 2.8, (lo, hi, ratio)                    # K^-1/2 => 2x per 4x samples


def test_the_periodic_control_variate_uses_the_right_axis_convention():
    """dx != dy on a NON-SQUARE grid: the circulant symbol's (nx, ny) <-> (dx, dy) pairing.

    This one needs care. The control variate stays *unbiased* even if the symbol's axes are
    transposed (the same lambda drives both the sampled field and the closed-form constant), so no
    mean-value test can see the error -- only the VARIANCE REDUCTION degrades. Measured on this grid:
    the correct symbol gives rms 0.036 at K = 256, a transposed one 0.095 (worse than plain
    sqrt(2/256) = 0.088). The assertion below separates those two by a factor of ~2.5.
    """
    ny, nx, dy, dx = 51, 63, 0.25, 1.0
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(ny, nx), dx_km=dx, dy_km=dy)
    exact = p.marginal_var(method="exact")
    k = 256
    rms = [float(np.sqrt((((p.marginal_var(method="mc", n_samples=k,
                                           rng=np.random.default_rng(s)) - exact) / exact) ** 2).mean()))
           for s in range(4)]
    assert float(np.mean(rms)) < 0.6 * np.sqrt(2.0 / k), rms


# --- standardize=True: the congruence direction ----------------------------------------------------

def test_standardize_forces_unit_marginal_variance_and_preserves_correlations_and_zeros():
    """``Qt = D^-1 Q D^-1`` with ``D = diag(sigma/sqrt(B_ii))``, i.e. ``Bt = D B D``.

    The DIRECTION of the congruence is the thing to pin: the inverse direction would give
    ``diag(Bt) = B_ii^2/sigma^2``, which is right only where B_ii already equals sigma^2 -- so an
    interior-only check would pass either way. This test uses a grid with a divide AND a tiny 3x3
    region, where B_ii ranges over two orders of magnitude, so the direction is unambiguous.

    The three properties that make standardization a legitimate modelling option rather than a fudge:
    diag(Bt) == sigma^2 exactly, every correlation unchanged, every structural zero still exactly zero.
    ``solve``/``sample``/``precision``/``dense_cov`` must all agree on which direction was taken.
    """
    n, sigma = 33, 1.7
    rid = np.zeros((n, n), dtype=np.int64)
    rid[:, n // 2:] = 1
    rid[2:5, 2:5] = 2                                             # a tiny region: B_ii >> sigma^2 there
    with _quiet():
        plain = SparseMaternPrior(sigma=sigma, length_km=4.0, shape=(n, n), dx_km=0.5, region_id=rid)
        std = SparseMaternPrior(sigma=sigma, length_km=4.0, shape=(n, n), dx_km=0.5, region_id=rid,
                                standardize=True)
    b0, bs = plain.dense_cov(), std.dense_cov()
    assert np.max(np.abs(np.diag(b0) - sigma ** 2)) > 5.0 * sigma ** 2     # the problem is real...
    assert np.max(np.abs(np.diag(bs) - sigma ** 2)) < 1e-9 * sigma ** 2    # ...and standardization fixes it

    corr0 = b0 / np.sqrt(np.outer(np.diag(b0), np.diag(b0)))
    corrs = bs / np.sqrt(np.outer(np.diag(bs), np.diag(bs)))
    assert np.max(np.abs(corr0 - corrs)) < 1e-10                  # a diagonal congruence: correlations
    r = rid.ravel()
    for i, j in ((0, 1), (0, 2), (1, 2)):
        assert np.max(np.abs(bs[np.ix_(r == i, r == j)])) == 0.0  # structural zeros survive exactly
    assert eigvalsh(std.precision().toarray()).min() > 0.0        # and it is still SPD

    # every access path must apply the SAME congruence
    e = np.zeros(plain.n)
    e[7] = 1.0
    assert np.max(np.abs(std.solve(e) - bs[:, 7])) < 1e-9
    assert np.max(np.abs(std.marginal_var(method="exact") - sigma ** 2)) == 0.0
    draws = std.sample(4000, rng=np.random.default_rng(1))
    assert abs(draws.var(axis=0).mean() / sigma ** 2 - 1.0) < 0.05


def test_standardize_above_the_exact_guard_is_only_sigma_squared_TO_MONTE_CARLO_ACCURACY():
    """The honest half of ``standardize=True``: above n = 4096 it is exact only to ~2%, and it SAYS so.

    Below the ``_EXACT_MAX_N`` guard ``_scale`` builds the congruence from the exact ``diag(B)`` (n
    solves) and ``diag(D B D)`` is sigma^2 to 1e-9 -- that is what the test above measures, on n = 1089.
    Above it, ``_scale`` falls back to a 512-sample Monte-Carlo ``diag(B)``, so **the standardization
    inherits that estimator's error**: the true ``diag(D B D)`` is sigma^2 only to ~2% rms and ~6-8%
    near a divide, exactly the accuracy quoted for ``marginal_var(method="mc", n_samples=512)``.
    ``marginal_var`` nevertheless returns *exactly* sigma^2 for every method, because under
    ``standardize=True`` it short-circuits to ``full(n, sigma**2)`` by construction. That gap is
    documented on the class and was untested; a plain ``n <= 4096`` test cannot see it at all.

    Measured here (n = 65^2 = 4225, one vertical divide, sigma = 1.3, over 115 sampled cells): the true
    standardized diagonal is off by 2.6% rms and 7.8% max. So this asserts the deviation is BOTH
    non-zero (the exactness claim does not extend past the guard) and bounded at the documented size.

    The consequence that actually reaches a figure: ``var_prior`` from such a prior is a hair *below*
    the true prior variance at some cells, and ``reduction`` is computed from the exact ``X``, so the
    pre-clip resolution there exceeds 1 (measured 1.070). The ``np.clip(reduction, 0, var_prior)``
    guard is what keeps the published ratio in [0, 1] -- and it saturates one-sidedly, pinning those
    cells at exactly 1.0 with var_post exactly 0.0 rather than reporting a slightly-too-large number.
    """
    n, sigma, L, dx = 65, 1.3, 4.0, 0.5
    rid = np.zeros((n, n), dtype=np.int64)
    rid[:, n // 2:] = 1
    with _quiet():
        std = SparseMaternPrior(sigma=sigma, length_km=L, shape=(n, n), dx_km=dx, region_id=rid,
                                standardize=True)
    assert std.n > _obs._EXACT_MAX_N, std.n                 # the whole point: the MC fallback branch

    # every method returns EXACTLY sigma^2 -- including "exact", which does not hit its n guard here
    # because standardize short-circuits before it, and "analytic", which does not warn under it
    for method in ("mc", "analytic", "exact"):
        with warnings.catch_warnings():
            warnings.simplefilter("error")                  # no warning is correct under standardize
            got = std.marginal_var(method=method, n_samples=8)
        assert np.max(np.abs(got - sigma ** 2)) == 0.0, method

    # ...but the TRUE diag(D B D), on a sample of cells (dense_cov() is unavailable above the guard),
    # is only sigma^2 to the Monte-Carlo accuracy of the diag(B) the congruence was built from
    cells = np.arange(0, std.n, 37)
    e = np.zeros((std.n, cells.size))
    e[cells, np.arange(cells.size)] = 1.0
    true_diag = np.einsum("ij,ij->j", std.solve(e), e)
    rel = true_diag / sigma ** 2 - 1.0
    assert np.abs(rel).max() > 0.005, np.abs(rel).max()     # NOT exact -- the documented gap is real
    assert np.abs(rel).max() < 0.12, np.abs(rel).max()      # measured 0.078 near the divide
    assert np.sqrt((rel ** 2).mean()) < 0.05, np.sqrt((rel ** 2).mean())    # measured 0.026 rms
    assert (rel > 0).any() and (rel < 0).any()              # unbiased-ish: it errs in both directions

    # and the downstream consequence: pre-clip resolution CAN exceed 1, the clip is what stops it
    worst = int(cells[int(np.argmax(true_diag))])
    g = np.zeros((1, std.n))
    g[0, worst] = 1.0                                       # a near-perfect observation of that cell
    var_prior = std.marginal_var()                          # sigma^2 exactly, by construction
    x = std.solve(g.T)
    pre_clip = float(x[worst, 0] ** 2 / (g @ x + 1e-10)[0, 0] / var_prior[worst])
    assert pre_clip > 1.0, pre_clip                         # measured 1.070
    res, var_post = resolution_precision(std, g, 1e-10, var_prior=var_prior)
    assert res.max() <= 1.0 and res.min() >= 0.0            # ...clipped, exactly as on the dense path
    assert var_post.min() >= 0.0
    assert res[worst] == 1.0 and var_post[worst] == 0.0     # saturated, one-sidedly


# --- edge cases beyond the spec ---------------------------------------------------------------------

def test_constructor_rejects_every_configuration_it_cannot_represent():
    """The class's validity domain, enforced rather than documented.

    ``nu != 1`` is the important one: a sparse local precision exists in 2-D only for integer alpha, so
    silently accepting nu=1.5 (the dense default!) would hand back a *different field* than asked for.
    A non-uniform grid is refused by construction -- the class takes spacings, not coordinates -- which
    is why there is no test for it here beyond the positivity of dx/dy.
    """
    ok = {"sigma": 1.0, "length_km": 4.0, "shape": (9, 9), "dx_km": 0.5}
    with pytest.raises(ValueError, match="nu=1.0 only"):
        SparseMaternPrior(**ok, nu=1.5)                            # the dense default is NOT accepted
    for nu in (0.5, 2.0, 2.5, 0.0):
        with pytest.raises(ValueError):
            SparseMaternPrior(**ok, nu=nu)
    for bad in ({"sigma": 0.0}, {"sigma": -1.0}, {"sigma": np.nan}, {"length_km": -2.0},
                {"length_km": np.inf}, {"dx_km": 0.0}, {"dx_km": np.nan}, {"dy_km": -1.0},
                {"shape": (0, 9)}, {"shape": (9,)}, {"shape": (3, 3, 3)}, {"shape": 9},
                {"shape": (9.5, 9)}, {"solver": "lu"}):
        with pytest.raises((ValueError, TypeError)):
            with _quiet():
                SparseMaternPrior(**(ok | bad))
    with pytest.raises(ValueError):                                # region_id inconsistent with shape
        SparseMaternPrior(**ok, region_id=np.zeros(80, dtype=np.int64))
    with pytest.raises(ValueError):
        SparseMaternPrior(**ok, region_id=np.zeros((8, 9), dtype=np.int64))
    with _quiet():                                                 # both accepted spellings work
        assert SparseMaternPrior(**ok, region_id=np.zeros(81, dtype=np.int64)).n == 81
        assert SparseMaternPrior(**ok, region_id=np.zeros((9, 9), dtype=np.int64)).n == 81


def test_a_one_by_one_grid_is_the_isolated_cell_limit_not_a_crash():
    """Degenerate geometry: no edges at all. K~ = kappa^2, so B = sigma^2/(tau^2 h kappa^4)."""
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(1, 1), dx_km=0.5)
    assert p.n == 1
    v = p.marginal_var(method="exact")
    assert v.shape == (1,)
    assert abs(v[0] - 1.0 / (p.tau ** 2 * p.dx_km ** 2 * p.kappa ** 4)) < 1e-9 * v[0]
    with _quiet():                                                  # 1-D strips must work too
        strip = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(1, 12), dx_km=0.5)
    assert strip.marginal_var(method="exact").shape == (12,)
    assert np.all(strip.marginal_var(method="exact") > 0)


def test_positive_definiteness_survives_ANY_region_labelling():
    """Spec §5's proof, tested: ``L_G >= 0`` for every edge subset, so ``K~ >= kappa^2 I > 0``.

    Including labellings that disconnect the graph entirely (every cell its own region) or checkerboard
    it (no edge survives at all). This is where the GMRF is structurally better than masking a dense
    kernel: PSD follows from the operator, not from the mask being an equivalence relation.
    """
    side = 20
    rng = np.random.default_rng(0)
    labellings = {
        "random": rng.integers(0, 7, size=(side, side)),
        "checkerboard (no edge survives)": (np.indices((side, side)).sum(0) % 2),
        "every cell isolated": np.arange(side * side).reshape(side, side),
        "one stripe": (np.indices((side, side))[1] // 3),
    }
    for name, rid in labellings.items():
        with _quiet():
            p = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(side, side), dx_km=0.5,
                                  region_id=rid.astype(np.int64))
        ev = eigvalsh(p.precision().toarray())
        assert ev.min() > 0.0, name
        # the exact lower bound, too: lambda_min(K~) = kappa^2 whatever the labelling
        assert abs(eigvalsh(_ktilde(p).toarray()).min() / p.kappa ** 2 - 1.0) < 1e-12, name
        assert ev.min() >= p.tau ** 2 * p.dx_km ** 2 * p.kappa ** 4 * (1.0 - 1e-9), name


def test_estimator_entry_points_reproduce_the_dense_path_contract():
    """Empty G, bad d, bad noise_var, bad var_prior, and dense/sparse G parity.

    The sparse estimators are documented as behaving exactly like the dense ones at their edges; if
    an empty observation set returned something other than "zero resolution, prior variance", every
    marginal-gain map built on them would be wrong at the baseline.
    """
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(9, 9), dx_km=0.5)
    n = p.n
    v = p.marginal_var(method="exact")
    for empty in (np.empty((0, n)), np.array([])):
        res, vpost = resolution_precision(p, empty, 0.02, var_prior=v)
        assert np.all(res == 0.0) and np.allclose(vpost, v)
        m_a, vpost = blue_update_precision(p, empty, np.array([]), 0.02, prior_mean=2.5, var_prior=v)
        assert np.allclose(m_a, 2.5) and np.allclose(vpost, v)

    g = np.zeros((2, n))
    g[0, 0] = 1.0
    g[1, 40] = 1.0
    with pytest.raises(ValueError):                                # d must be length n_obs
        blue_update_precision(p, g, np.array([1.0]), 0.02, var_prior=v)
    with pytest.raises(ValueError):                                # noise_var scalar or length n_obs
        blue_update_precision(p, g, np.array([1.0, 2.0]), np.array([1.0, 2.0, 3.0]), var_prior=v)
    with pytest.raises(ValueError):                                # var_prior must be length n
        resolution_precision(p, g, 0.02, var_prior=np.ones(5))
    with pytest.raises(ValueError):                                # G's cell axis must match the grid
        resolution_precision(p, np.zeros((2, n + 3)), 0.02, var_prior=v)

    ref_res, _ = resolution_precision(p, g, 0.02, var_prior=v)
    ref_ma, _ = blue_update_precision(p, g, np.array([1.0, -2.0]), 0.02, prior_mean=0.3, var_prior=v)
    for ctor in (sparse.csr_matrix, sparse.csc_matrix, sparse.coo_matrix, sparse.csr_array):
        res, _ = resolution_precision(p, ctor(g), 0.02, var_prior=v)
        m_a, _ = blue_update_precision(p, ctor(g), np.array([1.0, -2.0]), 0.02, prior_mean=0.3,
                                       var_prior=v)
        assert np.max(np.abs(res - ref_res)) == 0.0, ctor.__name__   # sparse G is a representation,
        assert np.max(np.abs(m_a - ref_ma)) == 0.0, ctor.__name__    # not a different estimator
    # and resolution stays a fraction, exactly as on the dense path
    assert np.all(ref_res >= -1e-12) and np.all(ref_res <= 1.0 + 1e-12)


def test_the_four_mandated_geometry_warnings_fire():
    """Resolution, padding, no-interior and small-region: the class must SAY when it is artifact-bound.

    These are not decoration. A user who pads by less than one practical range gets a variance inflated
    by up to x3.8 at the corner; a user with HUC-sized ``region_id`` units gets up to x395; a user
    below 8 cells per practical range gets a discretization error nothing has ever measured. Silence
    there would be the worst failure mode this class has, because the numbers still *look* plausible.

    The fourth (kappa*max(dx,dy) > 0.36, approximation 2) has its own test below; here it only has to
    stay OUT of the cases that are about the other three, and it is what the "must be silent" case
    turns on: a domain can be generously *padded* and still badly under-*resolved*. This test used to
    assert silence for ``length_km=1.0, shape=(60,60), dx_km=0.5`` -- 30 km across for a 2 km range, so
    15 ranges of padding, but only 4 cells per range (kappa*dx = 0.707, the very configuration this
    repo's 2 km assimilation grid sits at). That premise was wrong, not the warning.
    """
    def emitted(**kw):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            SparseMaternPrior(**kw)
        return [str(w.message) for w in caught if issubclass(w.category, UserWarning)]

    # A 10 km domain with an 8 km practical range cannot hold 1 range of padding on ANY side, and is
    # also below 3 ranges: BOTH warnings must fire. Matching on text unique to each is deliberate --
    # the "no interior" message also contains the phrase "practical range", so a looser matcher would
    # let a removed padding warning pass unnoticed.
    both = emitted(sigma=1.0, length_km=4.0, shape=(20, 20), dx_km=0.5)
    assert any("cannot hold the" in m for m in both), both           # padding
    assert any("no stationary interior" in m for m in both), both    # no interior
    # 20 km domain: wide enough for the padding (>= 2 ranges) but not for an interior (< 3 ranges),
    # so EXACTLY the second warning fires -- a warning that always fires carries no information.
    only_interior = emitted(sigma=1.0, length_km=4.0, shape=(40, 40), dx_km=0.5)
    assert len(only_interior) == 1 and "no stationary interior" in only_interior[0], only_interior
    rid = np.zeros((60, 60), dtype=np.int64)
    rid[10:12, 10:12] = 1                                            # a 1 km^2 region, range^2 = 64 km^2
    small = emitted(sigma=1.0, length_km=4.0, shape=(60, 60), dx_km=0.5, region_id=rid)
    assert len(small) == 1 and "smaller than one" in small[0], small
    assert "standardize=True" in small[0]                            # it must name the mitigation
    # A well-padded AND well-resolved domain with no region_id must be SILENT -- a warning that always
    # fires is noise. 12 km across for a 2 km practical range = 6 ranges of padding, and dx = 0.2 km is
    # 10 cells per range (kappa*dx = 0.283, inside the measured band). All four must hold their peace.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        SparseMaternPrior(sigma=1.0, length_km=1.0, shape=(60, 60), dx_km=0.2)
    # method="analytic" must warn: it returns sigma^2 everywhere and is wrong near every boundary
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=1.0, shape=(30, 30), dx_km=0.5)
    with pytest.warns(UserWarning, match="analytic"):
        assert np.all(p.marginal_var(method="analytic") == 1.0)


def test_the_kappa_dx_resolution_warning_fires_on_the_COARSER_axis():
    """The fourth warning (approximation 2): fewer than ~8 cells per practical range.

    This is the only approximation in the class with a hard numeric threshold, and it is the one this
    repo actually violates: the 2 km coarsened assimilation grid at L = 4 km sits at kappa*dx = 0.707,
    ~2x past the limit, where the 5-point discretization error is EXTRAPOLATED rather than measured
    (nothing was ever benchmarked past kappa*dx = 0.354). A silent extrapolation is the failure mode.

    Three separate claims, and the third is the one an obvious implementation gets wrong:

    1. it fires above 0.36;
    2. it is SILENT at and below it -- in particular at kappa*dx = 0.354, the coarsest case §7.1
       actually measured (max|drho| = 0.029), which must stay usable without a warning or the warning
       is contradicting the benchmark it cites;
    3. it keys on ``max(dx, dy)``, the COARSER axis. Accuracy is limited by the worse-resolved
       direction, so a ``min`` (or a dx-only test) would stay quiet on a grid that is fine in x and
       useless in y. Both orientations are checked, because a dx-only test passes one of them.

    Every geometry here is >= 3 practical ranges across so the padding and no-interior warnings cannot
    fire; ``emitted`` therefore returns the resolution warning alone or nothing at all.
    """
    def emitted(**kw):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            SparseMaternPrior(**kw)
        return [str(w.message) for w in caught if issubclass(w.category, UserWarning)]

    kap = np.sqrt(2.0) / 1.0                                     # length_km = 1.0 => range 2 km

    # 1. fires. kappa*dx = 0.424 on a 7.2 km domain (3.6 ranges: padded and with an interior).
    fired = emitted(sigma=1.0, length_km=1.0, shape=(24, 24), dx_km=0.3)
    assert len(fired) == 1, fired
    assert "kappa*max(dx,dy) = 0.424" in fired[0], fired
    assert "EXTRAPOLATED" in fired[0], fired                     # it must say WHY, not just that
    assert "0.255 km" in fired[0], fired                         # ...and what dx would be acceptable
    # and the repo's own 2 km assimilation grid (kappa*dx = 0.707) is squarely inside the warned band
    assert kap * 0.5 > _obs._KAPPA_DX_MAX

    # 2. silent at and below the threshold, including at the coarsest MEASURED case, kappa*dx = 0.354
    assert emitted(sigma=1.0, length_km=4.0, shape=(81, 81), dx_km=1.0) == []       # 0.354, spec §7.1
    just_under = 0.99 * _obs._KAPPA_DX_MAX / kap                                    # 0.252 km
    just_over = 1.01 * _obs._KAPPA_DX_MAX / kap                                     # 0.257 km
    assert emitted(sigma=1.0, length_km=1.0, shape=(40, 40), dx_km=just_under) == []
    assert len(emitted(sigma=1.0, length_km=1.0, shape=(40, 40), dx_km=just_over)) == 1

    # 3. the COARSER axis, in both orientations. Each grid is fine on one axis (kappa*d = 0.141) and
    #    coarse on the other (0.424); a min() or a dx-only check would be silent on one of the two.
    coarse_dy = emitted(sigma=1.0, length_km=1.0, shape=(24, 70), dx_km=0.1, dy_km=0.3)
    coarse_dx = emitted(sigma=1.0, length_km=1.0, shape=(70, 24), dx_km=0.3, dy_km=0.1)
    for msg in (coarse_dy, coarse_dx):
        assert len(msg) == 1 and "0.424" in msg[0], msg
    # ...and an anisotropic grid that is fine on BOTH axes stays silent, so it is not just "dx != dy"
    assert emitted(sigma=1.0, length_km=1.0, shape=(24, 70), dx_km=0.1, dy_km=0.25) == []


def test_monte_carlo_clips_and_reports_a_non_positive_variance_estimate():
    """With too few samples the split-plus-control-variate estimate can go negative; it must not pass silently.

    A negative prior variance would make ``resolution()``'s ratio meaningless (and ``information_gain``
    take a log of a negative number). The implementation clips to a tiny positive floor AND warns; both
    halves matter -- clipping alone would hide the fact that ``n_samples`` was far too small.
    """
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(21, 21), dx_km=0.5)
    with pytest.warns(UserWarning, match="non-positive"):
        est = p.marginal_var(method="mc", n_samples=1, rng=np.random.default_rng(1))
    assert np.all(est > 0.0)
    with _quiet():                                                   # ...and a healthy K does not warn
        healthy = p.marginal_var(method="mc", n_samples=512, rng=np.random.default_rng(0))
    assert np.all(healthy > 0.0)


def test_cg_solver_agrees_with_the_direct_factorization():
    """``solver="cg"`` is the O(n)-memory fallback above n ~ 2e6; it must give the same answer.

    Checked to the CG tolerance (rtol 1e-10) on both a random right-hand side and the full diagonal --
    if the fallback quietly disagreed, the only grids where it is *used* are the ones too large to
    cross-check.
    """
    for side in (41, 61):
        with _quiet():
            direct = SparseMaternPrior(1.0, 4.0, (side, side), 0.5, solver="splu")
            iterative = SparseMaternPrior(1.0, 4.0, (side, side), 0.5, solver="cg")
        v = np.random.default_rng(0).normal(size=direct.n)
        xd, xi = direct.solve(v), iterative.solve(v)
        assert np.max(np.abs(xd - xi)) < 1e-8 * np.max(np.abs(xd))
        vd = direct.marginal_var(method="exact")
        vi = iterative.marginal_var(method="exact")
        assert np.max(np.abs(vd - vi)) < 1e-8 * vd.max()


def test_solver_auto_actually_switches_to_CG_above_the_documented_n_and_agrees_with_splu():
    """``solver="auto"`` is the DEFAULT, and its CG branch is the one that runs at issue #163's scale.

    Both branches are individually correct (the test above pins ``solver="cg"`` explicitly), but that
    says nothing about the *switch*: at n = 1e7 nobody passes ``solver="cg"`` by hand, ``"auto"``
    picks it, and a wrong comparison or a missing ``self.solver == "auto"`` clause would fall through
    to ``splu`` and try to hold a ~20 GB factor. Since a 2e6-cell grid is not a unit test, the
    threshold constant is lowered instead of the grid being raised -- the branch is the same branch.

    Both halves are asserted: that the CG closure is the object actually cached (a numeric agreement
    alone would also pass if ``auto`` had quietly kept using ``splu``), and that it agrees with the
    direct factorization to the CG tolerance.
    """
    side = 41
    with _quiet():
        direct = SparseMaternPrior(1.0, 4.0, (side, side), 0.5, solver="splu")
        auto_small = SparseMaternPrior(1.0, 4.0, (side, side), 0.5, solver="auto")
        auto_big = SparseMaternPrior(1.0, 4.0, (side, side), 0.5, solver="auto")
    assert auto_small.n > 100                      # ...so the patched threshold below really bites
    assert auto_small.n < _obs._SPLU_MAX_N         # and the unpatched one does not

    v = np.random.default_rng(0).normal(size=direct.n)
    with _patched("_SPLU_MAX_N", 100):             # n = 1681 > 100 => the CG branch
        x_auto = auto_big.solve(v)                 # forces (and caches) the factor inside the branch
        assert getattr(auto_big._factor(), "__name__", "") == "solve_cg", auto_big._factor()
        v_auto = auto_big.marginal_var(method="exact")
    assert getattr(auto_small._factor(), "__name__", "") != "solve_cg"   # unpatched auto: still splu

    x_direct = direct.solve(v)
    assert np.max(np.abs(x_auto - x_direct)) < 1e-8 * np.max(np.abs(x_direct))
    v_direct = direct.marginal_var(method="exact")
    assert np.max(np.abs(v_auto - v_direct)) < 1e-8 * v_direct.max()


def test_sample_draws_have_the_right_covariance_and_solve_inverts_the_precision():
    """``A`` really is a symmetric square root of ``Q``: draws are exact, and ``solve`` is ``Q^-1``.

    ``sample()`` costs ONE solve per draw (that is the practical reason alpha=2 was chosen), and
    ``marginal_var(method="mc")`` is built on it -- so if the square root were wrong, the default
    variance path would be biased with nothing to catch it.
    """
    with _quiet():
        p = SparseMaternPrior(sigma=1.4, length_km=3.0, shape=(15, 15), dx_km=0.5)
    q = p.precision()
    ident = q @ p.solve(np.eye(p.n))                                 # Q Q^-1 = I
    assert np.max(np.abs(ident - np.eye(p.n))) < 1e-9
    a = p.operator()
    assert abs((a - a.T)).max() == 0.0                               # the square root is SYMMETRIC
    assert abs((a.T @ a) - q).max() < 1e-9 * abs(q).max()            # ...and Q = A^T A
    draws = p.sample(6000, rng=np.random.default_rng(2))
    assert draws.shape == (6000, p.n)
    emp = np.cov(draws, rowvar=False)
    exact = p.dense_cov()
    assert np.max(np.abs(np.diag(emp) - np.diag(exact))) < 0.08 * np.max(np.diag(exact))
    assert np.max(np.abs(emp - exact)) < 0.10 * np.max(np.diag(exact))
    # solve() accepts (n,) and (n, m) and is consistent between them
    rhs = np.random.default_rng(4).normal(size=(p.n, 3))
    assert np.max(np.abs(p.solve(rhs)[:, 1] - p.solve(rhs[:, 1]))) < 1e-9


def test_the_dense_X_budget_refuses_a_huge_request_without_allocating_anything():
    """``X = Q^-1 G^T`` is DENSE ``(n, n_obs)`` -- the one place the O(n) claim stops (approximation 10).

    The prior at n = 1e6 is a few tens of MB of sparse precision, so nothing about *constructing* it
    warns you that ``resolution_precision`` with 1100 observations wants 8.8 GB for one ``X`` and
    ~35 GB at peak. Without the check the process thrashes or the OOM killer takes it; with it the
    caller gets a message naming the size and the fix. The check is cheap to test precisely because it
    happens **before** anything is materialized: the prior is lazy (no operator, no factor) and
    ``_prior_var`` short-circuits on a supplied ``var_prior``, so this whole test allocates ~8 MB.

    Also asserted: the budget counts the PEAK, ``_X_PEAK_MULT`` (= 4) simultaneous ``(n, n_obs)``
    arrays, not one. Budgeting 1x would admit ~4x the memory it thinks it is admitting -- the
    difference between refusing at 8 GB and being killed at 32.
    """
    n_side, n_obs = 1000, 1100
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(n_side, n_side), dx_km=0.5)
    n = p.n
    g = sparse.csr_matrix((np.ones(n_obs), (np.arange(n_obs), (np.arange(n_obs) * 907) % n)),
                          shape=(n_obs, n))
    var_prior = np.full(n, 1.0)                      # supplied, so no Monte Carlo is ever run

    tracemalloc.start()
    try:
        with pytest.raises(ValueError) as err:
            resolution_precision(p, g, 0.02, var_prior=var_prior)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    msg = str(err.value)
    assert f"n_obs={n_obs}" in msg and "8.8 GB" in msg, msg          # 8*n*n_obs for one array
    assert "35.2 GB" in msg, msg                                     # ...and 4x that at peak
    assert "budget" in msg and "Chunk over observation columns" in msg, msg
    assert peak < 1e6, peak       # nothing (n, n_obs) was formed: measured ~2 kB inside the raises
    assert "factor" not in p._cache and "tau" not in p._cache        # the prior stayed entirely lazy
    # the arithmetic is exactly _X_PEAK_MULT * 8 * n * n_obs against _X_MAX_BYTES, bracketed by
    # lowering the budget on a tiny grid: a request that fits must still go through.
    with _quiet():
        small = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(9, 9), dx_km=0.5)
    tiny_g = np.zeros((2, small.n))
    tiny_g[0, 0] = tiny_g[1, 40] = 1.0
    need = _obs._X_PEAK_MULT * 8.0 * small.n * 2
    with _patched("_X_MAX_BYTES", 2.0 * need):                       # comfortably inside
        res, _ = resolution_precision(small, tiny_g, 0.02, var_prior=np.ones(small.n))
        assert np.all(np.isfinite(res))
    with _patched("_X_MAX_BYTES", 0.5 * need):                       # ...and just outside
        with pytest.raises(ValueError, match="budget"):
            resolution_precision(small, tiny_g, 0.02, var_prior=np.ones(small.n))


def test_the_reduction_clip_keeps_resolution_a_fraction_when_var_prior_is_an_ESTIMATE():
    """``var_prior`` is normally a Monte-Carlo ``diag(B)``, so it can sit BELOW the true diagonal.

    ``reduction`` is computed from the exact ``B`` (through ``X = Q^-1 G^T``) while the denominator is
    the supplied estimate, so the two are not forced to be consistent: an underestimated ``var_prior``
    at a well-observed cell gives ``reduction > var_prior``, i.e. resolution above 1 and a NEGATIVE
    posterior variance -- which then makes :func:`information_gain` take the log of a negative number.
    The dense path carries a ``np.clip(reduction, 0, var_prior)`` guard for exactly this and the sparse
    path must carry the same one. Passing a deliberately-too-small ``var_prior`` is the reproducing case.
    """
    with _quiet():
        p = SparseMaternPrior(sigma=1.0, length_km=4.0, shape=(15, 15), dx_km=0.5)
    exact = p.marginal_var(method="exact")
    g = np.zeros((1, p.n))
    g[0, p.n // 2] = 1.0                                           # a near-perfect point observation
    under = exact * 0.5                                            # an estimate that is 2x too small
    res, var_post = resolution_precision(p, g, 1e-8, var_prior=under)
    assert np.all(res <= 1.0) and np.all(res >= 0.0)
    assert np.all(var_post >= 0.0)
    _, var_post_blue = blue_update_precision(p, g, np.array([1.0]), 1e-8, var_prior=under)
    assert np.all(var_post_blue >= 0.0)
    # with a CONSISTENT var_prior the clip must be inert -- it is a guard, not a correction
    res_ok, vp_ok = resolution_precision(p, g, 1e-8, var_prior=exact)
    assert np.all(res_ok < 1.0 - 1e-12) and np.all(vp_ok > 0.0)
