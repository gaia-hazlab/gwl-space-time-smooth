"""Fetch monthly TerraClimate climate/water-balance fields (dynamic soil-moisture driver).

TerraClimate (Abatzoglou et al. 2018) is a 1/24° (~4 km) global monthly climatic
water-balance reanalysis, 1958→present. It supplies the **dynamic** driver for the
gaia-soil-hydromechanics soil-moisture state module: monthly precipitation and reference
evapotranspiration force a Thornthwaite–Mather bucket whose capacity comes from the
**static** SOLUS texture envelope (see ``src.models.soil_moisture``). TerraClimate's own
``soil`` (column soil-water storage, mm) is fetched alongside as an *independent* cross
check on the bucket — it is never used to fit it.

Access is via the University of Idaho THREDDS **NetcdfSubset (NCSS)** service, which does
the spatial + temporal subsetting server-side and returns a small NetCDF window — no
OPeNDAP client, no full-CONUS download. This mirrors the "public source, range-read a
window" pattern already used by ``src.data.fetch_public`` for SOLUS100.

Usage:
  # Puget Sound pilot (default bbox), 2000→present:
  python -m src.data.fetch_terraclimate --output data/processed/terraclimate_monthly_puget.zarr
  python -m src.data.fetch_terraclimate --bbox -124.9 45.5 -116.5 49.1 \
      --start 2000-01-01 --end 2024-12-01 --vars ppt pet soil
"""

from __future__ import annotations

import argparse
import logging
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Puget Sound lowland pilot (WGS84), matching the 90 m EPSG:5070 terrain/GWL grid extent.
PUGET_BBOX_WGS84 = (-122.95, 47.05, -121.55, 48.15)

# THREDDS NetcdfSubset endpoint for the aggregated (1950→present) monthly TerraClimate grids.
_NCSS_BASE = "http://thredds.northwestknowledge.net:8080/thredds/ncss/grid"
_DATASET = "agg_terraclimate_{var}_1950_CurrentYear_GLOBE.nc"

# TerraClimate NCSS variable short-names and their physical meaning / units.
_VAR_META = {
    "ppt": ("precip_mm", "mm/month", "Monthly total precipitation"),
    "pet": ("pet_mm", "mm/month", "Reference (potential) evapotranspiration"),
    "soil": ("tc_soil_mm", "mm", "TerraClimate column soil-water storage (cross-check only)"),
    "aet": ("aet_mm", "mm/month", "Actual evapotranspiration"),
    "def": ("deficit_mm", "mm/month", "Climatic water deficit"),
    "swe": ("swe_mm", "mm", "Snow water equivalent"),
    "q": ("runoff_mm", "mm/month", "Runoff"),
}


def _fetch_var(
    var: str, bbox: tuple[float, float, float, float], start: str, end: str
) -> xr.DataArray:
    """Fetch one TerraClimate variable over ``bbox``/[start, end] via NCSS → DataArray."""
    import requests

    west, south, east, north = bbox
    dataset = _DATASET.format(var=var)
    params = {
        "var": var,
        "north": north,
        "south": south,
        "west": west,
        "east": east,
        "time_start": f"{start}T00:00:00Z",
        "time_end": f"{end}T00:00:00Z",
        "accept": "netcdf",
    }
    url = f"{_NCSS_BASE}/{dataset}"
    logger.info("NCSS request: %s var=%s bbox=%s %s..%s", dataset, var, bbox, start, end)
    resp = requests.get(url, params=params, timeout=180, stream=True)
    resp.raise_for_status()

    with tempfile.NamedTemporaryFile(suffix=".nc", delete=True) as tmp:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            tmp.write(chunk)
        tmp.flush()
        ds = xr.open_dataset(tmp.name)
        da = ds[var].load()  # read fully before the temp file closes

    if da.size == 0:
        raise RuntimeError(f"NCSS returned an empty grid for var={var} (check bbox/dates).")

    out_name, units, long_name = _VAR_META.get(var, (var, "", var))
    da = da.rename(out_name)
    da.attrs = {"units": units, "long_name": long_name, "source": "TerraClimate v1.1 (NCSS)"}
    return da


def fetch_terraclimate(
    bbox: tuple[float, float, float, float],
    start: str,
    end: str,
    variables: list[str],
    output: Path,
) -> Path:
    """Fetch the requested TerraClimate variables → a single monthly Zarr store."""
    arrays = [_fetch_var(v, bbox, start, end) for v in variables]
    ds = xr.merge(arrays)

    # Normalise the time axis to month-start timestamps for clean joins downstream.
    ds = ds.assign_coords(time=pd.DatetimeIndex(ds["time"].values).to_period("M").to_timestamp())
    ds.attrs.update(
        source="TerraClimate v1.1 (Abatzoglou et al. 2018), Univ. of Idaho THREDDS NCSS",
        native_resolution="1/24 degree (~4 km)",
        role="dynamic driver for gaia-soil-hydromechanics soil-moisture state",
        bbox_wgs84=str(bbox),
    )

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        import shutil

        shutil.rmtree(output)
    ds.to_zarr(output, mode="w", consolidated=True)
    logger.info(
        "Wrote %s — vars=%s time=%s..%s (%d months) grid=%s",
        output,
        list(ds.data_vars),
        str(ds.time.values[0])[:7],
        str(ds.time.values[-1])[:7],
        ds.time.size,
        dict(ds.sizes),
    )
    return output


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"), default=PUGET_BBOX_WGS84,
        help="WGS84 bounding box (default: Puget Sound pilot).",
    )
    p.add_argument("--start", default="2000-01-01", help="Start date (YYYY-MM-DD).")
    p.add_argument("--end", default="2024-12-01", help="End date (YYYY-MM-DD); NCSS clips to available.")
    p.add_argument(
        "--vars", nargs="+", default=["ppt", "pet", "soil"],
        help="TerraClimate variables to fetch (ppt pet soil [aet def swe q]).",
    )
    p.add_argument(
        "--output", type=Path, default=Path("data/processed/terraclimate_monthly_puget.zarr"),
    )
    args = p.parse_args()

    fetch_terraclimate(tuple(args.bbox), args.start, args.end, args.vars, args.output)


if __name__ == "__main__":
    main()
