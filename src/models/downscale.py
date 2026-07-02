"""Statistical downscaling + uncertainty-budget helpers (gaia-soil-hydromechanics).

Both live state variables are produced as **fine 90 m static structure + coarse dynamic
signal**, so every product involves a downscaling step that must be tracked, not hidden:

  * soil moisture — 90 m SOLUS→Saxton-Rawls envelope × 4 km TerraClimate wetness (downscaled).
  * groundwater level — 90 m RF baseline + coarse-kriged monthly well anomaly (downscaled).

This module centralises (a) the bilinear downscaling operator, (b) a *representativeness*
uncertainty term for the information the coarse dynamic field cannot resolve within a coarse
footprint, and (c) a small provenance/uncertainty-budget record so the HTML dashboard can show
exactly which resolution each quantity came from and how each operation adds to σ.

Uncertainty is combined in quadrature (assumed independent components):
    σ_total = sqrt( Σ_i σ_i² ),
with named components (static / dynamic / downscaling) kept separate for the budget figure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import rioxarray  # noqa: F401
import xarray as xr


@dataclass
class ProvStep:
    """One provenance step: a quantity, where it came from, and the operation applied."""

    quantity: str
    source: str
    source_res_m: float
    target_res_m: float
    method: str

    def as_row(self) -> dict:
        return {
            "quantity": self.quantity, "source": self.source,
            "source_res_m": self.source_res_m, "target_res_m": self.target_res_m,
            "method": self.method,
        }


@dataclass
class UncertaintyBudget:
    """Named 1σ fields combined in quadrature; keeps components for the budget figure."""

    components: dict[str, np.ndarray] = field(default_factory=dict)
    provenance: list[ProvStep] = field(default_factory=list)

    def add(self, name: str, sigma: np.ndarray) -> None:
        self.components[name] = np.asarray(sigma, dtype="float64")

    def total(self) -> np.ndarray:
        stack = np.stack([np.nan_to_num(v) ** 2 for v in self.components.values()], axis=0)
        valid = np.any(np.stack([np.isfinite(v) for v in self.components.values()]), axis=0)
        tot = np.sqrt(stack.sum(axis=0))
        return np.where(valid, tot, np.nan)

    def fractions(self) -> dict[str, float]:
        """Domain-mean variance share of each component (sums to ~1)."""
        var = {k: float(np.nanmean(v ** 2)) for k, v in self.components.items()}
        s = sum(var.values()) or 1.0
        return {k: v / s for k, v in var.items()}


def bilinear_downscale(coarse: xr.DataArray, target_like: xr.DataArray) -> xr.DataArray:
    """Bilinearly resample a coarse field onto the fine ``target_like`` grid (CRS-aware).

    ``coarse`` must carry a CRS + spatial dims; ``target_like`` defines the fine grid.
    This is the *statistical downscaling* operator — it adds no new fine-scale information,
    it interpolates; the missing information is accounted for in :func:`representativeness_sigma`.
    """
    from rasterio.enums import Resampling

    if coarse.rio.crs is None:
        raise ValueError("coarse field needs a CRS (use .rio.write_crs).")
    return coarse.rio.reproject_match(target_like, resampling=Resampling.bilinear)


def representativeness_sigma(
    fine_static: xr.DataArray, coarse_res_m: float, target_res_m: float, scale: float = 1.0
) -> np.ndarray:
    """1σ representativeness error from downscaling a uniform coarse signal.

    Estimated as the within-coarse-footprint standard deviation of the *fine static* field:
    where fine structure varies a lot inside one coarse cell, applying a single coarse dynamic
    value there is correspondingly more uncertain. Computed by block-aggregating the fine field
    to the coarse footprint (std), then mapping back to the fine grid.
    """
    factor = max(int(round(coarse_res_m / target_res_m)), 1)
    # Block standard deviation over ~coarse-cell footprints, then broadcast back to fine grid.
    block_std = fine_static.coarsen(x=factor, y=factor, boundary="pad").std()
    sigma = block_std.rio.reproject_match(
        fine_static, resampling=__import__("rasterio").enums.Resampling.nearest
    )
    out = np.asarray(sigma.values, dtype="float64") * float(scale)
    return np.where(np.isfinite(fine_static.values), out, np.nan)
