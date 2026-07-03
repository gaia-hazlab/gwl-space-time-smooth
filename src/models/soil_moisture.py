"""Soil-moisture state module (gaia-soil-hydromechanics).

One of the three coupled state variables of gaia-soil-hydromechanics (soil moisture,
groundwater level, soil mechanical properties). Estimates the vadose-zone volumetric
soil-moisture state θ(x, t) on the canonical analysis grid.

Static ↔ dynamic decomposition (mirrors the project scope):
  * **Static** — the soil water-holding envelope from SOLUS100 texture (sand%, clay%)
    via the Saxton & Rawls (2006) pedotransfer functions: wilting point θ_wp, field
    capacity θ_fc, saturation/porosity θ_sat, and Ksat. This bounds θ physically and
    carries the fine-scale (90 m) spatial texture.
  * **Dynamic** — a monthly Thornthwaite–Mather soil-water balance driven by TerraClimate
    precipitation and reference ET (``src.data.fetch_terraclimate``). The available water
    capacity AWC = (θ_fc − θ_wp)·z_root sets the bucket size; the balance yields the
    relative wetness w(t) ∈ [0, 1] that carries the interannual signal (droughts, wet years).

θ(t) = θ_wp + w(t)·(θ_fc − θ_wp), clipped to the saturation ceiling θ_sat. Uncertainty
θ_std propagates the pedotransfer envelope error and the driver/storage error.

Complementarity: this couples upward to the vadose zone that GAIA Pillar 1 (Richards +
rock physics) models top-down, and downward to the water table produced by the GWL module.
The saturation state θ/θ_sat also feeds the effective-stress term in ``src.models.soil_mechanics``.

CLI outputs:
  * ``soil_hydraulic_envelope_90m.zarr`` — static θ_wp/θ_fc/θ_sat/awc/ksat on the 90 m grid.
  * ``soil_moisture_monthly_<tag>.zarr`` — θ(time,y,x) + θ_std on the driver grid, with the
    aggregated envelope and (when present) the TerraClimate ``soil`` field as a cross-check.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import rioxarray  # noqa: F401  (registers the .rio xarray accessor used across this module)
import xarray as xr

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TARGET_RES_M = 90.0

# Effective root-zone / vadose depth used to turn volumetric capacities (m³/m³) into a
# storage bucket (mm). 1.0 m is a standard monthly-water-balance root zone (Thornthwaite).
DEFAULT_ROOT_DEPTH_M = 1.0

# Nominal soil organic-matter content (%) for the Saxton–Rawls PTF. SOLUS ships texture only;
# 2.5 % is a representative topsoil value for the Puget lowland. θ is weakly sensitive to it.
DEFAULT_OM_PCT = 2.5

# Pedotransfer 1σ on the fitted θ_fc / θ_wp (Saxton & Rawls 2006 report RMSE ≈ 0.02–0.03).
_PTF_SIGMA = 0.03
# 1σ on the relative-wetness driver w (bucket closure / driver error), as a fraction of AWC.
_W_SIGMA = 0.12


@dataclass
class SoilMoistureInputs:
    """Aligned inputs for the soil-moisture estimate (all share one (y, x) grid).

    ``dynamic_driver`` is the relative wetness w(time, y, x) ∈ [0, 1] from the
    Thornthwaite–Mather balance (see :func:`thornthwaite_mather_wetness`).
    """

    field_capacity: np.ndarray          # (y, x) volumetric θ at field capacity   [Saxton–Rawls]
    wilting_point: np.ndarray           # (y, x) volumetric θ at wilting point     [Saxton–Rawls]
    porosity: np.ndarray                # (y, x) saturated θ (θ_sat)               [Saxton–Rawls]
    dynamic_driver: np.ndarray          # (time, y, x) relative wetness w ∈ [0, 1] [TerraClimate T–M]


# ---------------------------------------------------------------------------
# Static envelope — Saxton & Rawls (2006) pedotransfer functions
# ---------------------------------------------------------------------------
def saxton_rawls_envelope(
    sand_pct: np.ndarray, clay_pct: np.ndarray, om_pct: float | np.ndarray = DEFAULT_OM_PCT
) -> dict[str, np.ndarray]:
    """Volumetric hydraulic limits from texture (Saxton & Rawls 2006, SSSAJ 70:1569).

    Parameters use percent sand/clay (0–100); organic matter as percent by weight.
    Returns dict of θ_wp, θ_fc, θ_sat (m³/m³) and ksat (mm/hr).
    """
    S = np.asarray(sand_pct, dtype="float64") / 100.0
    C = np.asarray(clay_pct, dtype="float64") / 100.0
    OM = np.broadcast_to(np.asarray(om_pct, dtype="float64"), S.shape)

    # θ at −1500 kPa (permanent wilting point)
    t1500 = (-0.024 * S + 0.487 * C + 0.006 * OM + 0.005 * (S * OM)
             - 0.013 * (C * OM) + 0.068 * (S * C) + 0.031)
    theta_wp = t1500 + (0.14 * t1500 - 0.02)

    # θ at −33 kPa (field capacity)
    t33 = (-0.251 * S + 0.195 * C + 0.011 * OM + 0.006 * (S * OM)
           - 0.027 * (C * OM) + 0.452 * (S * C) + 0.299)
    theta_fc = t33 + (1.283 * t33 ** 2 - 0.374 * t33 - 0.015)

    # θ(sat) − θ(33), then saturation (porosity)
    ts33 = (0.278 * S + 0.034 * C + 0.022 * OM - 0.018 * (S * OM)
            - 0.027 * (C * OM) - 0.584 * (S * C) + 0.078)
    theta_s33 = ts33 + (0.636 * ts33 - 0.107)
    theta_sat = theta_fc + theta_s33 - 0.097 * S + 0.043

    # Saturated conductivity via the moisture-tension slope λ = 1/B
    B = (np.log(1500.0) - np.log(33.0)) / (np.log(theta_fc) - np.log(theta_wp))
    lam = 1.0 / B
    ksat = 1930.0 * np.clip(theta_sat - theta_fc, 1e-6, None) ** (3.0 - lam)  # mm/hr

    # Keep everything physical and ordered θ_wp ≤ θ_fc ≤ θ_sat.
    theta_wp = np.clip(theta_wp, 0.01, 0.5)
    theta_fc = np.clip(theta_fc, theta_wp + 0.01, 0.6)
    theta_sat = np.clip(theta_sat, theta_fc + 0.01, 0.75)
    return {"theta_wp": theta_wp, "theta_fc": theta_fc, "theta_sat": theta_sat, "ksat": ksat}


# ---------------------------------------------------------------------------
# Dynamic driver — Thornthwaite–Mather monthly soil-water balance
# ---------------------------------------------------------------------------
def thornthwaite_mather_wetness(
    precip_mm: np.ndarray, pet_mm: np.ndarray, awc_mm: np.ndarray, init_frac: float = 0.5
) -> np.ndarray:
    """Relative soil wetness w(time, y, x) ∈ [0, 1] from a monthly water balance.

    Classic Thornthwaite–Mather bucket: when P ≥ PET the store recharges toward AWC;
    when P < PET it depletes exponentially with the accumulated potential water loss.
    ``awc_mm`` is the available water capacity (mm); a leading-time-axis P/PET force it.
    """
    P = np.asarray(precip_mm, dtype="float64")
    PET = np.asarray(pet_mm, dtype="float64")
    awc = np.clip(np.asarray(awc_mm, dtype="float64"), 1.0, None)  # avoid div-by-zero

    nt = P.shape[0]
    storage = init_frac * awc
    apwl = np.where(P[0] < PET[0], (PET[0] - P[0]), 0.0)  # accumulated potential water loss
    w = np.empty_like(P)

    for t in range(nt):
        pmpet = P[t] - PET[t]
        wet = pmpet >= 0.0

        # Wet months: recharge and reset the depletion memory.
        storage_wet = np.minimum(storage + pmpet, awc)
        apwl_wet = np.where(storage_wet >= awc, 0.0, -awc * np.log(np.clip(storage_wet / awc, 1e-6, 1.0)))

        # Dry months: accumulate loss, deplete exponentially.
        apwl_dry = apwl + (PET[t] - P[t])
        storage_dry = awc * np.exp(-apwl_dry / awc)

        storage = np.where(wet, storage_wet, storage_dry)
        apwl = np.where(wet, apwl_wet, apwl_dry)
        w[t] = np.clip(storage / awc, 0.0, 1.0)

    return w


# ---------------------------------------------------------------------------
# Snow — temperature-index (degree-day) redistribution of winter precipitation
# ---------------------------------------------------------------------------
# Nominal parameters (documented; calibration-pending against SNOTEL SWE):
_DDF_MM_PER_C_DAY = 3.0   # degree-day melt factor
_T_SNOW_HI = 3.0          # ≥ this °C → all precip falls as rain
_T_SNOW_LO = -1.0         # ≤ this °C → all precip falls as snow (linear between)
_T_MELT = 0.0             # melt threshold (°C)


def snowmelt_liquid_input(precip_mm, tmean_c, days_in_month, ddf=_DDF_MM_PER_C_DAY):
    """Monthly temperature-index snow model → liquid water input W = rain + snowmelt (mm).

    Precip is partitioned into rain and snow by temperature; snow accumulates as SWE and is
    released by degree-day melt, so winter precipitation is **redistributed** into a spring
    melt pulse — the missing physics the SNOTEL validation exposed. Arrays are (time, y, x);
    ``days_in_month`` is (time,). Returns (W, final SWE).
    """
    P = np.asarray(precip_mm, dtype="float64")
    T = np.asarray(tmean_c, dtype="float64")
    swe = np.zeros(P.shape[1:], dtype="float64")
    W = np.empty_like(P)
    for t in range(P.shape[0]):
        snowfrac = np.clip((_T_SNOW_HI - T[t]) / (_T_SNOW_HI - _T_SNOW_LO), 0.0, 1.0)
        snowfall = snowfrac * P[t]
        rain = P[t] - snowfall
        swe = swe + snowfall
        melt = np.minimum(swe, ddf * np.maximum(T[t] - _T_MELT, 0.0) * days_in_month[t])
        swe = swe - melt
        W[t] = rain + melt
    return W.astype("float32"), swe


def apply_snow_if_available(driver_ds, precip_values):
    """Return liquid water input from precip, applying the snow module iff tmean_c is present."""
    if "tmean_c" not in driver_ds:
        return precip_values
    days = np.array([pd.Timestamp(t).days_in_month for t in driver_ds["time"].values])
    W, _ = snowmelt_liquid_input(precip_values, driver_ds["tmean_c"].values, days)
    return W


# ---------------------------------------------------------------------------
# Estimator — combine static envelope with the dynamic wetness
# ---------------------------------------------------------------------------
def estimate_soil_moisture(inp: SoilMoistureInputs) -> tuple[np.ndarray, np.ndarray]:
    """Return volumetric soil moisture θ(time, y, x) and its 1σ θ_std (m³/m³).

    θ = θ_wp + w·(θ_fc − θ_wp), clipped to the saturation ceiling θ_sat. Uncertainty
    combines the pedotransfer envelope error (on θ_wp, θ_fc) with the driver error on w.
    """
    wp = inp.wilting_point[None, ...]
    fc = inp.field_capacity[None, ...]
    sat = inp.porosity[None, ...]
    w = np.clip(inp.dynamic_driver, 0.0, 1.0)

    theta = wp + w * (fc - wp)
    theta = np.minimum(theta, sat)

    # Error propagation: ∂θ/∂θ_wp = (1−w), ∂θ/∂θ_fc = w, ∂θ/∂w = (θ_fc−θ_wp).
    awc = np.clip(fc - wp, 1e-6, None)
    var = ((1.0 - w) * _PTF_SIGMA) ** 2 + (w * _PTF_SIGMA) ** 2 + (_W_SIGMA * awc) ** 2
    theta_std = np.sqrt(var)
    return theta.astype("float32"), theta_std.astype("float32")


# ---------------------------------------------------------------------------
# 90 m statistical downscaling — fine static envelope × downscaled coarse wetness
# ---------------------------------------------------------------------------
def soil_moisture_90m(env90, driver_ds, root_depth_m=DEFAULT_ROOT_DEPTH_M, times=None,
                      downscaler="bilinear"):
    """Downscale the θ estimate onto the 90 m envelope grid, with a 3-term σ budget.

    The dynamic wetness is solved at the coarse TerraClimate grid (its true resolution) and
    downscaled to 90 m via the modular :func:`~src.models.downscale.downscale` operator
    (``downscaler="bilinear"`` is the resampling baseline; register a smarter, covariate-aware
    method to upgrade). The fine static envelope supplies the sub-4 km spatial structure.
    Returns (times, θ_90m[t,y,x], UncertaintyBudget) with static / dynamic / downscaling
    components + provenance. ``times`` optionally selects a subset (indices).
    """
    from src.models.downscale import (
        ProvStep,
        UncertaintyBudget,
        downscale,
        representativeness_sigma,
    )

    # Wetness w(time) on the coarse driver grid (its native ~4 km resolution). The snow module
    # redistributes winter precip → spring melt when the driver carries temperature (tmean_c).
    env_d = _regrid_envelope_to_driver(env90, driver_ds)
    awc_mm = np.clip(env_d["theta_fc"].values - env_d["theta_wp"].values, 0.02, None) \
        * (root_depth_m * 1000.0)
    liquid_in = apply_snow_if_available(driver_ds, driver_ds["precip_mm"].values)
    w_coarse_full = thornthwaite_mather_wetness(
        liquid_in, driver_ds["pet_mm"].values, awc_mm
    )
    w_coarse = xr.DataArray(
        w_coarse_full, dims=("time", "lat", "lon"),
        coords={"time": driver_ds["time"].values, "lat": driver_ds["lat"], "lon": driver_ds["lon"]},
    ).rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs("EPSG:4326")

    idx = range(w_coarse.sizes["time"]) if times is None else list(times)
    like = env90["theta_fc"]
    wp, fc, sat = env90["theta_wp"].values, env90["theta_fc"].values, env90["theta_sat"].values
    awc90 = np.clip(fc - wp, 1e-6, None)

    cov = {"envelope": env90}  # fine static covariates a smarter downscaler may exploit
    frames = []
    for t in idx:
        w90 = downscale(w_coarse.isel(time=t), like, method=downscaler, covariates=cov).values
        w90 = np.clip(w90, 0.0, 1.0)
        theta = np.minimum(wp + w90 * (fc - wp), sat)
        frames.append(theta.astype("float32"))
    theta_90m = np.stack(frames, axis=0)

    # Uncertainty budget (time-mean wetness weights the static/dynamic split).
    w90_mean = np.clip(
        downscale(w_coarse.isel(time=list(idx)).mean("time"), like, method=downscaler,
                  covariates=cov).values, 0.0, 1.0)
    budget = UncertaintyBudget()
    budget.add("static_pedotransfer", np.sqrt((1 - w90_mean) ** 2 + w90_mean ** 2) * _PTF_SIGMA)
    budget.add("dynamic_driver", _W_SIGMA * awc90)
    # representativeness on the θ scale: fine texture std the coarse driver can't resolve
    budget.add("downscaling", representativeness_sigma(like, 4000.0, TARGET_RES_M))
    budget.provenance = [
        ProvStep("clay%, sand%", "SOLUS100 (USDA-NRCS)", 100.0, TARGET_RES_M, "reproject (bilinear)"),
        ProvStep("θ_wp, θ_fc, θ_sat", "Saxton & Rawls (2006) PTF", TARGET_RES_M, TARGET_RES_M, "pedotransfer"),
        ProvStep("precip, PET", "TerraClimate v1.1", 4000.0, 4000.0, "NCSS subset"),
        ProvStep("wetness w(t)", "Thornthwaite–Mather bucket", 4000.0, 4000.0, "water balance"),
        ProvStep("w(t) → 90 m", "statistical downscaling", 4000.0, TARGET_RES_M, "bilinear + representativeness σ"),
        ProvStep("θ(t) = θ_wp + w·(θ_fc−θ_wp)", "envelope × wetness", TARGET_RES_M, TARGET_RES_M, "combine"),
    ]
    sel_times = np.asarray(driver_ds["time"].values)[list(idx)]
    return sel_times, theta_90m, budget


# ---------------------------------------------------------------------------
# Forcing ensemble — same envelope + bucket under multiple climate forcings
# ---------------------------------------------------------------------------
def soil_moisture_forcing_ensemble(env90, drivers: dict, root_depth_m=DEFAULT_ROOT_DEPTH_M):
    """Run the θ estimate under several forcings and quantify forcing uncertainty.

    ``drivers`` maps a forcing name (e.g. "TerraClimate", "PRISM") to its monthly driver
    Dataset (each with precip_mm, pet_mm). Each is solved with the SAME static envelope and
    bucket, downscaled to the SAME 90 m grid, then intersected on common months. Returns
    (months, per-forcing θ dict, ensemble-mean θ, σ_forcing[y,x]) where σ_forcing is the
    time-mean cross-forcing standard deviation — the forcing-uncertainty term for the budget
    and the basis for bootstrapping / ensembling.
    """
    # Common months across all forcings (month-resolution timestamps).
    month_sets = []
    for ds in drivers.values():
        month_sets.append({(pd.Timestamp(t).year, pd.Timestamp(t).month)
                           for t in ds["time"].values})
    common = sorted(set.intersection(*month_sets))

    per_forcing, times_ref = {}, None
    for name, ds in drivers.items():
        dt = pd.DatetimeIndex(ds["time"].values)
        idx = [int(np.where((dt.year == y) & (dt.month == m))[0][0]) for (y, m) in common]
        t, theta, _ = soil_moisture_90m(env90, ds, root_depth_m=root_depth_m, times=idx)
        per_forcing[name] = theta
        times_ref = t

    stack = np.stack(list(per_forcing.values()), axis=0)   # (forcing, time, y, x)
    ens_mean = np.nanmean(stack, axis=0)
    sigma_forcing = np.nanmean(np.nanstd(stack, axis=0), axis=0)  # (y, x) time-mean spread
    return times_ref, per_forcing, ens_mean, sigma_forcing.astype("float32")


# ---------------------------------------------------------------------------
# CLI — orchestrate SOLUS (static) + TerraClimate (dynamic) → θ product
# ---------------------------------------------------------------------------
def _load_solus_envelope_90m(solus_zarr: Path, like_tif: Path, om_pct: float):
    """SOLUS texture → Saxton–Rawls envelope reprojected onto the 90 m EPSG:5070 grid."""
    import rioxarray
    import xarray as xr

    like = rioxarray.open_rasterio(like_tif, masked=True).squeeze("band", drop=True)

    solus = xr.open_zarr(solus_zarr, consolidated=True)
    if solus.rio.crs is None:
        solus = solus.rio.write_crs("EPSG:5070")
    solus = solus.rio.reproject_match(like)

    env = saxton_rawls_envelope(solus["sand_pct"].values, solus["clay_pct"].values, om_pct)
    out = xr.Dataset(
        {k: (("y", "x"), v.astype("float32")) for k, v in env.items()},
        coords={"y": like.y, "x": like.x},
    )
    out["awc_mm"] = ((out["theta_fc"] - out["theta_wp"]) * (DEFAULT_ROOT_DEPTH_M * 1000.0)).astype("float32")
    out = out.rio.write_crs("EPSG:5070")
    # Mask cells with no SOLUS texture (outside coverage).
    valid = np.isfinite(solus["sand_pct"].values) & np.isfinite(solus["clay_pct"].values)
    for v in out.data_vars:
        out[v] = out[v].where(valid)
    return out


def _regrid_envelope_to_driver(env_90m, driver_ds):
    """Area-aggregate the 90 m envelope onto the TerraClimate (WGS84) driver grid."""
    import rioxarray  # noqa: F401

    driver = driver_ds.rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs("EPSG:4326")
    env_wgs84 = env_90m.rio.reproject("EPSG:4326")
    return env_wgs84.rio.reproject_match(driver)


def main() -> None:
    import shutil

    import pandas as pd
    import rioxarray  # noqa: F401
    import xarray as xr

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--solus", type=Path, default=Path("data/processed/solus100_wa.zarr"),
                   help="SOLUS100 texture (clay_pct, sand_pct) — static capacity terms.")
    p.add_argument("--like", type=Path, default=Path("data/processed/terrain_hand_90m.tif"),
                   help="Reference 90 m EPSG:5070 grid for the static envelope.")
    p.add_argument("--driver", type=Path, default=Path("data/processed/terraclimate_monthly_puget.zarr"),
                   help="TerraClimate monthly driver (precip_mm, pet_mm[, tc_soil_mm]).")
    p.add_argument("--root-depth-m", type=float, default=DEFAULT_ROOT_DEPTH_M)
    p.add_argument("--om-pct", type=float, default=DEFAULT_OM_PCT)
    p.add_argument("--tag", default="puget", help="Filename tag for the θ product.")
    p.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    args = p.parse_args()

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Static envelope on the 90 m grid ---
    logger.info("Building Saxton–Rawls static envelope from SOLUS texture on the 90 m grid.")
    env90 = _load_solus_envelope_90m(args.solus, args.like, args.om_pct)
    env90_path = out_dir / "soil_hydraulic_envelope_90m.zarr"
    if env90_path.exists():
        shutil.rmtree(env90_path)
    env90.attrs.update(source="SOLUS100 texture → Saxton & Rawls (2006) PTF",
                       role="static hydraulic envelope", root_depth_m=args.root_depth_m)
    env90.to_zarr(env90_path, mode="w", consolidated=True)
    logger.info("Wrote %s (%s)", env90_path, dict(env90.sizes))

    # --- Dynamic driver on the TerraClimate grid ---
    logger.info("Running Thornthwaite–Mather balance on the TerraClimate driver grid.")
    driver = xr.open_zarr(args.driver, consolidated=True)
    env_d = _regrid_envelope_to_driver(env90, driver)
    awc_mm = np.clip((env_d["theta_fc"].values - env_d["theta_wp"].values), 0.02, None) \
        * (args.root_depth_m * 1000.0)

    liquid_in = apply_snow_if_available(driver, driver["precip_mm"].values)
    w = thornthwaite_mather_wetness(liquid_in, driver["pet_mm"].values, awc_mm)
    inp = SoilMoistureInputs(
        field_capacity=env_d["theta_fc"].values,
        wilting_point=env_d["theta_wp"].values,
        porosity=env_d["theta_sat"].values,
        dynamic_driver=w,
    )
    theta, theta_std = estimate_soil_moisture(inp)

    ds = xr.Dataset(
        {
            "theta": (("time", "lat", "lon"), theta),
            "theta_std": (("time", "lat", "lon"), theta_std),
            "wetness": (("time", "lat", "lon"), w.astype("float32")),
            "theta_wp": (("lat", "lon"), env_d["theta_wp"].values.astype("float32")),
            "theta_fc": (("lat", "lon"), env_d["theta_fc"].values.astype("float32")),
            "theta_sat": (("lat", "lon"), env_d["theta_sat"].values.astype("float32")),
            "awc_mm": (("lat", "lon"), awc_mm.astype("float32")),
        },
        coords={"time": driver["time"].values, "lat": driver["lat"].values, "lon": driver["lon"].values},
    )
    if "tc_soil_mm" in driver:
        ds["tc_soil_mm"] = (("time", "lat", "lon"), driver["tc_soil_mm"].values.astype("float32"))
        ds["tc_soil_mm"].attrs["note"] = "TerraClimate column soil-water storage — independent cross-check"
    ds["theta"].attrs.update(units="m3/m3", long_name="Volumetric soil moisture (0–1 m root zone)")
    ds.attrs.update(
        static_source="SOLUS100 → Saxton & Rawls (2006) pedotransfer envelope",
        dynamic_source="TerraClimate monthly P & PET → Thornthwaite–Mather bucket",
        root_depth_m=args.root_depth_m, om_pct=args.om_pct,
    )
    theta_path = out_dir / f"soil_moisture_monthly_{args.tag}.zarr"
    if theta_path.exists():
        shutil.rmtree(theta_path)
    ds.to_zarr(theta_path, mode="w", consolidated=True)

    tmean = float(np.nanmean(theta))
    logger.info("Wrote %s — θ mean=%.3f m³/m³, time=%s..%s (%d months), grid=%s",
                theta_path, tmean, str(pd.Timestamp(ds.time.values[0]))[:7],
                str(pd.Timestamp(ds.time.values[-1]))[:7], ds.time.size,
                dict(ds.theta.isel(time=0).sizes))


if __name__ == "__main__":
    main()
