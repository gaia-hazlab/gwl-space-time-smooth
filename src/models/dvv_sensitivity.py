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
time — the coda samples further from the receivers the longer you wait. Summing over all available
pairs gives the **network sensitivity** :math:`S(x) = \\sum_{\\text{pairs}} K_{\\text{pair}}(x)`.

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

# Diffuse-coda parameters. Both are properties of the medium and the measurement window, not free
# knobs: D is the diffusivity of the scattered wavefield and t_lapse is the coda window in which dv/v
# is measured. Longer lapse time -> the coda has sampled further from the receivers.
DIFFUSIVITY_KM2_S = 20.0     # D; crustal coda, v ~ 2 km/s with a ~20 km transport mean free path
LAPSE_TIME_S = 30.0          # centre of the coda window used for the stretching measurement


def _intensity_2d(r_km, t_s, d_km2_s):
    """2-D diffusion intensity Green's function p(r, t)."""
    t = np.maximum(t_s, 1e-6)
    return np.exp(-(r_km ** 2) / (4.0 * d_km2_s * t)) / (4.0 * np.pi * d_km2_s * t)


def pair_kernel(x_km, y_km, s1, s2, t_lapse=LAPSE_TIME_S, d=DIFFUSIVITY_KM2_S, n_quad=24):
    """Coda sensitivity kernel K(x) of one station pair, on a grid (Pacheco & Snieder 2005).

    ``s1``/``s2`` are (x, y) station positions in km, on the same grid coordinates.
    Returns an array shaped like ``x_km``, normalised so it integrates to 1 over the grid — the kernel
    is a *weighting*, and its absolute scale is absorbed into the normalisation below.
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


def network_sensitivity(x_km, y_km, stations_km, t_lapse=LAPSE_TIME_S, d=DIFFUSIVITY_KM2_S,
                        max_pair_km=None):
    """Summed coda sensitivity S(x) over every station pair.

    ``stations_km`` is an (n, 2) array of station positions in km. ``max_pair_km`` optionally drops
    pairs whose separation exceeds the distance over which a usable cross-correlation is realistic;
    without a limit, distant pairs contribute a broad, near-uniform kernel that overstates coverage.
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
    return s, n_used


def sensitivity_to_sigma(sens, floor=1e-6):
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
