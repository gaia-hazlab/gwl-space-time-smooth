"""Where a measured dv/v actually constrains the twin: the 2-D coda sensitivity of the network.

## The distinction this module exists to enforce

The twin evaluates ``dvv_high`` and ``dvv_low`` at **every 90 m cell**. That field is a **forward
prediction** — it is computed from the modelled soil moisture and water table through the petrophysical
coupling, and it exists everywhere the model exists. It is *not* a measurement.

A **measured** dv/v does not live at a cell. It is a property of a **station pair**: the coda of the
noise cross-correlation between two receivers samples the medium over an extended region, and its
sensitivity to a local velocity perturbation is a spatial kernel, not a point. Plotting the modelled
dv/v everywhere and calling it "dv/v" silently implies the network measures it everywhere, which it
does not.

This module makes the difference explicit: it computes **where the network is sensitive**, so that the
forward field can be separated into the part a measurement can constrain and the part that is
model-only.

## The kernel

For diffuse (multiply scattered) coda, the sensitivity of the travel-time change between receivers
:math:`r_1, r_2` at lapse time :math:`t` to a perturbation at :math:`s` is [Pacheco & Snieder, 2005]

.. math::
    K(s) = \\frac{\\int_0^t p(r_1, s, u)\\, p(s, r_2, t-u)\\, du}{p(r_1, r_2, t)},

with :math:`p` the intensity Green's function of the diffusion equation. In 2-D,

.. math::
    p(r, t) = \\frac{1}{4\\pi D t}\\, e^{-r^2/(4 D t)} .

The kernel is large near both stations and along the path between them, and it broadens with lapse
time — the coda samples further from the receivers, and deeper, the longer you wait. For dv/v that
tracks soil moisture and the shallow water table, the informative window is the **early coda** of the
shallow Rayleigh wavefield; a late window samples too deep.

## Two measurement geometries

**Inter-station** (cross-correlation) sensitivity bridges the two receivers — it is large *along the
path between* them. **Single-station** (autocorrelation) sensitivity sets :math:`s_1 = s_2`, so it is a
localised blob *at* the receiver. The two are complementary: combining them lets the between-station
region be isolated, because the path signal is the part of a pair kernel that the two single-station
kernels do not already account for. Single-station coda is also available at *every* station, so it
fills the gaps a sparse pair geometry leaves. The **network sensitivity** sums both,
:math:`S(x) = \\sum_{\\text{pairs}} K_{\\text{pair}}(x) + \\sum_{\\text{stations}} K_{\\text{auto}}(x)`.

## From sensitivity to a measurement uncertainty

A dv/v measurement constrains a cell in proportion to how strongly the coda samples it. Treating the
pairs as independent observations of the local perturbation, the posterior standard deviation of a
dv/v-derived state at a cell scales as

.. math::
    \\sigma(x) \\;\\propto\\; \\big[\\, S(x) \\,\\big]^{-1/2},

so cells with no sensitivity receive **no constraint at all** and must fall back on the model. This is
the spatial complement to codameter's *depth* sensitivity (``codameter.uq_depth``): together they say
*where* and *at what depth* a dv/v measurement carries information.

dv/v does not replace the wells or the soil-moisture sensors — it **complements** them. Wells observe
the saturated store at a point; SNOTEL observes the vadose store at a point; the coda samples a
*volume* between stations, and its shallow band responds to moisture on the timescale of individual
storms, which the wells cannot see.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

# Diffuse-coda parameters. Both are properties of the medium and the measurement window, not free
# knobs: D is the diffusivity of the scattered wavefield and t_lapse is the coda window in which dv/v
# is measured. Longer lapse time -> the coda has sampled further from, and deeper below, the receivers.
#
# These are NEAR-SURFACE values. dv/v that tracks soil moisture and the shallow water table lives in the
# EARLY coda of the shallow Rayleigh wavefield: a late/long window samples too deep and too broadly to
# be informative about the top few hundred metres. Shorter lapse and a shorter mean free path (stronger
# near-surface scattering) both localise the kernel. They are calibratable from the group velocity and
# the observed coda decay of the actual measurement band -- these defaults should be replaced with
# values fitted to the network's own data where available.
DIFFUSIVITY_KM2_S = 8.0      # D; near-surface coda, v ~ 1.5 km/s with a ~10 km transport mean free path
LAPSE_TIME_S = 10.0          # centre of the EARLY coda window (near-surface Rayleigh scattering)


def _intensity_2d(r_km: ArrayLike, t_s: ArrayLike, d_km2_s: float) -> NDArray[np.float64]:
    """2-D diffusion intensity Green's function ``p(r, t)``.

    ``r_km`` in km, ``t_s`` in seconds, ``d_km2_s`` in km^2/s.
    """
    t = np.maximum(np.asarray(t_s, dtype="float64"), 1e-6)
    r = np.asarray(r_km, dtype="float64")
    return np.exp(-(r ** 2) / (4.0 * d_km2_s * t)) / (4.0 * np.pi * d_km2_s * t)


def pair_kernel(x_km: NDArray[np.float64], y_km: NDArray[np.float64],
                s1: ArrayLike, s2: ArrayLike,
                t_lapse: float = LAPSE_TIME_S, d: float = DIFFUSIVITY_KM2_S,
                n_quad: int = 24) -> NDArray[np.float64]:
    """Coda sensitivity kernel ``K(x)`` of one station pair, on a grid (Pacheco & Snieder 2005).

    ``x_km``/``y_km`` are grid coordinates in km (as from ``np.meshgrid``); ``s1``/``s2`` are ``(x, y)``
    station positions in the same coordinates. Returns an array shaped like ``x_km``.

    **Normalisation.** The kernel is divided by its **discrete sum over the grid cells** — not by a
    cell-area-weighted integral — so each pair contributes unit total weight and the pairs can be summed
    without one dominating on the strength of its geometry alone. The absolute scale is arbitrary: only
    the *relative* spatial pattern is used downstream.

    A consequence worth knowing: a pair whose sensitivity extends beyond the grid has the in-grid part
    of its kernel upweighted to sum to one. Coverage near the domain edge is therefore optimistic, and
    the sensitivity field should be read as a *relative* map within the domain rather than an absolute
    one comparable across domains.
    """
    r1 = np.hypot(x_km - s1[0], y_km - s1[1])
    r2 = np.hypot(x_km - s2[0], y_km - s2[1])
    r12 = float(np.hypot(s1[0] - s2[0], s1[1] - s2[1]))

    # convolution over the time the wave spends getting from r1 to s and then s to r2
    u = (np.arange(n_quad) + 0.5) * (t_lapse / n_quad)
    num = np.zeros_like(r1, dtype="float64")
    for ui in u:
        num += _intensity_2d(r1, ui, d) * _intensity_2d(r2, t_lapse - ui, d)
    num *= t_lapse / n_quad

    den = _intensity_2d(np.array(r12), t_lapse, d)
    k = num / max(float(den), 1e-30)
    tot = float(np.nansum(k))
    return k / tot if tot > 0 else k


def single_station_kernel(x_km: NDArray[np.float64], y_km: NDArray[np.float64],
                          s: ArrayLike, t_lapse: float = LAPSE_TIME_S,
                          d: float = DIFFUSIVITY_KM2_S, n_quad: int = 24) -> NDArray[np.float64]:
    """Coda sensitivity of a **single-station autocorrelation** — the source and receiver coincide.

    Setting ``s1 = s2 = s`` in the Pacheco–Snieder kernel gives the autocorrelation case: the coda
    samples the medium **immediately around the one station** and decays outward, so the kernel is a
    localised blob centred on the receiver rather than a bridge between two.

    This is the complement of :func:`pair_kernel`. An inter-station kernel is sensitive **along the path
    between** the receivers; a single-station kernel is sensitive **at** each receiver. Having both is
    what lets the between-station region be isolated: the path signal is the part of the pair
    sensitivity that the two single-station kernels do *not* already explain. Single-station coda is
    also available at **every** station, including isolated ones with no usable partner, so it fills the
    gaps a sparse pair geometry leaves.
    """
    return pair_kernel(x_km, y_km, s, s, t_lapse, d, n_quad)


def network_sensitivity(x_km: NDArray[np.float64], y_km: NDArray[np.float64],
                        stations_km: ArrayLike, t_lapse: float = LAPSE_TIME_S,
                        d: float = DIFFUSIVITY_KM2_S,
                        max_pair_km: float | None = None,
                        include_single: bool = True
                        ) -> tuple[NDArray[np.float64], int]:
    """Summed coda sensitivity ``S(x)`` over the network.

    ``stations_km`` is an ``(n, 2)`` array of station positions in km, on the same grid coordinates as
    ``x_km``/``y_km``.

    The total combines two measurement types, which sample different geometry:

    - **inter-station** (cross-correlation) kernels, one per pair — sensitive along the path between the
      receivers. ``max_pair_km`` drops pairs whose separation exceeds the distance over which a usable
      cross-correlation is realistic; without a limit, distant pairs contribute a broad, near-uniform
      kernel that overstates coverage.
    - **single-station** (autocorrelation) kernels, one per station — sensitive at each receiver, and
      available everywhere including isolated stations. Included when ``include_single`` is true.

    Returns ``(sensitivity_field, n_contributions)`` — the field shaped like ``x_km``, and the total
    number of kernels summed (pairs, plus one per station if single-station is included).
    """
    st = np.asarray(stations_km, dtype="float64")
    s = np.zeros_like(x_km, dtype="float64")
    n_used = 0
    for i in range(len(st)):
        for j in range(i + 1, len(st)):
            if max_pair_km is not None and np.hypot(*(st[i] - st[j])) > max_pair_km:
                continue
            s += pair_kernel(x_km, y_km, st[i], st[j], t_lapse, d)
            n_used += 1
    if include_single:
        for k in range(len(st)):
            s += single_station_kernel(x_km, y_km, st[k], t_lapse, d)
            n_used += 1
    return s, n_used


def sensitivity_to_sigma(sens: ArrayLike, floor: float = 1e-6) -> NDArray[np.float64]:
    """Relative dv/v measurement uncertainty from the network sensitivity: sigma ∝ S^{-1/2}.

    Returned normalised to its minimum (the best-constrained cell = 1), so the field reads as
    "how many times worse than the best-observed cell is this one". Cells with no sensitivity return
    ``inf`` — **no constraint**, rather than a large-but-finite number that invites interpolation.
    """
    s = np.asarray(sens, dtype="float64")
    sig = np.where(s > floor, 1.0 / np.sqrt(np.maximum(s, floor)), np.inf)
    finite = np.isfinite(sig)
    if finite.any():
        sig = sig / np.nanmin(sig[finite])
    return sig
