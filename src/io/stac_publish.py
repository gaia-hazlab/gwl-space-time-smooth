"""Generate STAC items with GAIA four-part provenance for GWL outputs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pystac
import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform_bounds

logger = logging.getLogger(__name__)

# GAIA provenance field prefix
_GAIA_PREFIX = "gaia"


def _raster_bbox_wgs84(raster_path: Path) -> tuple[float, float, float, float]:
    """Return (west, south, east, north) in WGS84 from a raster's native CRS."""
    with rasterio.open(raster_path) as src:
        bounds = src.bounds
        left, bottom, right, top = transform_bounds(
            src.crs, CRS.from_epsg(4326), *bounds
        )
    return (left, bottom, right, top)


def make_stac_item(
    product_path: Path,
    product_id: str,
    source: str,
    measurement: str,
    resolution_m: int,
    uncertainty_path: Path | None = None,
    datetime_range: tuple[datetime, datetime] | None = None,
    extra_properties: dict | None = None,
) -> pystac.Item:
    """Generate a STAC item for a GWL output product.

    Parameters
    ----------
    product_path:
        Path to the GeoTIFF or Zarr output (must exist).
    product_id:
        Unique STAC item ID (e.g. "gwl_dtw_wa_2024_01").
    source:
        GAIA provenance source (e.g. "USGS-NWIS + 3DEP + SOLUS100 + PRISM").
    measurement:
        What is measured (e.g. "depth-to-water (m below surface)").
    resolution_m:
        Spatial resolution in metres (typically 90 for the WA 90 m outputs).
    uncertainty_path:
        Optional companion uncertainty raster/Zarr.
    datetime_range:
        (start, end) UTC datetimes for time-varying products. None for static products.
    extra_properties:
        Additional properties to merge into the STAC item.

    Returns
    -------
    pystac.Item
        STAC item (not uploaded — caller saves to disk or pushes to catalog).
    """
    product_path = Path(product_path)
    if not product_path.exists():
        raise FileNotFoundError(product_path)

    # Spatial extent — try raster, fall back to PNW default
    try:
        bbox = _raster_bbox_wgs84(product_path)
    except Exception:
        logger.warning("Could not read bbox from %s — using PNW default", product_path)
        bbox = (-124.9, 42.0, -116.5, 49.0)

    item_datetime = datetime_range[0] if datetime_range else datetime.now(tz=timezone.utc)

    properties: dict = {
        f"{_GAIA_PREFIX}:source": source,
        f"{_GAIA_PREFIX}:measurement": measurement,
        f"{_GAIA_PREFIX}:resolution_m": resolution_m,
        f"{_GAIA_PREFIX}:uncertainty_path": str(uncertainty_path) if uncertainty_path else None,
        "datetime": item_datetime.isoformat(),
        "product_path": str(product_path),
    }
    if datetime_range:
        properties["start_datetime"] = datetime_range[0].isoformat()
        properties["end_datetime"] = datetime_range[1].isoformat()
    if extra_properties:
        properties.update(extra_properties)

    item = pystac.Item(
        id=product_id,
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [bbox[0], bbox[1]],
                [bbox[2], bbox[1]],
                [bbox[2], bbox[3]],
                [bbox[0], bbox[3]],
                [bbox[0], bbox[1]],
            ]],
        },
        bbox=list(bbox),
        datetime=item_datetime,
        properties=properties,
    )

    suffix = product_path.suffix or ".zarr"
    media_type = (
        pystac.MediaType.COG if suffix in {".tif", ".tiff"} else "application/vnd.zarr"
    )
    item.add_asset(
        "data",
        pystac.Asset(href=str(product_path), media_type=media_type, roles=["data"]),
    )
    if uncertainty_path and Path(uncertainty_path).exists():
        item.add_asset(
            "uncertainty",
            pystac.Asset(
                href=str(uncertainty_path),
                media_type=media_type,
                roles=["uncertainty"],
            ),
        )

    return item


def save_stac_item(item: pystac.Item, output_dir: Path | None = None) -> Path:
    """Write a STAC item JSON alongside its data product.

    Parameters
    ----------
    item:
        STAC item to serialize.
    output_dir:
        Directory for the sidecar JSON. Defaults to the directory of the data asset.

    Returns
    -------
    Path
        Path of the written JSON file.
    """
    if output_dir is None:
        data_href = item.assets.get("data")
        if data_href:
            output_dir = Path(data_href.href).parent
        else:
            output_dir = Path(".")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{item.id}_stac_item.json"
    with open(out_path, "w") as fh:
        json.dump(item.to_dict(), fh, indent=2, default=str)
    logger.info("STAC item written to %s", out_path)
    return out_path
