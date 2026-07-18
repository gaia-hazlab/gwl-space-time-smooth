"""Capillary hysteresis in the water-retention curve — the first memory state (#120).

The vadose retention of [water_budget] is single-valued: one curve for both drying and wetting, so a
given water content always maps to the same suction and the same stiffness. Real soil does not behave
that way — the suction needed to *drain* a pore exceeds the suction at which it *fills*, so water
content vs. matric potential traces a **loop**, and the state carries **memory** of the last reversal.
That memory is a source of soil-moisture memory and it is exactly what a seismic velocity change is
sensitive to (Shi et al. 2026, agroseismology).

This module implements the Kool & Parker (1987, WRR, doi:10.1029/WR023i001p00105) family: van Genuchten
main drying and main wetting curves sharing the shape exponent ``n`` with the wetting air-entry scale
larger than the drying one (``alpha_w = ratio * alpha_d``, ``ratio ~ 2``), and first-order **scanning
curves** obtained by linearly scaling between the two bounding curves, anchored at the last reversal
point. The only extra state carried is that reversal point — the model "remembers" where the last
wetting or drying began.

The suction it returns is fed into the SAME effective-stress / Hertz-Mindlin velocity map as
``dvv_coupling._vs_vadose`` (constants imported from there), so the output is a hysteretic
``V_s(theta)`` — a loop in the observable, not a line.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from src.models.dvv_coupling import G_REF, N_EXP, P_REF, RHO_GRAIN, RHO_W, SIGMA0

WETTING_RATIO = 2.0        # alpha_w / alpha_d: wetting air-entry scale (Kool-Parker default ~2)
_SE_LO, _SE_HI = 1e-3, 1.0 - 1e-6


def vg_suction(se: ArrayLike, alpha: float, n: float) -> NDArray[np.float64]:
    r"""van Genuchten capillary suction (same units as ``1/alpha``, kPa here) at effective saturation.

    :math:`P_c(S_e) = \frac{1}{\alpha}\,(S_e^{-1/m} - 1)^{1/n}`, with :math:`m = 1 - 1/n`. Larger
    ``alpha`` (wetting branch) gives a *lower* suction at the same ``S_e`` — the physical origin of the
    loop.
    """
    se = np.clip(np.asarray(se, dtype="float64"), _SE_LO, _SE_HI)
    m = 1.0 - 1.0 / n
    return (1.0 / alpha) * (se ** (-1.0 / m) - 1.0) ** (1.0 / n)


@dataclass
class ScanState:
    """The carried memory: the last reversal point and the active direction ('d' drying / 'w' wetting)."""
    se_rev: float
    h_rev: float
    direction: str


def hysteretic_suction(se_path: ArrayLike, alpha_d: float, n: float,
                       wetting_ratio: float = WETTING_RATIO, start: str = "drying"
                       ) -> tuple[NDArray[np.float64], list[ScanState]]:
    """Suction along a saturation path, tracking scanning curves and reversals (Kool-Parker family).

    ``se_path`` is the sequence of effective saturations the soil passes through (from the water budget).
    Returns ``(h_path, states)`` where ``h_path`` is the suction on the correct branch at each step and
    ``states`` records the reversal-point memory after each step (for inspection/plotting).

    Model: the two bounding curves are ``vg_suction(., alpha_d, n)`` (drying, higher suction) and
    ``vg_suction(., alpha_w, n)`` with ``alpha_w = wetting_ratio * alpha_d`` (wetting, lower suction). A
    scanning curve is **anchored at the reversal point and decays back to the bound it is heading for**:
    a drying scan passes through the reversal and approaches the main drying curve as ``S_e`` falls
    (weight ``g = S_e / S_e^{rev}``); a wetting scan approaches the main wetting curve as ``S_e`` rises
    (``g = (1-S_e)/(1-S_e^{rev})``). This passes through the reversal, asymptotes to the correct bound,
    and collapses to a single curve when the two bounds coincide (``wetting_ratio = 1``).
    """
    se = np.clip(np.asarray(se_path, dtype="float64"), _SE_LO, _SE_HI)
    alpha_w = wetting_ratio * alpha_d
    hd = lambda s: vg_suction(s, alpha_d, n)          # noqa: E731  drying bound (upper suction)
    hw = lambda s: vg_suction(s, alpha_w, n)          # noqa: E731  wetting bound (lower suction)

    h = np.empty_like(se)
    states: list[ScanState] = []
    cur = "d" if start == "drying" else "w"
    se_r = float(se[0])
    h_r = float(hd(se_r) if cur == "d" else hw(se_r))
    h[0] = h_r
    states.append(ScanState(se_r, h_r, cur))
    for i in range(1, len(se)):
        if se[i] < se[i - 1] - 1e-12:
            d = "d"
        elif se[i] > se[i - 1] + 1e-12:
            d = "w"
        else:
            d = cur
        if d != cur:                                  # reversal: re-anchor at the previous point
            se_r, h_r, cur = float(se[i - 1]), float(h[i - 1]), d
        if cur == "d":                                # heading to the drying bound as Se falls
            g = np.clip(se[i] / se_r, 0.0, 1.0)
            hi = hd(se[i]) + (h_r - hd(se_r)) * g
        else:                                         # heading to the wetting bound as Se rises
            g = np.clip((1.0 - se[i]) / max(1.0 - se_r, 1e-9), 0.0, 1.0)
            hi = hw(se[i]) + (h_r - hw(se_r)) * g
        h[i] = float(np.clip(hi, hw(se[i]), hd(se[i])))
        states.append(ScanState(se_r, h_r, cur))
    return h, states


def vs_from_suction(theta: ArrayLike, se: ArrayLike, suction_kpa: ArrayLike,
                    phi: ArrayLike) -> NDArray[np.float64]:
    """Shear-wave velocity from suction via the SAME effective-stress / Hertz-Mindlin map as the twin.

    ``P_e = SIGMA0 + S_e * P_c``; ``G = G_REF (P_e/P_REF)^{1/3}``; ``V_s = sqrt(G / rho_bulk)``. Feeding
    the *hysteretic* suction here yields a hysteretic ``V_s(theta)``.
    """
    se = np.asarray(se, dtype="float64")
    pc = np.asarray(suction_kpa, dtype="float64")
    phi = np.asarray(phi, dtype="float64")
    theta = np.asarray(theta, dtype="float64")
    p_e = np.clip(SIGMA0 + se * pc, 1.0, None)                     # kPa
    g = G_REF * (p_e / P_REF) ** N_EXP * 1e6                       # Pa
    rho_b = RHO_GRAIN * (1.0 - phi) + theta * RHO_W                # kg/m^3
    return np.sqrt(g / rho_b)


def hysteretic_vs_loop(theta_path: ArrayLike, theta_r: float, phi: float,
                       alpha_d: float, n: float, wetting_ratio: float = WETTING_RATIO,
                       start: str = "drying") -> dict:
    """Convenience: a moisture path -> (suction, Vs) with hysteresis, plus the single-valued reference.

    Returns dict(se, suction, vs, suction_single, vs_single) so a caller can plot the loop against the
    non-hysteretic curve. ``suction_single`` uses the drying bound as the single-valued stand-in.
    """
    theta = np.asarray(theta_path, dtype="float64")
    se = np.clip((theta - theta_r) / max(phi - theta_r, 1e-6), _SE_LO, _SE_HI)
    suction, _ = hysteretic_suction(se, alpha_d, n, wetting_ratio, start)
    vs = vs_from_suction(theta, se, suction, phi)
    suction_single = vg_suction(se, alpha_d, n)                    # one curve, no memory
    vs_single = vs_from_suction(theta, se, suction_single, phi)
    return {"se": se, "suction": suction, "vs": vs,
            "suction_single": suction_single, "vs_single": vs_single}
