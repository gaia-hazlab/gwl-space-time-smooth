"""Export the *dynamic* hydrological state to LandLab-ready fields for the landslide pipeline.

Division of labour with ``gaia-hazlab/landslide-data-prep``: that repo gathers and harmonises the
**static** stack (DEM, SOLUS soil, NLCD -> cohesion/phi/LAI). This soil-reanalysis owns the
**dynamic / hydrological** state and exports only those fields, on the *same grid* so they drop onto
the static stack cell-for-cell. The consumer is LandLab's infinite-slope ``LandslideProbability``.

Exported (dynamic) fields, in the DataHub canonical vocabulary:

  * ``water_table__depth``               depth to water table [m]  (mean and seasonal-high state)
  * ``soil_moisture__saturation_fraction`` S = theta / porosity  [-]
  * ``soil_water__recharge_rate``        groundwater recharge  [mm day^-1]  (from the water budget)

Static soil-hydromechanical parameters (K_sat, transmissivity, texture, thickness) are *not*
exported here -- they are LandLab data-prep's job. Where they must agree with our hydrology, both
sides select the same pedotransfer via ``src.models.soil_hydraulics``.

Format: ESRI ASCII (``.asc``, GDAL AAIGrid) that ``landlab.io.esri_ascii`` loads directly, plus a
provenance JSON manifest. Grid parity is enforced by reprojecting each field onto a caller-supplied
template grid before writing. Resolution note: our native grid is 90 m EPSG:5070; exporting onto a
finer LandLab AOI grid *resamples* (does not add information) -- the manifest records native vs
export resolution so a downscaled cell is never mistaken for a native observation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import rioxarray  # noqa: F401  (registers the .rio accessor)
import xarray as xr

logger = logging.getLogger(__name__)

NODATA = -9999.0

# our source variable -> (canonical LandLab/DataHub field name, units). Kept as an explicit,
# editable crosswalk so field names can be reconciled with the LandLab team without code churn.
CANONICAL = {
    "water_table__depth": ("water_table__depth", "m"),
    "saturation_fraction": ("soil_moisture__saturation_fraction", "1"),
    "recharge": ("soil_water__recharge_rate", "mm/day"),
}


def saturation_fraction(theta, porosity) -> np.ndarray:
    """Degree of saturation S = theta / porosity, clipped to [0, 1]. NaN-safe."""
    theta = np.asarray(theta, dtype="float64")
    n = np.asarray(porosity, dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(n > 0, theta / n, np.nan)
    return np.clip(s, 0.0, 1.0)


def seasonal_high_water_table(dtw_time, quantile: float = 0.1, dim: str = "time"):
    """Seasonal-high water table = the shallow-tail quantile of depth-to-water over time.

    The landslide-relevant state is the *wet-season high* table (small depth-to-water), not the
    annual mean. Depth-to-water is positive-down, so the high table is the LOW quantile of DTW
    (default the 10th percentile). Returns a (y, x) DataArray/array.
    """
    if isinstance(dtw_time, xr.DataArray):
        return dtw_time.quantile(quantile, dim=dim).drop_vars("quantile", errors="ignore")
    return np.nanquantile(np.asarray(dtw_time, dtype="float64"), quantile, axis=0)


def align_to_grid(da: xr.DataArray, template: xr.DataArray, resampling: str = "bilinear") -> xr.DataArray:
    """Reproject/resample ``da`` onto ``template``'s grid (CRS, resolution, extent) for parity."""
    from rasterio.enums import Resampling

    how = getattr(Resampling, resampling)
    return da.rio.reproject_match(template, resampling=how)


def write_landlab_ascii(da: xr.DataArray, path: str | Path, nodata: float = NODATA) -> Path:
    """Write a 2-D DataArray as an ESRI ASCII grid (``.asc``) that landlab.io.esri_ascii reads."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = da.copy()
    if out.rio.crs is None:
        out = out.rio.write_crs("EPSG:5070")
    out = out.fillna(nodata)
    out.attrs.pop("_FillValue", None)
    out.encoding.pop("_FillValue", None)
    out.rio.write_nodata(nodata, inplace=True)
    out.rio.to_raster(path, driver="AAIGrid")            # Arc/Info ASCII == ESRI ASCII (LandLab)
    return path


@dataclass
class DynamicField:
    """One dynamic field to export: our key (see CANONICAL), its data, and the epoch label."""

    key: str
    data: xr.DataArray
    epoch: str = "mean"                                  # e.g. "mean", "seasonal_high", "2021-11"
    extra: dict = field(default_factory=dict)


def export_dynamic_bundle(fields: list[DynamicField], out_dir: str | Path,
                          template: xr.DataArray | None = None,
                          native_res_m: float = 90.0, write_cog: bool = True) -> dict:
    """Export dynamic fields to canonical ``.asc`` (+ optional COG) on the template grid + a manifest.

    Each field is reprojected onto ``template`` (if given) for grid parity, written to
    ``<canonical_name>__<epoch>.asc`` (LandLab-ready) and, when ``write_cog``, a matching COG. A
    ``landlab_export_manifest.json`` records the canonical name, units, epoch, native vs export
    resolution, and grid, so provenance travels with the data. Returns the manifest dict.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    export_res_m = native_res_m
    if template is not None:
        try:
            export_res_m = float(abs(template.rio.resolution()[0]))
        except Exception:
            pass

    entries = []
    for f in fields:
        if f.key not in CANONICAL:
            raise ValueError(f"unknown dynamic field key {f.key!r}; choose from {tuple(CANONICAL)}")
        canonical, units = CANONICAL[f.key]
        da = align_to_grid(f.data, template) if template is not None else f.data
        stem = f"{canonical}__{f.epoch}"
        asc = write_landlab_ascii(da, out_dir / f"{stem}.asc")
        cog = None
        if write_cog:
            cog = out_dir / f"{stem}.tif"
            dc = da.copy()
            if dc.rio.crs is None:
                dc = dc.rio.write_crs("EPSG:5070")
            dc.rio.to_raster(cog, driver="COG")
        entries.append({
            "key": f.key, "canonical_name": canonical, "units": units, "epoch": f.epoch,
            "asc": asc.name, "cog": (cog.name if cog else None),
            "native_resolution_m": native_res_m, "export_resolution_m": export_res_m,
            "resampled": template is not None and abs(export_res_m - native_res_m) > 1e-6,
            **f.extra,
        })
        logger.info("exported %s (%s) -> %s", canonical, f.epoch, asc.name)

    manifest = {
        "product": "gaia-soil-reanalysis dynamic hydrological export for LandLab",
        "consumer": "landlab.components.LandslideProbability",
        "crs": str((template if template is not None else fields[0].data).rio.crs),
        "native_resolution_m": native_res_m,
        "export_resolution_m": export_res_m,
        "note": ("Dynamic fields only; static stack (DEM/SOLUS/NLCD) is provided by "
                 "gaia-hazlab/landslide-data-prep. A resampled cell is not a native observation."),
        "fields": entries,
    }
    (out_dir / "landlab_export_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
