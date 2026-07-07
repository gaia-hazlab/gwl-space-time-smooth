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


def apply_confidence_mask(da: xr.DataArray, mask: xr.DataArray) -> xr.DataArray:
    """Blank ``da`` (-> NaN) where ``mask`` is not positive, so unsupported cells export as no-data.

    ``mask`` is the variogram-driven well-density / confidence mask (1 = supported, 0 = masked). It
    is aligned to ``da`` first (nearest, to preserve the 0/1 classes)."""
    m = mask.rio.reproject_match(da, resampling=_nearest()) if mask.shape != da.shape else mask
    return da.where(m > 0)


def _nearest():
    from rasterio.enums import Resampling
    return Resampling.nearest


def _georef_latlon(da: xr.DataArray) -> xr.DataArray:
    """Give a lat/lon DataArray the rio spatial dims + EPSG:4326 CRS so it can be reprojected."""
    if "lat" in da.dims or "lon" in da.dims:
        da = da.rename({"lat": "y", "lon": "x"})
    da = da.rio.set_spatial_dims(x_dim="x", y_dim="y", inplace=False)
    return da.rio.write_crs("EPSG:4326") if da.rio.crs is None else da


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
    """One dynamic field to export: our key (see CANONICAL), its data, and the epoch label.

    ``sigma`` (optional) is the matching per-cell 1σ, written as a ``<name>_std`` sidecar so LandLab
    can ingest uncertainty, not just a mean field."""

    key: str
    data: xr.DataArray
    epoch: str = "mean"                                  # e.g. "mean", "seasonal_high", "2021-11"
    sigma: xr.DataArray | None = None
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
        # optional per-cell 1σ sidecar
        std_name = None
        if f.sigma is not None:
            sig = align_to_grid(f.sigma, template) if template is not None else f.sigma
            std_name = write_landlab_ascii(sig, out_dir / f"{stem}_std.asc").name
        cog = None
        if write_cog:
            cog = out_dir / f"{stem}.tif"
            dc = da.copy()
            if dc.rio.crs is None:
                dc = dc.rio.write_crs("EPSG:5070")
            dc.rio.to_raster(cog, driver="COG")
        entries.append({
            "key": f.key, "canonical_name": canonical, "units": units, "epoch": f.epoch,
            "asc": asc.name, "std_asc": std_name, "cog": (cog.name if cog else None),
            "native_resolution_m": native_res_m, "export_resolution_m": export_res_m,
            "resampled": template is not None and abs(export_res_m - native_res_m) > 1e-6,
            **f.extra,
        })
        logger.info("exported %s (%s) -> %s%s", canonical, f.epoch, asc.name,
                    f" (+σ {std_name})" if std_name else "")

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


# ---------------------------------------------------------------------------
# Loaders: assemble DynamicFields from the real reanalysis products on disk
# ---------------------------------------------------------------------------
def load_water_table_field(dtw_tif, rf_std_tif=None, krige_std_tif=None, mask_tif=None,
                           dtw_series=None, seasonal_quantile=0.1):
    """Water-table depth field(s): the mean, its 1σ (rf ⊕ kriging in quadrature), masked to the
    supported domain. If ``dtw_series`` (a time-stack of depth-to-water) is given, also a
    seasonal-high field. Returns a list of :class:`DynamicField`."""
    import rioxarray as rxr

    dtw = rxr.open_rasterio(dtw_tif, masked=True).squeeze("band", drop=True)
    sig = None
    parts = [rxr.open_rasterio(p, masked=True).squeeze("band", drop=True)
             for p in (rf_std_tif, krige_std_tif) if p is not None]
    if parts:
        sig = np.sqrt(sum(p ** 2 for p in parts))
    if mask_tif is not None:
        mask = rxr.open_rasterio(mask_tif, masked=True).squeeze("band", drop=True)
        dtw = apply_confidence_mask(dtw, mask)
        if sig is not None:
            sig = apply_confidence_mask(sig, mask)
    fields = [DynamicField("water_table__depth", dtw, epoch="mean", sigma=sig)]
    if dtw_series is not None:
        high = seasonal_high_water_table(dtw_series, quantile=seasonal_quantile)
        fields.append(DynamicField("water_table__depth", high, epoch="seasonal_high",
                                   extra={"quantile": seasonal_quantile}))
    return fields


def load_saturation_field(sm_zarr):
    """Temporal-mean saturation fraction S = θ/θ_sat (+1σ) from the soil-moisture Zarr."""
    ds = xr.open_zarr(sm_zarr)
    s = saturation_fraction(ds["theta"], ds["theta_sat"])              # (time, lat, lon)
    s = xr.DataArray(s, dims=ds["theta"].dims, coords=ds["theta"].coords)
    s_mean = _georef_latlon(s.mean("time"))
    s_std = _georef_latlon((ds["theta_std"] / ds["theta_sat"]).mean("time"))
    return DynamicField("saturation_fraction", s_mean, epoch="mean", sigma=s_std)


def load_recharge_field(forcing_zarr, sm_zarr, root_depth_m=1.0):
    """Gridded recharge (temporal mean, +max in extra) from the coupled water budget over the
    TerraClimate forcing grid; σ ≈ 0.1·mean (the DataHub convention)."""
    import pandas as pd

    from src.models.water_budget import coupled_water_budget

    fz = xr.open_zarr(forcing_zarr)
    sm = xr.open_zarr(sm_zarr)
    wb = coupled_water_budget(fz["precip_mm"].values, fz["pet_mm"].values,
                              sm["theta_wp"].values, sm["theta_fc"].values, sm["theta_sat"].values,
                              root_depth_m=root_depth_m)
    tmpl = fz["precip_mm"]                                              # (time, lat, lon) for coords
    # The monthly budget yields recharge in mm per month; convert to the canonical mm day⁻¹ rate
    # by each month's length before taking temporal statistics.
    dim = pd.to_datetime(fz["time"].values).days_in_month.values.astype("float64")
    rech = xr.DataArray(wb.recharge_mm / dim[:, None, None], dims=tmpl.dims, coords=tmpl.coords)
    mean = _georef_latlon(rech.mean("time"))
    mx = _georef_latlon(rech.max("time"))
    return DynamicField("recharge", mean, epoch="mean", sigma=0.1 * abs(mean),
                        extra={"max_asc_note": "max also available", "max_epoch": "max"}), \
        DynamicField("recharge", mx, epoch="max")


def main():
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Export the dynamic hydrological state as LandLab-ready fields.")
    d = "data/processed"
    p.add_argument("--dtw", default=f"{d}/baseline_dtw_m.tif")
    p.add_argument("--rf-std", default=f"{d}/baseline_rf_std_m.tif")
    p.add_argument("--krige-std", default=f"{d}/baseline_kriging_std_m.tif")
    p.add_argument("--mask", default=f"{d}/well_density_mask.tif")
    p.add_argument("--sm-zarr", default=f"{d}/soil_moisture_monthly_puget.zarr")
    p.add_argument("--forcing-zarr", default=f"{d}/terraclimate_monthly_puget.zarr")
    p.add_argument("--template", default=None, help="Raster defining the export grid (default: --dtw grid).")
    p.add_argument("--out-dir", default=f"{d}/landlab_export")
    p.add_argument("--root-depth-m", type=float, default=1.0)
    p.add_argument("--no-recharge", action="store_true")
    p.add_argument("--no-cog", action="store_true")
    args = p.parse_args()

    import rioxarray as rxr

    template = rxr.open_rasterio(args.template or args.dtw, masked=True).squeeze("band", drop=True)
    fields = []
    fields += load_water_table_field(args.dtw, args.rf_std, args.krige_std, args.mask)
    try:
        fields.append(load_saturation_field(args.sm_zarr))
    except Exception as exc:                                            # pragma: no cover
        logger.warning("saturation fraction skipped (%s)", exc)
    if not args.no_recharge:
        try:
            fields += list(load_recharge_field(args.forcing_zarr, args.sm_zarr, args.root_depth_m))
        except Exception as exc:                                        # pragma: no cover
            logger.warning("recharge skipped (%s); needs the forcing + envelope Zarrs", exc)

    manifest = export_dynamic_bundle(fields, args.out_dir, template=template,
                                     write_cog=not args.no_cog)
    logger.info("wrote %d fields to %s", len(manifest["fields"]), args.out_dir)


if __name__ == "__main__":
    main()
