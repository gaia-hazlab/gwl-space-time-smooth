"""Statistical downscaling + uncertainty-budget helpers (gaia-soil-hydromechanics).

Both live state variables are produced as **fine 90 m static structure + coarse dynamic
signal**, so every product involves a downscaling step that must be tracked, not hidden:

  * soil moisture — 90 m SOLUS→Saxton-Rawls envelope × 4 km TerraClimate wetness (downscaled).
  * groundwater level — 90 m RF baseline + coarse-kriged monthly well anomaly (downscaled).

This module centralises (a) a **modular downscaling operator** (see below), (b) a
*representativeness* uncertainty term for the information the coarse dynamic field cannot
resolve within a coarse footprint, (c) an **upscaling** operator for native-scale calibration
against coarse sensors, and (d) a small provenance/uncertainty-budget record.

**Downscaling is modular, and the default is deliberately the simplest thing.** The baseline
``"bilinear"`` downscaler is *pure resampling* — it adds **no** new fine-scale information; the
representativeness σ measures exactly what it cannot recover. It sits behind a registry
(``register_downscaler`` / ``downscale(method=...)``) so smarter, **data-informed or
model-driven** downscalers can be swapped in **without touching any call site**. Each downscaler
receives the fine static ``covariates`` (envelope / terrain / baseline) so it can exploit them;
bilinear ignores them. Candidate future methods (not yet implemented): covariate/regression
downscaling on the fine static field, quantile mapping / bias correction, ML super-resolution
trained on high-resolution observations (SMAP-to-fine, NISAR), and physics-based redistribution
(TWI / TOPMODEL for θ, poroelastic head propagation for GWL).

Uncertainty is combined in quadrature (assumed independent components):
    σ_total = sqrt( Σ_i σ_i² ),
with named components (static / dynamic / downscaling / forcing) kept separate for the budget.
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


def _ensure_spatial_dims(da: xr.DataArray) -> xr.DataArray:
    """Set rioxarray spatial dims explicitly (survives .isel/.mean, which reset the accessor).

    Needed because some drivers' lat/lon coords lack CF attributes, so rioxarray cannot
    auto-detect them after an indexing op.
    """
    dims = set(da.dims)
    if "x" in dims and "y" in dims:
        return da
    xd = next((d for d in ("lon", "longitude", "x") if d in dims), None)
    yd = next((d for d in ("lat", "latitude", "y") if d in dims), None)
    if xd and yd:
        return da.rio.set_spatial_dims(x_dim=xd, y_dim=yd)
    return da


# --- Modular downscaling operator --------------------------------------------
# The registry is the seam for smarter downscalers. Each entry has the signature
# ``fn(coarse, target_like, covariates=None) -> DataArray``. Default = "bilinear" (resampling).
_DOWNSCALERS: dict = {}


def register_downscaler(name: str):
    """Register a downscaler under ``name`` so ``downscale(method=name)`` can dispatch to it.

    A downscaler MUST accept (coarse, target_like, covariates=None) and return a DataArray on
    the target grid. ``covariates`` is a dict of fine static fields (envelope, terrain, baseline)
    that data-informed / model-driven methods may exploit; the bilinear baseline ignores it.
    """
    def _deco(fn):
        _DOWNSCALERS[name] = fn
        return fn
    return _deco


@register_downscaler("bilinear")
def _bilinear(coarse: xr.DataArray, target_like: xr.DataArray, covariates=None) -> xr.DataArray:
    """BASELINE downscaler: bilinear resampling. Adds **no** new fine-scale information.

    Pure interpolation onto ``target_like``; the unresolved sub-footprint structure is what
    :func:`representativeness_sigma` charges to the uncertainty budget. Swap in a smarter,
    covariate-aware method via :func:`register_downscaler` when available.
    """
    from rasterio.enums import Resampling

    coarse = _ensure_spatial_dims(coarse)
    if coarse.rio.crs is None:
        raise ValueError("coarse field needs a CRS (use .rio.write_crs).")
    return coarse.rio.reproject_match(target_like, resampling=Resampling.bilinear)


def downscale(coarse: xr.DataArray, target_like: xr.DataArray, method: str = "bilinear",
              covariates=None) -> xr.DataArray:
    """Downscale ``coarse`` onto ``target_like`` using a registered method (default bilinear).

    This is the single seam every product goes through, so the downscaling strategy can be
    upgraded globally by registering a smarter method and passing ``method=...`` — call sites
    do not change.
    """
    if method not in _DOWNSCALERS:
        raise ValueError(f"unknown downscaler {method!r}; registered: {sorted(_DOWNSCALERS)}")
    return _DOWNSCALERS[method](coarse, target_like, covariates=covariates)


def bilinear_downscale(coarse: xr.DataArray, target_like: xr.DataArray) -> xr.DataArray:
    """Back-compat alias for ``downscale(..., method='bilinear')`` (the resampling baseline)."""
    return downscale(coarse, target_like, method="bilinear")


def upscale_to_grid(fine: xr.DataArray, coarse_like: xr.DataArray) -> xr.DataArray:
    """Area-mean **upscale** a fine field onto a coarse product grid (the inverse operator).

    Calibration/validation against a remote-sensing product (SMAP, NISAR, NLDAS, GRACE) must
    happen at the product's *native* resolution — you upscale the fine model to the sensor
    grid with proper area averaging, not downscale the sensor to 90 m. This is that operator.
    """
    from rasterio.enums import Resampling

    fine = _ensure_spatial_dims(fine)
    coarse_like = _ensure_spatial_dims(coarse_like)
    if fine.rio.crs is None:
        raise ValueError("fine field needs a CRS (use .rio.write_crs).")
    return fine.rio.reproject_match(coarse_like, resampling=Resampling.average)


def native_scale_comparison(fine_model: xr.DataArray, coarse_product: xr.DataArray) -> dict:
    """Compare a fine model to a coarse product **at the product's native scale**.

    Upscales ``fine_model`` (area-mean) onto ``coarse_product``'s grid, then returns bias,
    RMSE and correlation over co-located, finite cells — the scale at which calibration or
    assimilation against SMAP/NISAR/NLDAS/GRACE should be scored (upscale-then-compare, so a
    coarse footprint is matched by the correct areal average of the fine field, not a point).
    """
    up = upscale_to_grid(fine_model, coarse_product)
    a = np.asarray(up.values, dtype="float64").ravel()
    b = np.asarray(coarse_product.values, dtype="float64").ravel()
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if a.size < 3:
        return {"n": int(a.size), "bias": np.nan, "rmse": np.nan, "corr": np.nan}
    return {"n": int(a.size), "bias": float(np.mean(a - b)),
            "rmse": float(np.sqrt(np.mean((a - b) ** 2))),
            "corr": float(np.corrcoef(a, b)[0, 1])}


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
