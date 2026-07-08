"""Modular soil hydraulics: saturated conductivity (K_sat) and transmissivity (T).

K_sat and T are *static* soil-hydromechanical parameters, but they sit at the seam between two
models: they set the drainage/infiltration terms of **our** water budget (``src.models.water_budget``)
*and* the transmissivity that LandLab's infinite-slope ``LandslideProbability`` divides pore pressure
by. For the two to stay physically consistent, both sides must agree on how K_sat and T are derived
from the shared SOLUS100 static inputs. There is no single correct pedotransfer function (PTF), so
this module makes the choice **explicit and swappable**: pick a `ksat_method` and a
`transmissivity_method`, or plug in a measured/data-product K_sat field.

Canonical output units: **K_sat in m day⁻¹**, **T in m² day⁻¹**. Each method documents its native
unit and the conversion applied; ``saxton_rawls`` is the reference. See the "Downstream: LandLab
coupling" section of the technical report for the equations and guidance on which to choose.

K_sat methods
-------------
- ``saxton_rawls``      Saxton & Rawls (2006) from sand%/clay%/organic-matter% (our default; also
                        yields the θ_wp/θ_fc/θ_sat retention envelope). Native mm hr⁻¹ -> m day⁻¹.
- ``solus_pedotransfer`` Log-linear PTF in pH, clay%, silt%, CEC used by the LandLab data-prep
                        pipeline (``gaia-hazlab/landslide-data-prep``); select this to make our
                        hydrology consistent with the LandLab Factor-of-Safety. Native unit is
                        unconfirmed at source -- apply ``unit_scale`` to convert to m day⁻¹.
- ``provided``          Pass through an externally supplied K_sat field (e.g. POLARIS Ksat, or a
                        measured raster). Units are the caller's responsibility.

Transmissivity methods
-----------------------
- ``ksat_x_thickness``              T = K_sat · h_soil (LandLab data-prep convention).
- ``ksat_x_thickness_anisotropy``   T = K_sat · h_soil · f  (DataHub canonical; f≈2.5 lateral:vertical).
- ``topmodel_exponential``          T = K_sat · d, the effective profile transmissivity of an
                                    exponential store (d = 1/f decay depth; TOPMODEL-style).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike

# Unit conversions to the canonical K_sat unit (m day⁻¹).
_MM_PER_HR_TO_M_PER_DAY = 24.0 / 1000.0

KSAT_METHODS = ("saxton_rawls", "solus_pedotransfer", "provided")
TRANSMISSIVITY_METHODS = ("ksat_x_thickness", "ksat_x_thickness_anisotropy", "topmodel_exponential")

# DataHub canonical lateral:vertical anisotropy for T = Ksat·h·f (a documented calibration lever).
DEFAULT_ANISOTROPY = 2.5


def ksat_saxton_rawls(sand_pct: ArrayLike, clay_pct: ArrayLike,
                      om_pct: ArrayLike = 2.5) -> np.ndarray:
    """K_sat [m day⁻¹] from Saxton & Rawls (2006) texture PTF (reuses the soil-moisture envelope)."""
    from src.models.soil_moisture import saxton_rawls_envelope

    env = saxton_rawls_envelope(sand_pct, clay_pct, om_pct=om_pct)
    return np.asarray(env["ksat"], dtype="float64") * _MM_PER_HR_TO_M_PER_DAY  # mm/hr -> m/day


def ksat_solus_pedotransfer(ph: ArrayLike, clay_pct: ArrayLike, silt_pct: ArrayLike,
                            cec: ArrayLike, unit_scale: float = 1.0) -> np.ndarray:
    """K_sat from the log-linear PTF used by ``gaia-hazlab/landslide-data-prep``.

    ``log10(K_sat) = 0.40220 + 0.26122·pH + 0.44565 - 0.02329·clay - 0.01265·silt - 0.01038·CEC``
    (clay/silt as percent, CEC in cmol(+) kg⁻¹). Select this method to keep our water-budget K_sat
    and LandLab's transmissivity on the *same* pedotransfer. The regression's native output unit is
    not documented at source, so the result is multiplied by ``unit_scale`` (default 1.0, i.e. raw);
    set ``unit_scale`` to convert to m day⁻¹ once the source unit is confirmed with the data-prep
    authors. Values are returned as-is otherwise (no unit conversion is assumed).
    """
    ph = np.asarray(ph, dtype="float64")
    clay = np.asarray(clay_pct, dtype="float64")
    silt = np.asarray(silt_pct, dtype="float64")
    cec = np.asarray(cec, dtype="float64")
    log10_ksat = (0.40220 + 0.26122 * ph + 0.44565
                  - 0.02329 * clay - 0.01265 * silt - 0.01038 * cec)
    return (10.0 ** log10_ksat) * float(unit_scale)


def saturated_conductivity(method: str = "saxton_rawls", *,
                           sand_pct: ArrayLike | None = None, clay_pct: ArrayLike | None = None,
                           silt_pct: ArrayLike | None = None, ph: ArrayLike | None = None,
                           cec: ArrayLike | None = None, om_pct: ArrayLike = 2.5,
                           ksat_field: ArrayLike | None = None, unit_scale: float = 1.0) -> np.ndarray:
    """Dispatch to a K_sat PTF. Returns K_sat as an array in the method's documented unit (m day⁻¹
    for ``saxton_rawls``; see each method for the others).

    Raises ``ValueError`` on an unknown method or missing required inputs.
    """
    if method == "saxton_rawls":
        if sand_pct is None or clay_pct is None:
            raise ValueError("saxton_rawls requires sand_pct and clay_pct")
        return ksat_saxton_rawls(sand_pct, clay_pct, om_pct=om_pct)
    if method == "solus_pedotransfer":
        if any(v is None for v in (ph, clay_pct, silt_pct, cec)):
            raise ValueError("solus_pedotransfer requires ph, clay_pct, silt_pct, cec")
        return ksat_solus_pedotransfer(ph, clay_pct, silt_pct, cec, unit_scale=unit_scale)
    if method == "provided":
        if ksat_field is None:
            raise ValueError("provided requires ksat_field (a K_sat array/raster)")
        return np.asarray(ksat_field, dtype="float64")
    raise ValueError(f"unknown ksat_method {method!r}; choose from {KSAT_METHODS}")


def transmissivity(ksat: ArrayLike, thickness_m: ArrayLike, method: str = "ksat_x_thickness", *,
                   anisotropy: float = DEFAULT_ANISOTROPY,
                   decay_depth_m: ArrayLike | None = None) -> np.ndarray:
    """Transmissivity from K_sat and soil thickness. Returns T in K_sat-units × metres.

    With K_sat in m day⁻¹ and thickness in m, T is in m² day⁻¹.
      * ``ksat_x_thickness``            T = K_sat · h
      * ``ksat_x_thickness_anisotropy`` T = K_sat · h · anisotropy
      * ``topmodel_exponential``        T = K_sat · decay_depth_m (defaults to h if not given)
    """
    ksat = np.asarray(ksat, dtype="float64")
    h = np.asarray(thickness_m, dtype="float64")
    if method == "ksat_x_thickness":
        return ksat * h
    if method == "ksat_x_thickness_anisotropy":
        return ksat * h * float(anisotropy)
    if method == "topmodel_exponential":
        d = h if decay_depth_m is None else np.asarray(decay_depth_m, dtype="float64")
        return ksat * d
    raise ValueError(f"unknown transmissivity_method {method!r}; choose from {TRANSMISSIVITY_METHODS}")


def soil_hydraulic_properties(method: str = "saxton_rawls", *,
                              transmissivity_method: str = "ksat_x_thickness",
                              thickness_m: ArrayLike | None = None,
                              anisotropy: float = DEFAULT_ANISOTROPY,
                              decay_depth_m: ArrayLike | None = None,
                              **ksat_kwargs: ArrayLike) -> dict:
    """Convenience: K_sat plus (if thickness given) T, from one call.

    Returns a dict with ``ksat`` (and ``transmissivity`` when ``thickness_m`` is provided). Extra
    kwargs pass to :func:`saturated_conductivity` (sand_pct/clay_pct/silt_pct/ph/cec/ksat_field/...).
    """
    ksat = saturated_conductivity(method, **ksat_kwargs)
    out = {"ksat": ksat, "ksat_method": method}
    if thickness_m is not None:
        out["transmissivity"] = transmissivity(
            ksat, thickness_m, method=transmissivity_method,
            anisotropy=anisotropy, decay_depth_m=decay_depth_m)
        out["transmissivity_method"] = transmissivity_method
    return out
