r"""The hydrologic state vocabulary: storage, water-table head, depth to water, aquifer head, pore pressure.

This module exists because five physically distinct quantities were being carried under three
interchangeable names (``GWL``, ``head``, ``WTD``/``DTW``). They are *not* interchangeable, and the
places where they were treated as such produced two specific errors: a spatial prior fitted to the
wrong field, and a screened-aquifer well used as if it pinned the shallow water table.

## The five quantities

===========================  ==========================================================================
symbol                       meaning
===========================  ==========================================================================
:math:`z_s(x)`               land-surface elevation (m, vertical datum; NAVD88 here)
:math:`S(x,t)`               **groundwater storage** per unit area (m of water) — the *canonical
                             evolving state* in the target architecture (issue #187)
:math:`h_{wt}(x,t)`          **water-table head**: elevation of the phreatic surface in an
                             *unconfined* aquifer (m, same datum as :math:`z_s`)
:math:`D(x,t)`               **depth to water table** (DTW / WTD), positive downward,
                             :math:`D = z_s - h_{wt}`
:math:`H(x,z,t)`             **hydraulic head at depth**, :math:`H = z + p/(\rho_w g)`. At the phreatic
                             surface gauge pressure is zero and :math:`H = h_{wt}`; in a confined,
                             semiconfined, perched or artesian interval it is *not* the water table.
:math:`u(x,z,t)`             **pore-water pressure** at depth :math:`z` — the quantity slope stability
                             actually consumes, through :math:`\sigma' = \sigma - u`
===========================  ==========================================================================

## The invariant that removes a whole class of modelling error

Land-surface elevation is fixed in time, so differencing :math:`D = z_s - h_{wt}` gives

.. math::  \Delta D(x,t) = -\,\Delta h_{wt}(x,t) .

A water-table-**depth** anomaly and a water-table-**head** anomaly are therefore the same random
variable up to sign. They have identical variance and identical covariance,

.. math::  \mathrm{Cov}\big(\Delta D(x), \Delta D(x')\big) = \mathrm{Cov}\big(\Delta h_{wt}(x), \Delta h_{wt}(x')\big),

so they must **not** be given separate Matérn :math:`(\sigma, L, \nu)` fits or separate prior
configurations. Only the sign of the mean update flips. :func:`assert_anomaly_covariance_identity`
and the tests in ``tests/test_hydro_state.py`` pin this.

Note what the invariant does *not* say: it is a statement about **anomalies**. The *absolute* fields
differ by the deterministic, strongly structured :math:`z_s`, which is exactly why the spatial GP
prior belongs on the residual/anomaly and not on the absolute DTW landscape (see
:mod:`src.models.observability` and ``docs/twin/04-assimilation.qmd``).

## Storage first, head and DTW diagnosed

The **target** cycling state is storage; head and DTW are diagnostics of it:

.. code-block:: text

    S_groundwater  ->  h_wt  ->  D  ->  u(z)  ->  hazard variables

:func:`water_table_head_from_storage` implements the storage-to-head step under an explicitly named
specific-yield assumption. The uncertainty in :math:`S_y` propagates into the diagnosed head and is
returned rather than hidden (issues #137/#171/#172).

The **current** snapshot BLUE does not do this: it carries a water-table *anomaly* as the reduced
analysis variable. That is a statement about what the code does today, not about the target
architecture; see ``docs/reviews/hydrology-geostatistics-prior-audit-2026-08.md``.

## Hydrostatic assumptions are named, never hidden

:func:`pore_pressure_hydrostatic_below_water_table` carries "hydrostatic" in its name because the
conversion is only valid under that assumption. A generic ``pore_pressure_from_head`` utility would
let a slope-stability caller silently inherit a hydrostatic groundwater condition it never chose
[@bogaard2016landslidehydrology]. Under slope-parallel flow the head gradient is not vertical and the
pressure at a failure surface is smaller than the hydrostatic value by
:math:`\cos^2\beta`; :func:`pore_pressure_slope_parallel` provides that variant, also explicitly named.
"""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import ArrayLike, NDArray

RHO_W: Final[float] = 1000.0        # density of fresh water (kg m^-3)
G: Final[float] = 9.80665           # standard gravity (m s^-2)

#: Plausible range for **unconfined specific yield** :math:`S_y`. Reported values for granular
#: aquifers span roughly 0.01-0.35; the upper bound here is porosity-ish and the lower bound is set
#: to keep a *confined* storativity (:math:`S = S_s b \sim 10^{-5}`-:math:`10^{-3}`) out. Anything
#: below it is almost certainly a storativity, for which a head change is not a water-table movement.
SPECIFIC_YIELD_RANGE: Final[tuple[float, float]] = (0.005, 0.6)


def _check_specific_yield(specific_yield: ArrayLike) -> None:
    """Raise if any finite value falls outside :data:`SPECIFIC_YIELD_RANGE` (the storativity trap)."""
    lo, hi = SPECIFIC_YIELD_RANGE
    sy = np.asarray(specific_yield, dtype="float64")
    bad = np.isfinite(sy) & ((sy < lo) | (sy > hi))
    if np.any(bad):
        got = float(np.asarray(sy)[bad].ravel()[0]) if sy.ndim else float(sy)
        raise ValueError(
            f"specific_yield must lie in [{lo}, {hi}], got {got!r}. Values far below this range are "
            "a CONFINED storativity S = S_s*b, for which a head change is not a water-table movement "
            "at all -- use an aquifer-head diagnostic, not this function.")


# --- water table <-> depth to water ---------------------------------------------------------------

def dtw_from_water_table_elevation(z_surface_m: ArrayLike, h_wt_m: ArrayLike) -> NDArray[np.float64]:
    r"""Depth to water table :math:`D = z_s - h_{wt}` (m, **positive downward**).

    ``z_surface_m`` and ``h_wt_m`` must be in the *same* vertical datum. A negative result means the
    water table stands above the land surface (a flowing/artesian or ponded condition) and is
    returned as such rather than clipped — clipping would silently convert an artesian observation
    into a zero-depth water table.
    """
    return np.asarray(z_surface_m, dtype="float64") - np.asarray(h_wt_m, dtype="float64")


def water_table_elevation_from_dtw(z_surface_m: ArrayLike, dtw_m: ArrayLike) -> NDArray[np.float64]:
    r"""Water-table head :math:`h_{wt} = z_s - D` (m, same datum as ``z_surface_m``)."""
    return np.asarray(z_surface_m, dtype="float64") - np.asarray(dtw_m, dtype="float64")


def dtw_anomaly_from_head_anomaly(delta_h_wt_m: ArrayLike) -> NDArray[np.float64]:
    r"""Convert a water-table-head anomaly to a DTW anomaly: :math:`\Delta D = -\Delta h_{wt}`.

    Land-surface elevation is time-invariant, so this is exact — no baseline, no datum, no parameter.
    It is a *sign flip*, which is precisely why the two anomalies cannot carry independent prior
    covariances.
    """
    return -np.asarray(delta_h_wt_m, dtype="float64")


def head_anomaly_from_dtw_anomaly(delta_dtw_m: ArrayLike) -> NDArray[np.float64]:
    r"""Convert a DTW anomaly to a water-table-head anomaly: :math:`\Delta h_{wt} = -\Delta D`."""
    return -np.asarray(delta_dtw_m, dtype="float64")


def assert_anomaly_covariance_identity(cov_head: ArrayLike, cov_dtw: ArrayLike,
                                       atol: float = 1e-12) -> None:
    r"""Raise unless :math:`\mathrm{Cov}(\Delta D) = \mathrm{Cov}(\Delta h_{wt})` to ``atol``.

    A guard for configuration code: if two separate prior blocks are ever built for "WTD anomaly" and
    "water-table-head anomaly", this fails loudly instead of letting the twin carry two mutually
    inconsistent covariance models for one random field.
    """
    a = np.asarray(cov_head, dtype="float64")
    b = np.asarray(cov_dtw, dtype="float64")
    if a.shape != b.shape:
        raise ValueError(f"covariance shapes differ: {a.shape} vs {b.shape}")
    if not np.allclose(a, b, atol=atol, rtol=0.0):
        worst = float(np.nanmax(np.abs(a - b)))
        raise ValueError(
            "water-table-head and DTW anomaly covariances differ by up to "
            f"{worst:.3e}; they are the SAME random field up to sign (Delta D = -Delta h_wt) and "
            "must not be given separate (sigma, L, nu) configurations")


# --- storage -> head (the target architecture's first diagnostic step) -----------------------------

def water_table_head_from_storage(storage_anomaly_m: ArrayLike, specific_yield: ArrayLike,
                                  h_wt_reference_m: ArrayLike = 0.0,
                                  specific_yield_sigma: ArrayLike | None = None
                                  ) -> tuple[NDArray[np.float64], NDArray[np.float64] | None]:
    r"""Diagnose water-table head from a groundwater **storage** anomaly (issues #137/#171/#172).

    For an unconfined aquifer draining/filling at its phreatic surface, a storage change
    :math:`\Delta S` (expressed as a depth of water, m) raises the table by

    .. math::  \Delta h_{wt} = \Delta S / S_y ,

    with :math:`S_y` the specific yield. This is the storage-first contract's first diagnostic step:
    storage is the canonical evolving state, head is *derived* from it, and DTW is derived from head.

    The conversion is only as good as :math:`S_y`, which is poorly known and spatially variable, so
    the uncertainty is propagated rather than dropped. Given ``specific_yield_sigma``, first-order
    propagation of :math:`\Delta h = \Delta S / S_y` gives

    .. math::  \sigma_{\Delta h} = \big|\Delta S / S_y^2\big|\,\sigma_{S_y}
                                 = \big|\Delta h_{wt}\big|\,\sigma_{S_y}/S_y ,

    i.e. the *relative* uncertainty in head equals the relative uncertainty in :math:`S_y`. Returns
    ``(h_wt, sigma_h_wt)``; ``sigma_h_wt`` is ``None`` when no ``specific_yield_sigma`` is given.

    This is a **confined-aquifer trap**: for a confined interval the storage coefficient is the
    storativity :math:`S = S_s b`, three to five orders of magnitude smaller than :math:`S_y`, and the
    resulting head change is *not* a water-table movement at all. Passing a storativity here would
    produce a nonsense "water table" inflated by the same three to five orders of magnitude. The
    function therefore rejects values outside :data:`SPECIFIC_YIELD_RANGE`, the plausible range for
    unconfined specific yield.
    """
    _check_specific_yield(specific_yield)
    sy = np.asarray(specific_yield, dtype="float64")
    ds = np.asarray(storage_anomaly_m, dtype="float64")
    dh = ds / sy
    h_wt = np.asarray(h_wt_reference_m, dtype="float64") + dh
    if specific_yield_sigma is None:
        return h_wt, None
    sig = np.abs(dh) * np.asarray(specific_yield_sigma, dtype="float64") / sy
    return h_wt, sig


def storage_from_water_table_head(delta_h_wt_m: ArrayLike, specific_yield: ArrayLike
                                  ) -> NDArray[np.float64]:
    r"""Inverse of :func:`water_table_head_from_storage`: :math:`\Delta S = S_y\,\Delta h_{wt}` (m)."""
    _check_specific_yield(specific_yield)
    return np.asarray(specific_yield, dtype="float64") * np.asarray(delta_h_wt_m, dtype="float64")


# --- head -> pore pressure (named assumptions only) ------------------------------------------------

def pore_pressure_hydrostatic_below_water_table(h_wt_m: ArrayLike, z_m: ArrayLike,
                                                rho_w: float = RHO_W, g: float = G
                                                ) -> NDArray[np.float64]:
    r"""Pore pressure at elevation ``z_m`` **under an explicit hydrostatic assumption** (Pa).

    .. math::  u(z) = \rho_w g\,(h_{wt} - z), \qquad u \equiv 0 \ \text{above the water table}.

    Valid only where the vertical head gradient is zero — i.e. no vertical flow component. It is
    *not* valid during infiltration, in a perched system, above a capillary fringe treated as
    unsaturated, or on a hillslope with slope-parallel flow. Use
    :func:`pore_pressure_slope_parallel` for the last case.

    Suction above the water table is returned as zero rather than as a negative pressure: this
    function's contract is saturated-zone positive pore pressure only. A model that needs matric
    suction must go through the retention curve (:mod:`src.models.hysteresis`), not through here.
    """
    head_above = np.asarray(h_wt_m, dtype="float64") - np.asarray(z_m, dtype="float64")
    return rho_w * g * np.clip(head_above, 0.0, None)


def pore_pressure_slope_parallel(h_wt_m: ArrayLike, z_m: ArrayLike, slope_rad: ArrayLike,
                                 rho_w: float = RHO_W, g: float = G) -> NDArray[np.float64]:
    r"""Pore pressure at ``z_m`` under an explicit **slope-parallel** groundwater-flow assumption (Pa).

    For steady flow parallel to a hillslope of angle :math:`\beta`, the equipotentials are not
    horizontal and the pressure head at a point a vertical distance :math:`d = h_{wt}-z` below the
    water table is :math:`d\cos^2\beta`, so

    .. math::  u(z) = \rho_w g\,(h_{wt}-z)\,\cos^2\beta .

    This is the standard infinite-slope hydrologic closure and it is the assumption an infinite-slope
    factor of safety implicitly makes. At :math:`\beta = 0` it reduces to the hydrostatic case; at
    :math:`30^\circ` it is 25% smaller — a difference that matters directly in
    :math:`\sigma' = \sigma - u` [@bogaard2016landslidehydrology; @pelascini2022hillslope].
    """
    d = np.clip(np.asarray(h_wt_m, dtype="float64") - np.asarray(z_m, dtype="float64"), 0.0, None)
    cb = np.cos(np.asarray(slope_rad, dtype="float64"))
    return rho_w * g * d * cb ** 2


def pore_pressure_head_m(pressure_pa: ArrayLike, rho_w: float = RHO_W, g: float = G
                         ) -> NDArray[np.float64]:
    r"""Convert a pore pressure (Pa) to pressure head :math:`p/(\rho_w g)` (m of water)."""
    return np.asarray(pressure_pa, dtype="float64") / (rho_w * g)


def hydraulic_head_from_pressure(z_m: ArrayLike, pressure_pa: ArrayLike,
                                 rho_w: float = RHO_W, g: float = G) -> NDArray[np.float64]:
    r"""Hydraulic head at depth: :math:`H = z + p/(\rho_w g)` (m, elevation datum of ``z_m``).

    This is the quantity a **screened piezometer** measures for its own screened interval. Only when
    the screen straddles the phreatic surface of an unconfined aquifer does :math:`H` coincide with
    :math:`h_{wt}`; in a confined or perched interval it does not, and treating it as a water table
    is the error :mod:`src.features.well_hydrostratigraphy` exists to prevent.
    """
    return np.asarray(z_m, dtype="float64") + pore_pressure_head_m(pressure_pa, rho_w, g)
