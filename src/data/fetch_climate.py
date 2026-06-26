"""Fetch climate indices needed for GWL response functions.

Sub-commands:
  pdo   — Pacific Decadal Oscillation monthly index (NOAA PSL)
  swe   — SNODAS monthly mean SWE (NSIDC G02158)
  spi3  — 3-month SPI derived from PRISM monthly precipitation

Usage:
  python -m src.data.fetch_climate pdo --output-dir data/raw/climate
  python -m src.data.fetch_climate swe --bbox -124.9 42.0 -116.5 49.0 --output-dir data/raw/climate
  python -m src.data.fetch_climate spi3 --prism data/processed/prism_monthly_pnw.zarr \
      --output-dir data/processed
"""

from __future__ import annotations

import argparse
import io
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

logger = logging.getLogger(__name__)

PNW_BBOX_WGS84 = (-124.9, 42.0, -116.5, 49.0)

# NOAA PSL PDO index — plain-text monthly table
_PDO_URL = "https://psl.noaa.gov/data/timeseries/monthly/PDO/pdomon.data"

# NSIDC SNODAS — daily SWE HTTPS access
_SNODAS_BASE = "https://noaadata.apps.nsidc.org/NOAA/G02158/masked/"


# ---------------------------------------------------------------------------
# PDO index
# ---------------------------------------------------------------------------

def fetch_pdo(output_dir: Path) -> Path:
    """Download NOAA PSL PDO monthly index and write as CSV.

    The PSL file is a fixed-width table: year | Jan Feb ... Dec | annual.
    Missing values are encoded as -9999.00 or -99.90.

    Parameters
    ----------
    output_dir:
        Output directory. Writes pdo_monthly.csv with columns [year, month, pdo].

    Returns
    -------
    Path
        Path to the written CSV.
    """
    import requests

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "pdo_monthly.csv"

    logger.info("Downloading PDO index from %s", _PDO_URL)
    resp = requests.get(_PDO_URL, timeout=30)
    resp.raise_for_status()

    rows = []
    for line in resp.text.splitlines():
        parts = line.split()
        if not parts or not parts[0].isdigit():
            continue
        year = int(parts[0])
        monthly = parts[1:13]  # 12 monthly values; ignore annual
        if len(monthly) < 12:
            continue
        for month_idx, val_str in enumerate(monthly, start=1):
            try:
                val = float(val_str)
            except ValueError:
                continue
            if val < -90:  # missing
                val = np.nan
            rows.append({"year": year, "month": month_idx, "pdo": val})

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(
        df[["year", "month"]].assign(day=1)
    )
    df = df[["time", "pdo"]].sort_values("time").reset_index(drop=True)
    df.to_csv(out_path, index=False)
    logger.info("PDO index written: %s  (%d records)", out_path, len(df))
    return out_path


# ---------------------------------------------------------------------------
# SNODAS SWE
# ---------------------------------------------------------------------------

def fetch_snodas_swe(
    bbox_wgs84: tuple[float, float, float, float],
    output_dir: Path,
    start: str = "2003-10-01",
    end: str | None = None,
) -> Path:
    """Download SNODAS daily SWE, compute monthly means, clip to bbox, write Zarr.

    SNODAS is available from 2003-10-01. The masked (filled) version is used.
    Daily files are in NSIDC HTTPS; we download, parse, compute monthly means,
    and write a Zarr store (time, y, x) on the native SNODAS 1 km grid clipped
    to the PNW bbox.

    Parameters
    ----------
    bbox_wgs84:
        (west, south, east, north).
    output_dir:
        Output directory.
    start:
        ISO start date (earliest available: 2003-10-01).
    end:
        ISO end date (defaults to last complete month).

    Returns
    -------
    Path
        Path to written Zarr store.
    """
    import requests
    import struct
    import gzip
    import tarfile

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "snodas_swe_monthly_pnw.zarr"

    if end is None:
        end = (pd.Timestamp.today() - pd.DateOffset(months=1)).strftime("%Y-%m-01")

    months = pd.date_range(start=start, end=end, freq="MS")
    logger.info(
        "Fetching SNODAS SWE for %d months (%s → %s)", len(months), start, end
    )

    # SNODAS masked SWE grid parameters (conus masked product)
    # Native: ~1 km, EPSG:4326-like (geographic), llcorner = (-124.733_333, 24.9499_583)
    SNODAS_NCOLS = 6935
    SNODAS_NROWS = 3351
    SNODAS_CELLSIZE = 0.00833333  # degrees
    SNODAS_XLLCORNER = -124.73333333
    SNODAS_YLLCORNER = 24.94999583
    SNODAS_SCALE = 1e-3  # values are in mm × 10^-3 → mm when multiplied
    SNODAS_NODATA = -9999

    # Clip indices for PNW bbox
    west, south, east, north = bbox_wgs84
    col_start = max(0, int((west - SNODAS_XLLCORNER) / SNODAS_CELLSIZE))
    col_end = min(SNODAS_NCOLS, int((east - SNODAS_XLLCORNER) / SNODAS_CELLSIZE) + 1)
    row_start = max(0, int(
        SNODAS_NROWS - (north - SNODAS_YLLCORNER) / SNODAS_CELLSIZE
    ))
    row_end = min(SNODAS_NROWS, int(
        SNODAS_NROWS - (south - SNODAS_YLLCORNER) / SNODAS_CELLSIZE
    ) + 1)

    lons = (
        SNODAS_XLLCORNER
        + (np.arange(col_start, col_end) + 0.5) * SNODAS_CELLSIZE
    )
    lats = (
        SNODAS_YLLCORNER
        + (SNODAS_NROWS - np.arange(row_start, row_end) - 0.5) * SNODAS_CELLSIZE
    )

    monthly_swe = []
    monthly_times = []

    for month_start in months:
        yr = month_start.year
        mo = month_start.month
        days_in_month = pd.Period(f"{yr}-{mo:02d}").days_in_month
        day_arrays = []

        for day in range(1, days_in_month + 1):
            date_str = f"{yr}{mo:02d}{day:02d}"
            yr_str = f"{yr}"
            # NSIDC directory structure: .../YYYY/MM_Mon/
            mon_abbr = month_start.strftime("%b")
            url = (
                f"{_SNODAS_BASE}{yr_str}/{mo:02d}_{mon_abbr}/"
                f"SNODAS_{date_str}.tar"
            )
            try:
                resp = requests.get(url, timeout=60, stream=True)
                resp.raise_for_status()
            except Exception:
                continue

            # Extract SWE .dat.gz from the tar
            try:
                with tarfile.open(fileobj=io.BytesIO(resp.content)) as tar:
                    swe_name = next(
                        (m.name for m in tar.getmembers()
                         if "us_ssmv11034tS__T0001TTNATS" in m.name and m.name.endswith(".dat.gz")),
                        None,
                    )
                    if swe_name is None:
                        continue
                    raw_gz = tar.extractfile(swe_name).read()
                raw_bytes = gzip.decompress(raw_gz)
                arr = np.frombuffer(raw_bytes, dtype=">i2").reshape(
                    SNODAS_NROWS, SNODAS_NCOLS
                ).astype(np.float32)
                arr[arr == SNODAS_NODATA] = np.nan
                arr_mm = arr  # values already in mm (SNODAS scale factor = 1 mm)
                day_arrays.append(arr_mm[row_start:row_end, col_start:col_end])
            except Exception as exc:
                logger.debug("Failed parsing SNODAS %s: %s", date_str, exc)

        if day_arrays:
            monthly_mean = np.nanmean(np.stack(day_arrays, axis=0), axis=0)
        else:
            monthly_mean = np.full(
                (row_end - row_start, col_end - col_start), np.nan, dtype=np.float32
            )

        monthly_swe.append(monthly_mean)
        monthly_times.append(month_start)
        logger.info("  %s: %d days averaged", month_start.strftime("%Y-%m"), len(day_arrays))

    if not monthly_swe:
        raise RuntimeError("No SNODAS data could be downloaded.")

    swe_arr = np.stack(monthly_swe, axis=0)  # (time, lat, lon)
    ds = xr.Dataset(
        {"swe_mm": (["time", "lat", "lon"], swe_arr)},
        coords={
            "time": pd.DatetimeIndex(monthly_times),
            "lat": lats,
            "lon": lons,
        },
        attrs={
            "long_name": "SNODAS monthly mean snow water equivalent",
            "units": "mm",
            "source": "NSIDC SNODAS G02158 masked product",
        },
    )
    ds.to_zarr(out_path, mode="w", consolidated=True)
    logger.info("SNODAS SWE written: %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# SPI-3
# ---------------------------------------------------------------------------

def compute_spi3(prism_zarr: Path, output_dir: Path) -> Path:
    """Derive 3-month Standardized Precipitation Index from PRISM monthly ppt.

    Method:
      1. Compute 3-month rolling sum of precipitation.
      2. For each grid cell and each calendar month, fit empirical CDF.
      3. Transform to standard normal via scipy.stats.norm.ppf.

    Parameters
    ----------
    prism_zarr:
        Path to PRISM monthly precipitation Zarr (variable: "ppt", dims: time, y, x).
    output_dir:
        Output directory.

    Returns
    -------
    Path
        Path to SPI-3 Zarr store.
    """
    from scipy import stats
    from sklearn.preprocessing import QuantileTransformer

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "spi3_monthly_pnw.zarr"

    logger.info("Loading PRISM precipitation from %s", prism_zarr)
    ds = xr.open_zarr(prism_zarr, consolidated=True)
    ppt_var = "ppt" if "ppt" in ds else list(ds.data_vars)[0]
    ppt = ds[ppt_var].load()  # (time, y, x)

    logger.info("Computing 3-month rolling sum...")
    ppt3 = ppt.rolling(time=3, min_periods=3).sum()

    logger.info("Standardising per calendar month (this may take a few minutes)...")
    spi3_vals = np.full_like(ppt3.values, np.nan, dtype=np.float32)
    times = ppt3["time"].values
    months = pd.DatetimeIndex(times).month

    for cal_month in range(1, 13):
        idx = np.where(months == cal_month)[0]
        if len(idx) < 10:
            continue
        subset = ppt3.values[idx]  # (n_months, ny, nx)
        ny, nx = subset.shape[1], subset.shape[2]
        flat = subset.reshape(len(idx), -1)  # (n_months, n_cells)
        spi_flat = np.full_like(flat, np.nan)

        for cell in range(flat.shape[1]):
            vals = flat[:, cell]
            valid = ~np.isnan(vals)
            if valid.sum() < 10:
                continue
            qt = QuantileTransformer(
                n_quantiles=min(500, valid.sum()),
                output_distribution="normal",
                random_state=0,
            )
            qt.fit(vals[valid].reshape(-1, 1))
            spi_flat[valid, cell] = qt.transform(vals[valid].reshape(-1, 1)).ravel()

        spi3_vals[idx] = spi_flat.reshape(len(idx), ny, nx)
        logger.info("  Calendar month %02d complete.", cal_month)

    spi3_da = xr.DataArray(
        spi3_vals,
        coords=ppt3.coords,
        dims=ppt3.dims,
        attrs={
            "long_name": "3-month Standardized Precipitation Index",
            "units": "1",
            "standard_name": "standardized_precipitation_index",
            "comment": "Derived from PRISM monthly ppt; standardized per calendar month via QuantileTransformer",
        },
    )
    spi3_ds = xr.Dataset({"spi3": spi3_da})
    spi3_ds.to_zarr(out_path, mode="w", consolidated=True)
    logger.info("SPI-3 written: %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch climate indices for GWL response functions.")
    sub = parser.add_subparsers(dest="command", required=True)

    # pdo
    p_pdo = sub.add_parser("pdo", help="Download PDO monthly index")
    p_pdo.add_argument("--output-dir", type=Path, default=Path("data/raw/climate"))

    # swe
    p_swe = sub.add_parser("swe", help="Download SNODAS monthly SWE")
    p_swe.add_argument("--bbox", nargs=4, type=float,
                       metavar=("WEST", "SOUTH", "EAST", "NORTH"),
                       default=list(PNW_BBOX_WGS84))
    p_swe.add_argument("--output-dir", type=Path, default=Path("data/raw/climate"))
    p_swe.add_argument("--start", default="2003-10-01")
    p_swe.add_argument("--end", default=None)

    # spi3
    p_spi3 = sub.add_parser("spi3", help="Compute SPI-3 from PRISM monthly ppt")
    p_spi3.add_argument(
        "--prism",
        type=Path,
        default=Path("data/processed/prism_monthly_pnw.zarr"),
        help="PRISM monthly precipitation Zarr",
    )
    p_spi3.add_argument("--output-dir", type=Path, default=Path("data/processed"))

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.command == "pdo":
        fetch_pdo(args.output_dir)
    elif args.command == "swe":
        fetch_snodas_swe(tuple(args.bbox), args.output_dir, start=args.start, end=args.end)
    elif args.command == "spi3":
        compute_spi3(args.prism, args.output_dir)


if __name__ == "__main__":
    main()
