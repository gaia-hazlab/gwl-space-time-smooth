"""Helpers for reading and writing xarray.DataTree in GAIA cresst-format Zarr."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

logger = logging.getLogger(__name__)

# Standard GWL DataTree node names
GWL_NODES = (
    "baseline",   # wte_m, dtw_m, std_m — long-term LightGBM + kriged residual
    "climate",    # spi3, swe_anom, pdo, ar_count — forcing indices (time, y, x)
    "beta",       # b_spi3, b_swe, b_pdo, b_ar, r2 — static β maps (y, x)
    "anomaly",    # wte_anomaly_m, std_m — climate-response reconstruction (time, y, x)
    "residual",   # wte_residual_m, std_m — Stage 3 kriged residuals (time, y, x)
    "final",      # wte_m, dtw_m, total_std_m — assembled product (time, y, x)
    "mask",       # well_density_50km — boolean (y, x)
)

# CF grid-mapping attribute for EPSG:5070 Albers Equal-Area
_GRID_MAPPING_NAME = "albers_conical_equal_area"

_CF_GRID_MAPPING_ATTRS: dict[str, Any] = {
    "grid_mapping_name": _GRID_MAPPING_NAME,
    "standard_parallel": (29.5, 45.5),
    "longitude_of_central_meridian": -96.0,
    "latitude_of_projection_origin": 23.0,
    "false_easting": 0.0,
    "false_northing": 0.0,
    "semi_major_axis": 6378137.0,
    "inverse_flattening": 298.257222101,
    "crs_wkt": "EPSG:5070",
}


def add_cf_attrs(
    da: xr.DataArray,
    long_name: str,
    units: str,
    standard_name: str = "",
    grid_mapping: str = _GRID_MAPPING_NAME,
) -> xr.DataArray:
    """Attach CF-convention attributes to a DataArray.

    Parameters
    ----------
    da:
        Input array.
    long_name:
        Human-readable description.
    units:
        Udunits-compatible unit string (e.g. "m", "m s-1", "1").
    standard_name:
        CF standard name where one exists; empty string otherwise.
    grid_mapping:
        Name of the grid-mapping coordinate variable (default: EPSG:5070 Albers).
    """
    attrs = {
        "long_name": long_name,
        "units": units,
        "grid_mapping": grid_mapping,
    }
    if standard_name:
        attrs["standard_name"] = standard_name
    return da.assign_attrs(attrs)


def _add_grid_mapping_var(ds: xr.Dataset) -> xr.Dataset:
    """Attach an EPSG:5070 grid_mapping scalar variable to the dataset."""
    gm = xr.DataArray(np.int32(0), attrs=_CF_GRID_MAPPING_ATTRS)
    return ds.assign({_GRID_MAPPING_NAME: gm})


def write_datatree(
    dt: xr.DataTree,
    path: Path,
    chunks: dict[str, int] | None = None,
    consolidated: bool = True,
) -> None:
    """Write a GWL DataTree to Zarr (cresst-compatible format).

    Each node is written as a Zarr group. Static nodes (baseline, beta, mask) are
    written without a time dimension; time-varying nodes use chunks along time.

    Parameters
    ----------
    dt:
        DataTree following the GWL_NODES schema.
    path:
        Output Zarr store path.
    chunks:
        Chunk sizes. Defaults to {"time": 12, "y": 256, "x": 256}.
    consolidated:
        Write consolidated Zarr metadata (recommended for s3 access).
    """
    if chunks is None:
        chunks = {"time": 12, "y": 256, "x": 256}
    path = Path(path)
    logger.info("Writing DataTree to %s", path)
    dt.to_zarr(path, consolidated=consolidated, mode="w")
    logger.info("DataTree written: %d nodes", len(list(dt.subtree)))


def read_datatree(path: Path) -> xr.DataTree:
    """Read a GWL DataTree from a Zarr store.

    Parameters
    ----------
    path:
        Path to the Zarr store.

    Returns
    -------
    xr.DataTree
        Loaded DataTree.
    """
    path = Path(path)
    logger.info("Reading DataTree from %s", path)
    return xr.open_datatree(path, engine="zarr", consolidated=True)


def build_gwl_datatree(
    baseline: xr.Dataset | None = None,
    climate: xr.Dataset | None = None,
    beta: xr.Dataset | None = None,
    anomaly: xr.Dataset | None = None,
    residual: xr.Dataset | None = None,
    final: xr.Dataset | None = None,
    mask: xr.Dataset | None = None,
    global_attrs: dict[str, Any] | None = None,
) -> xr.DataTree:
    """Assemble a GWL DataTree from component datasets.

    All datasets must share the same spatial grid (EPSG:5070, 1 km).
    Pass None for any node not yet computed.

    Parameters
    ----------
    baseline:
        Long-term WTE/DTW from LightGBM + regression kriging.
    climate:
        Climate forcing index fields (SPI-3, SWE, PDO) on the grid.
    beta:
        Static β-coefficient maps.
    anomaly:
        Climate-response-reconstructed GWL anomaly.
    residual:
        Stage 3 kriged residuals.
    final:
        Fully assembled GWL product.
    mask:
        Well-density binary mask.
    global_attrs:
        Global metadata attached to the root node.
    """
    nodes: dict[str, xr.Dataset] = {}
    for name, ds in (
        ("baseline", baseline),
        ("climate", climate),
        ("beta", beta),
        ("anomaly", anomaly),
        ("residual", residual),
        ("final", final),
        ("mask", mask),
    ):
        if ds is not None:
            nodes[f"/{name}"] = _add_grid_mapping_var(ds)

    root_attrs = {
        "Conventions": "CF-1.8",
        "institution": "GAIA HazLab — University of Washington",
        "source": "gwl-space-time-smooth",
        "crs": "EPSG:5070 (NAD83 / CONUS Albers)",
        "spatial_resolution": "1000 m",
        "temporal_resolution": "monthly",
    }
    if global_attrs:
        root_attrs.update(global_attrs)

    root_ds = xr.Dataset(attrs=root_attrs)
    nodes["/"] = root_ds
    return xr.DataTree.from_dict(nodes)
