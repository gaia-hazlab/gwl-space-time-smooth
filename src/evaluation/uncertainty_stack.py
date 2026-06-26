"""
Combine four uncertainty layers into an explainable uncertainty stack.

Uncertainty decomposition (updated for GAIA regression-kriging pipeline)
------------------------------------------------------------------------
σ²_total(x, y, t) = σ²_lgbm(x, y)       from baseline_lgbm_std_m.tif
                   + σ²_krige_base(x, y)  from baseline_kriging_std_m.tif
                   + σ²_response(x, y)    from beta_r2_1km.tif (climate response residual std)
                   + σ²_krige_resid(x,y,t) from gwl_kriging_std.zarr (temporal; not combined here)

Static (time-invariant) components written here:
  σ_lgbm:      LightGBM conformal PI half-width (Stage 1 regression)
  σ_krige_base: kriging σ on LightGBM residuals (Stage 1)
  σ_response:  per-cell residual std from climate response OLS (1 − R²) × obs std (Stage 2 proxy)

Temporal component stored separately in gwl_kriging_std.zarr.

Legacy: σ_physics (HydroGEN) is kept as an optional input for benchmarking;
        σ_EDK (co-kriging SGS) kept for comparison with new σ_krige_base.

Outputs
-------
data/processed/baseline_uncertainty_stack.tif   — 4-band GeoTIFF (EPSG:5070)
    Band 1: σ_lgbm      (m)   — LightGBM conformal PI half-width
    Band 2: σ_krige_base (m)  — kriging σ on LightGBM residuals
    Band 3: σ_response  (m)   — climate response fit residual std proxy
    Band 4: mask_50km   (0/1) — 1 = within 50 km of a well

data/processed/total_uncertainty_m.tif          — 1-band GeoTIFF (EPSG:5070)
    σ_total = sqrt(σ_lgbm² + σ_krige_base² + σ_response²)  (m)

Usage:
    python -m src.evaluation.uncertainty_stack \\
        --lgbm-std      data/processed/baseline_lgbm_std_m.tif \\
        --krige-std     data/processed/baseline_kriging_std_m.tif \\
        --beta-r2       data/processed/beta_r2_1km.tif \\
        --mask          data/processed/well_density_mask.tif \\
        --output-dir    data/processed

    # Legacy / comparison:
    python -m src.evaluation.uncertainty_stack \\
        --physics  data/processed/hydrogen_wtd_uncertainty_1km.tif \\
        --edk-std  data/processed/baseline_kriging_std_m.tif \\
        --mask     data/processed/well_density_mask.tif \\
        --output-dir data/processed --legacy
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

TARGET_CRS = CRS.from_epsg(5070)
NODATA_OUT = np.float32(-9999.0)


def _read_band(path: Path) -> tuple[np.ndarray, rasterio.transform.Affine, rasterio.crs.CRS]:
    """Read band 1 of a GeoTIFF; return (array float32, transform, crs). nodata → NaN."""
    with rasterio.open(path) as src:
        arr = src.read(1, out_dtype=np.float32)
        nd = src.nodata if src.nodata is not None else -9999.0
        transform = src.transform
        crs = src.crs
    arr[arr == nd] = np.nan
    return arr, transform, crs


def _save_multiband(
    arrays: list[np.ndarray],
    transform: rasterio.transform.Affine,
    path: Path,
    band_descriptions: list[str],
) -> None:
    """Write a list of 2-D float32 arrays as a multi-band GeoTIFF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    height, width = arrays[0].shape
    with rasterio.open(
        path, "w",
        driver="GTiff",
        height=height,
        width=width,
        count=len(arrays),
        dtype=np.float32,
        crs=TARGET_CRS,
        transform=transform,
        nodata=float(NODATA_OUT),
        compress="lzw",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        for i, (arr, desc) in enumerate(zip(arrays, band_descriptions), start=1):
            out = np.where(np.isnan(arr), NODATA_OUT, arr).astype(np.float32)
            dst.write(out, i)
            dst.update_tags(i, description=desc)
    logger.info(f"Saved {len(arrays)}-band: {path}")


def _save_single(
    array: np.ndarray,
    transform: rasterio.transform.Affine,
    path: Path,
    description: str = "",
) -> None:
    """Write a single float32 2-D array as a GeoTIFF."""
    _save_multiband([array], transform, path, [description])


def build_uncertainty_stack(
    mask_path: Path,
    output_dir: Path,
    lgbm_std_path: Path | None = None,
    krige_std_path: Path | None = None,
    beta_r2_path: Path | None = None,
    physics_path: Path | None = None,
    edk_std_path: Path | None = None,
    legacy: bool = False,
) -> dict[str, Path]:
    """Combine uncertainty layers and write outputs.

    Parameters
    ----------
    mask_path:
        Well-density mask (1 = within 50 km of well).
    output_dir:
        Output directory.
    lgbm_std_path:
        LightGBM conformal PI half-width (Stage 1, new pipeline).
    krige_std_path:
        Kriging σ on LightGBM residuals (Stage 1 / legacy EDK).
    beta_r2_path:
        β-map OLS R² raster; σ_response ≈ sqrt(1 − R²) × domain_dtw_std.
    physics_path:
        HydroGEN σ_physics (legacy / benchmark; optional).
    edk_std_path:
        Legacy σ_EDK from co-kriging SGS (optional).
    legacy:
        If True, use physics + EDK combination (old pipeline); otherwise use
        lgbm_std + krige_std + response (new pipeline).

    Returns
    -------
    dict with keys ``"stack"`` and ``"total"``.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mask_arr, transform, crs = _read_band(mask_path)
    if crs.to_epsg() != 5070:
        raise ValueError(f"Mask CRS is {crs} — expected EPSG:5070.")

    if legacy:
        # ---------- Legacy (co-kriging) mode ----------
        sigma_edk, _, _ = _read_band(edk_std_path) if edk_std_path else (np.zeros_like(mask_arr), None, None)
        if physics_path and Path(physics_path).exists():
            sigma_physics, _, _ = _read_band(physics_path)
        else:
            sigma_physics = np.zeros_like(sigma_edk)
            logger.info("No physics uncertainty — σ_physics = 0")

        sigma_total = np.sqrt(
            np.where(np.isfinite(sigma_physics), sigma_physics ** 2, 0.0)
            + np.where(np.isfinite(sigma_edk), sigma_edk ** 2, np.nan)
        )
        bands = [sigma_physics, sigma_edk, mask_arr]
        descriptions = [
            "Band 1: sigma_physics (m) — HydroGEN ensemble spread",
            "Band 2: sigma_edk (m) — kriging σ (co-kriging SGS)",
            "Band 3: mask_50km (0/1)",
        ]
    else:
        # ---------- New pipeline mode ----------
        sigma_lgbm = _read_band(lgbm_std_path)[0] if lgbm_std_path and Path(lgbm_std_path).exists() else np.zeros_like(mask_arr)
        sigma_krige = _read_band(krige_std_path)[0] if krige_std_path and Path(krige_std_path).exists() else np.zeros_like(mask_arr)
        # σ_response proxy: sqrt(1 − R²) × median_dtw_range
        # where median_dtw_range ≈ 5 m as a domain-wide proxy (conservative)
        if beta_r2_path and Path(beta_r2_path).exists():
            r2_arr, _, _ = _read_band(beta_r2_path)
            r2_arr = np.clip(r2_arr, 0, 1)
            sigma_response = np.sqrt(np.maximum(1 - r2_arr, 0)) * 5.0
        else:
            sigma_response = np.zeros_like(mask_arr)

        sigma_total = np.sqrt(
            np.where(np.isfinite(sigma_lgbm), sigma_lgbm ** 2, 0.0)
            + np.where(np.isfinite(sigma_krige), sigma_krige ** 2, 0.0)
            + np.where(np.isfinite(sigma_response), sigma_response ** 2, np.nan)
        )
        bands = [sigma_lgbm, sigma_krige, sigma_response, mask_arr]
        descriptions = [
            "Band 1: sigma_lgbm (m) — LightGBM conformal PI half-width",
            "Band 2: sigma_krige_base (m) — kriging σ on LightGBM residuals",
            "Band 3: sigma_response (m) — climate response fit uncertainty proxy",
            "Band 4: mask_50km (0/1) — 1=within 50 km of well",
        ]

    # Diagnostics
    for name, arr in zip(
        ["σ_lgbm" if not legacy else "σ_physics",
         "σ_krige" if not legacy else "σ_EDK",
         "σ_total"],
        [bands[0], bands[1], sigma_total],
    ):
        valid = arr[np.isfinite(arr)]
        if len(valid):
            logger.info(
                "  %s: median=%.3f m  90th-pct=%.3f m  max=%.3f m",
                name, np.median(valid), np.percentile(valid, 90), valid.max(),
            )

    stack_path = output_dir / "baseline_uncertainty_stack.tif"
    _save_multiband(bands, transform, stack_path, descriptions)

    total_path = output_dir / "total_uncertainty_m.tif"
    _save_single(sigma_total, transform, total_path, "sigma_total (m)")

    return {"stack": stack_path, "total": total_path}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combine uncertainty layers into an explainable stack.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # New pipeline inputs
    parser.add_argument("--lgbm-std", type=Path, default=Path("data/processed/baseline_lgbm_std_m.tif"))
    parser.add_argument("--krige-std", type=Path, default=Path("data/processed/baseline_kriging_std_m.tif"))
    parser.add_argument("--beta-r2", type=Path, default=Path("data/processed/beta_r2_1km.tif"))
    parser.add_argument("--mask", type=Path, default=Path("data/processed/well_density_mask.tif"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    # Legacy / benchmark inputs
    parser.add_argument("--legacy", action="store_true", default=False,
                        help="Use legacy physics+EDK mode (requires --physics and --edk-std)")
    parser.add_argument("--physics", type=Path, default=None,
                        help="HydroGEN σ_physics raster (legacy mode)")
    parser.add_argument("--edk-std", type=Path, default=None,
                        help="Legacy σ_EDK from co-kriging SGS")
    args = parser.parse_args()

    if not args.mask.exists():
        raise FileNotFoundError(f"Mask not found: {args.mask}. Run `make baseline` first.")

    outputs = build_uncertainty_stack(
        mask_path=args.mask,
        output_dir=args.output_dir,
        lgbm_std_path=args.lgbm_std,
        krige_std_path=args.krige_std,
        beta_r2_path=args.beta_r2,
        physics_path=args.physics,
        edk_std_path=args.edk_std,
        legacy=args.legacy,
    )
    logger.info("Uncertainty stack → %s", outputs["stack"])
    logger.info("Total uncertainty → %s", outputs["total"])
    logger.info(
        "Verify: σ_krige should be largest far from wells; σ_response largest in complex terrain."
    )


if __name__ == "__main__":
    main()
