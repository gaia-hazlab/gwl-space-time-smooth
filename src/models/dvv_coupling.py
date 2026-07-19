"""dv/v coupling — derive groundwater level & soil moisture from seismic velocity change.

The third state variable's dynamic source is **dv/v**: ambient-noise seismic velocity change.
Grounded in the gaia-hazlab soil-hydromechanical memory framework, the observed change is a
superposition of a saturated-zone poroelastic term and a vadose-zone effective-stress term,

    Δv_obs ≈ Δv_sat + Δv_vad,

and different frequency bands sense different depths (Δv(r,t) ≈ ∫ K(z) Δv(r,z,t) dz):

    low-frequency band  → deeper saturated zone → head change Δh → **groundwater level**
    high-frequency band → shallow vadose zone (~1 m) → saturation S_w → **soil moisture**

so dv/v is not only a *constraint* on soil mechanics — with the right bands it **derives** GWL
and SM, giving a third, independent observational estimate to assimilate against the
terrain/climate estimates.

Governing relations (framework):
  * Saturated (poroelastic head sensitivity):   (Δv/v)_sat = −S_sk · β · B · Δh
    → invert:  Δh = −(Δv/v)_sat / (S_sk β B),   d_wt(t) = d_wt0 − Δh
  * Vadose (Hertz–Mindlin stiffness vs effective stress):
        V_s = sqrt(G/ρ_b),   G(P_e) = G_ref (P_e/P_ref)^n,  n ≈ 1/3,
        P_e = σ − p − S_e P_c(S_e),   P_c(S_e) = (1/α)(S_e^{−1/m} − 1)^{1/n_vg}   (van Genuchten)
    → (Δv/v)_vad = [V_s(S_w,t) − V_s(S_w,t0)] / V_s(t0);  invert monotonically for S_w → θ.

Static envelope (the sensitivities) comes from SOLUS texture (+ Vs30 when available); the
dynamic driver is banded dv/v(t). This module implements the FORWARD map (states → banded
dv/v) and the INVERSE map (banded dv/v → states).

STATUS: demonstrative. Real dv/v comes from ambient-noise cross-correlation (codameter,
denolle-lab). Here we exercise the forward+inverse operators on the modeled GWL/SM states
(a closed loop) to show the coupling is self-consistent and invertible — pending ingestion of
measured dv/v and calibration of the poroelastic/retention parameters against boreholes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Nominal, calibration-pending parameters (documented; to be anchored to boreholes/lab).
RHO_GRAIN = 2650.0     # mineral grain density (kg/m^3)
RHO_W = 1000.0         # water density (kg/m^3)
P_REF = 100.0          # Hertz–Mindlin reference effective pressure (kPa)
N_EXP = 1.0 / 3.0      # Hertz–Mindlin pressure exponent
G_REF = 75.0           # reference shear modulus at P_REF (MPa) — shallow soil
SIGMA0 = 10.0          # nominal shallow overburden effective stress (kPa)
# Saturated poroelastic head sensitivity S_sk·β·B: ~0.05 % dv/v per metre of head.
K_SAT = 5.0e-4         # (Δv/v) per metre of head change


@dataclass
class CouplingEnvelope:
    """Static poroelastic/mechanical sensitivities on a common (y, x) grid."""

    theta_wp: np.ndarray      # residual/wilting θ  (van Genuchten θ_r proxy)
    theta_sat: np.ndarray     # porosity φ
    vg_alpha: np.ndarray      # van Genuchten α (1/kPa)
    vg_n: np.ndarray          # van Genuchten n
    k_sat: float = K_SAT      # saturated head sensitivity (Δv/v per m)


def coupling_envelope(sand_pct, clay_pct, theta_wp, theta_sat) -> CouplingEnvelope:
    """Build the static coupling envelope from SOLUS texture + the Saxton–Rawls limits.

    van Genuchten α, n are estimated from texture (coarser soils → larger α, larger n),
    a standard pedotransfer simplification adequate for this demonstrative coupling.
    """
    S = np.asarray(sand_pct, dtype="float64") / 100.0
    C = np.asarray(clay_pct, dtype="float64") / 100.0
    # Texture heuristics (Carsel & Parrish-style trends): sandy → high α & n, clayey → low.
    vg_alpha = np.clip(0.02 + 0.13 * S - 0.05 * C, 0.005, 0.25)   # 1/kPa
    vg_n = np.clip(1.2 + 1.3 * S - 0.4 * C, 1.1, 2.8)
    return CouplingEnvelope(theta_wp=np.asarray(theta_wp, float),
                            theta_sat=np.asarray(theta_sat, float),
                            vg_alpha=vg_alpha, vg_n=vg_n)


def _vs_vadose(theta, env: CouplingEnvelope):
    """Shear-wave velocity of the vadose layer as a function of θ (Hertz–Mindlin + suction)."""
    theta_r = env.theta_wp
    phi = env.theta_sat
    Se = np.clip((theta - theta_r) / np.clip(phi - theta_r, 1e-6, None), 1e-3, 1.0)
    m = 1.0 - 1.0 / env.vg_n
    # van Genuchten capillary suction (kPa); drier soil → larger suction → stiffer.
    Pc = (1.0 / env.vg_alpha) * (Se ** (-1.0 / m) - 1.0) ** (1.0 / env.vg_n)
    Pc = np.nan_to_num(Pc, nan=0.0, posinf=1e4)
    P_e = np.clip(SIGMA0 + Se * Pc, 1.0, None)                    # effective stress (kPa)
    G = G_REF * (P_e / P_REF) ** N_EXP * 1e6                      # Pa
    rho_b = RHO_GRAIN * (1.0 - phi) + theta * RHO_W               # bulk density (kg/m^3)
    return np.sqrt(G / rho_b)


# ---------------------------------------------------------------------------
# Forward: (GWL head anomaly, soil moisture) → banded dv/v
# ---------------------------------------------------------------------------
def saturated_dvv(dtw_anom, env: CouplingEnvelope) -> np.ndarray:
    """Saturated / low-freq dv/v band from a depth-to-water anomaly.

    ``dtw_anom`` = DTW − baseline (m); a deeper table (positive anomaly) is a head drop Δh = −dtw_anom,
    so ``dvv_low = −k_sat·Δh``. Factored out so a hysteresis-aware caller can compute the (unchanged)
    saturated band without re-running the vadose calculation it will replace.
    """
    dh = -np.asarray(dtw_anom, dtype="float64")                  # head change (m)
    return (-env.k_sat * dh).astype("float32")


def forward_dvv(dtw_anom, theta, theta_ref, env: CouplingEnvelope) -> dict:
    """Banded dv/v that the given states produce.

    ``dtw_anom`` = DTW − baseline (m); a deeper table (positive anomaly) is a head drop
    Δh = −dtw_anom. ``theta_ref`` is the per-cell reference θ (t0) for the vadose band.
    Returns dict(dvv_low, dvv_high) as fractions (not %).
    """
    dvv_low = saturated_dvv(dtw_anom, env)                       # saturated / low-freq band
    vs_t = _vs_vadose(theta, env)
    vs_0 = _vs_vadose(theta_ref, env)
    dvv_high = (vs_t - vs_0) / vs_0                              # vadose / high-freq band
    return {"dvv_low": dvv_low, "dvv_high": dvv_high.astype("float32")}


# ---------------------------------------------------------------------------
# Inverse: banded dv/v → (GWL, soil moisture)
# ---------------------------------------------------------------------------
def invert_dvv(dvv_low, dvv_high, env: CouplingEnvelope, dtw0, theta_ref):
    """Recover DTW(t) and θ(t) from the banded dv/v (the dv/v→states derivation).

    Saturated band inverts analytically for head; vadose band inverts the monotone V_s(θ)
    relation by a per-cell lookup between θ_wp and θ_sat.
    """
    dh = -np.asarray(dvv_low, dtype="float64") / env.k_sat       # Δh from low band
    dtw = np.asarray(dtw0, dtype="float64") - dh                 # d_wt = d_wt0 − Δh

    # Vadose: build V_s(θ) on a θ grid per cell and invert dvv_high → θ.
    theta_grid = np.linspace(0.0, 1.0, 41)[:, None, None]        # fractions of [wp, sat]
    wp, sat = env.theta_wp[None], env.theta_sat[None]
    theta_samples = wp + theta_grid * (sat - wp)                 # (41, y, x)
    vs0 = _vs_vadose(theta_ref, env)[None]
    dvv_curve = (_vs_vadose(theta_samples.reshape(41, *wp.shape[1:]), env) - vs0) / vs0
    target = np.asarray(dvv_high, dtype="float64")[None]
    # nearest θ on the monotone curve
    j = np.argmin(np.abs(dvv_curve - target), axis=0)
    yy, xx = np.meshgrid(np.arange(wp.shape[1]), np.arange(wp.shape[2]), indexing="ij")
    theta = theta_samples[j, yy, xx]
    return dtw.astype("float32"), theta.astype("float32")
