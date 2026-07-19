"""Soil-mechanics state module (gaia-soil-hydromechanics).

The third coupled state variable of gaia-soil-hydromechanics (with soil moisture and groundwater
level), producing the mechanical state the downstream hazard twins consume.

**Implemented (#128): the landslide infinite-slope factor of safety.** This is the MVP mechanical
state for the LandLab landslide chain: a per-cell factor of safety from the twin's hydrology (the
water table sets the pore pressure on the failure plane), the terrain slope, a slope-dependent
colluvium thickness, and soil + root strength, with a per-cell uncertainty companion and a failure
probability.

Not yet here (tracked separately): the liquefaction stiffness/triggering state (Milestone 2, needs
CPT/Vs(z)), and the dynamic dv/v modulation of strength (needs measured dv/v). ``vs30``/``dvv`` are
accepted as optional context for that future coupling but do not enter the FS MVP.

Physics (infinite-slope, slope-parallel seepage; Montgomery & Dietrich 1994; the model LandLab's
``LandslideProbability`` evaluates):

    FS = [ C' + (gamma_s*h - gamma_w*h_w) cos^2(theta) tan(phi') ] / [ gamma_s*h sin(theta) cos(theta) ]

with total cohesion ``C' = c_soil + c_root`` [Pa], soil unit weight ``gamma_s`` [N/m^3], soil (failure
-plane) depth ``h`` [m], the height of the water table above the failure plane ``h_w = max(h - DTW, 0)``
[m], water unit weight ``gamma_w = 9810`` [N/m^3], and slope angle ``theta``. A wetter column (larger
``h_w``) lowers the effective normal stress and therefore FS -- the hydrology-to-stability link.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.stats import norm

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TARGET_RES_M = 90.0
GAMMA_W = 9810.0          # unit weight of water [N/m^3]
FS_CAP = 10.0             # FS is meaningless on flat ground (denominator -> 0); cap it
_EPS = 1e-9

# MVP default strengths (documented, to be replaced by a land-cover / SOLUS lookup):
ROOT_COHESION_PA = 5000.0     # forested colluvium root cohesion ~5 kPa
SOIL_COHESION_PA = 0.0        # cohesionless colluvium (conservative)
PHI_DEG = 33.0                # effective friction angle of colluvium
GAMMA_SOIL = 18000.0          # moist colluvium unit weight ~18 kN/m^3
ROOT_COHESION_CV = 0.4        # coefficient of variation on cohesion (spatial + temporal ignorance)
PHI_SIGMA_DEG = 4.0           # 1-sigma on the friction angle


def colluvium_thickness(slope_tan: ArrayLike, z_min: float = 0.3, z_max: float = 2.0,
                        slope_cap_deg: float = 45.0) -> NDArray[np.float64]:
    """Slope-dependent soil (colluvium) thickness [m]: thinner on steeper ground.

    A simple, monotone MVP model — full thickness ``z_max`` on flats, thinning linearly to ``z_min`` by
    ``slope_cap_deg`` and holding there. Steep slopes shed colluvium; this is the standard first-order
    proxy where a mapped soil-depth product is unavailable.
    """
    slope_deg = np.degrees(np.arctan(np.asarray(slope_tan, dtype="float64")))
    frac = np.clip(slope_deg / max(slope_cap_deg, _EPS), 0.0, 1.0)
    return z_max - (z_max - z_min) * frac


@dataclass
class SlopeStability:
    """Infinite-slope stability state on the grid."""

    fs: NDArray[np.float64]              # factor of safety (>1 stable, <1 failure)
    fs_sigma: NDArray[np.float64]        # 1-sigma on FS (from cohesion + friction uncertainty)
    p_failure: NDArray[np.float64]       # P(FS < 1) under a normal reliability model
    soil_depth_m: NDArray[np.float64]    # the failure-plane depth used
    sat_fraction: NDArray[np.float64]    # h_w / h: how much of the column is above the water table


def infinite_slope_factor_of_safety(
    slope_tan: ArrayLike, wt_depth_m: ArrayLike, soil_depth_m: ArrayLike | None = None,
    root_cohesion_pa: ArrayLike = ROOT_COHESION_PA, soil_cohesion_pa: ArrayLike = SOIL_COHESION_PA,
    phi_deg: ArrayLike = PHI_DEG, gamma_soil: float = GAMMA_SOIL,
    root_cohesion_cv: float = ROOT_COHESION_CV, phi_sigma_deg: float = PHI_SIGMA_DEG,
    fs_cap: float = FS_CAP,
) -> SlopeStability:
    """Per-cell infinite-slope factor of safety + uncertainty + failure probability.

    ``slope_tan`` = tan(slope); ``wt_depth_m`` = depth to water table [m] (a wetter shallow table
    lowers FS). ``soil_depth_m`` defaults to :func:`colluvium_thickness`. Strength parameters are
    scalars or per-cell arrays. Returns a :class:`SlopeStability`.

    Uncertainty is first-order reliability: FS is linear in the total cohesion ``C'`` and in
    ``tan(phi')``, so ``sigma_FS^2 = (dFS/dC' sigma_C')^2 + (dFS/dtanphi sigma_tanphi)^2`` and
    ``P(FS<1) = Phi((1 - FS)/sigma_FS)``. Flat ground (denominator -> 0) is capped stable with zero
    failure probability. NaN inputs propagate to NaN.
    """
    t = np.asarray(slope_tan, dtype="float64")
    dtw = np.asarray(wt_depth_m, dtype="float64")
    h = colluvium_thickness(t) if soil_depth_m is None else np.asarray(soil_depth_m, dtype="float64")
    h = np.broadcast_to(h, np.broadcast_shapes(np.shape(t), np.shape(dtw), np.shape(h))).astype("float64")
    t, dtw = (np.broadcast_to(a, h.shape).astype("float64") for a in (t, dtw))

    c_total = np.asarray(root_cohesion_pa, dtype="float64") + np.asarray(soil_cohesion_pa, dtype="float64")
    phi = np.radians(np.asarray(phi_deg, dtype="float64"))
    tan_phi = np.tan(phi)

    h_w = np.clip(h - dtw, 0.0, h)                                  # saturated height above the plane
    with np.errstate(invalid="ignore", divide="ignore"):
        sat_fraction = np.where(h > _EPS, h_w / h, np.nan)
        cos2 = 1.0 / (1.0 + t * t)                                 # cos^2(theta)
        sc = t / (1.0 + t * t)                                     # sin(theta)cos(theta)
        eff_normal = (gamma_soil * h - GAMMA_W * h_w) * cos2       # effective normal stress term [Pa]
        denom = gamma_soil * h * sc                                # driving stress [Pa]
        num = c_total + eff_normal * tan_phi
        fs = np.where(denom > _EPS, num / denom, fs_cap)

        # first-order reliability from cohesion + friction uncertainty
        sigma_c = root_cohesion_cv * c_total
        sigma_tanphi = (1.0 / np.cos(phi) ** 2) * np.radians(phi_sigma_deg)   # sec^2(phi) * d phi
        dfs_dc = np.where(denom > _EPS, 1.0 / denom, 0.0)
        dfs_dtanphi = np.where(denom > _EPS, eff_normal / denom, 0.0)
        fs_sigma = np.sqrt((dfs_dc * sigma_c) ** 2 + (dfs_dtanphi * sigma_tanphi) ** 2)

    fs = np.clip(fs, 0.0, fs_cap)
    # propagate NaN from the inputs so unconstrained cells are not fabricated as stable
    bad = ~np.isfinite(t) | ~np.isfinite(dtw) | ~np.isfinite(h)
    p_failure = np.where(
        fs_sigma > _EPS, norm.cdf((1.0 - fs) / np.where(fs_sigma > _EPS, fs_sigma, 1.0)),
        (fs < 1.0).astype("float64"))
    fs, fs_sigma, p_failure = (np.where(bad, np.nan, a) for a in (fs, fs_sigma, p_failure))
    return SlopeStability(fs=fs, fs_sigma=fs_sigma, p_failure=p_failure,
                          soil_depth_m=h, sat_fraction=sat_fraction)


@dataclass
class MechanicsInputs:
    """Aligned 90 m EPSG:5070 inputs for the landslide factor-of-safety estimate.

    ``slope_tan`` and ``water_table_depth`` are required; ``water_table_depth`` may be static ``(y, x)``
    or time-varying ``(t, y, x)`` (reduced to the seasonal-high / shallow-tail table by
    :func:`estimate_mechanics`). ``soil_depth_m`` defaults to a slope model. ``vs30``/``dvv``/
    ``saturation`` are optional context for the future dynamic-stiffness coupling and do not enter the
    FS MVP.
    """

    slope_tan: np.ndarray
    water_table_depth: np.ndarray
    soil_depth_m: np.ndarray | None = None
    root_cohesion_pa: float | np.ndarray = ROOT_COHESION_PA
    soil_cohesion_pa: float | np.ndarray = SOIL_COHESION_PA
    phi_deg: float | np.ndarray = PHI_DEG
    gamma_soil: float = GAMMA_SOIL
    vs30: np.ndarray | None = None
    dvv: np.ndarray | None = None
    saturation: np.ndarray | None = None
    extra: dict = field(default_factory=dict)


def estimate_mechanics(inp: MechanicsInputs, wt_quantile: float = 0.1) -> SlopeStability:
    """Landslide slope-stability state from the twin's hydrology + terrain.

    A time-varying water table is reduced to the **seasonal-high** (shallow-tail) depth — the
    landslide-relevant worst case (highest pore pressure, lowest FS) — before FS is evaluated.
    """
    dtw = np.asarray(inp.water_table_depth, dtype="float64")
    if dtw.ndim == 3:                                              # (t, y, x) -> seasonal-high (low DTW)
        dtw = np.nanquantile(dtw, wt_quantile, axis=0)
    return infinite_slope_factor_of_safety(
        inp.slope_tan, dtw, soil_depth_m=inp.soil_depth_m,
        root_cohesion_pa=inp.root_cohesion_pa, soil_cohesion_pa=inp.soil_cohesion_pa,
        phi_deg=inp.phi_deg, gamma_soil=inp.gamma_soil)


def main() -> None:
    import rioxarray

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    d = "data/processed"
    p.add_argument("--slope", type=Path, default=Path(f"{d}/terrain_slope_domain_90m.tif"),
                   help="Slope raster in DEGREES (converted to tan internally).")
    p.add_argument("--dtw", type=Path, default=Path(f"{d}/baseline_dtw_m.tif"),
                   help="Depth-to-water raster [m] (static baseline, or a seasonal-high field).")
    p.add_argument("--soil-depth", type=Path, default=None,
                   help="Optional colluvium-thickness raster [m]; default is a slope model.")
    p.add_argument("--root-cohesion-pa", type=float, default=ROOT_COHESION_PA)
    p.add_argument("--phi-deg", type=float, default=PHI_DEG)
    p.add_argument("--output-dir", type=Path, default=Path(d))
    args = p.parse_args()

    def _load(path):
        return rioxarray.open_rasterio(path, masked=True).squeeze("band", drop=True)

    slope = _load(args.slope)
    tan_b = np.tan(np.radians(slope.values))
    dtw = _load(args.dtw).rio.reproject_match(slope).values
    soil_depth = _load(args.soil_depth).rio.reproject_match(slope).values if args.soil_depth else None

    ss = infinite_slope_factor_of_safety(tan_b, dtw, soil_depth_m=soil_depth,
                                         root_cohesion_pa=args.root_cohesion_pa, phi_deg=args.phi_deg)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, arr in [("fs", ss.fs), ("pfail", ss.p_failure)]:
        out = slope.copy(data=arr.astype("float32"))
        path = args.output_dir / f"soil_mechanics_{name}_90m.tif"
        out.rio.to_raster(path)
        logger.info("wrote %s", path)
    logger.info("FS < 1 (potentially unstable) over %.1f%% of finite cells",
                100.0 * np.nanmean((ss.fs < 1.0).astype("float64")))


if __name__ == "__main__":
    main()
