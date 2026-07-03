"""Fetch MERRA-2 monthly soil moisture over the pilot → monthly θ, with a LOCAL cache.

MERRA-2 (NASA GMAO reanalysis, 1980→present) provides monthly land-surface soil moisture at
0.5°×0.625°. Its **root-zone** field ``RZMC`` (m³/m³, ~0–1 m) is depth-matched to our root-zone
bucket — a better comparison than SMAP's 0–5 cm surface — and, unlike SMAP's ~650 MB global
granules, each MERRA-2 month is one file we lazily subset. It is a model *reanalysis* (an
independent cross-check, not a satellite retrieval), and it covers 2025.

**Local caching (so we never waste compute):** each month's small pilot subset (RZMC + surface
SFMC) is written to ``data/raw/merra2/`` and reused; re-runs only fetch missing months, and the
monthly product can be re-aggregated from the cache without any network access.

Access: NASA GES DISC via ``earthaccess`` (needs ~/.netrc + GES DISC app authorised).

Usage:
  python -m src.data.fetch_merra2 --start 2024-01 --end 2025-12 \
      --output data/processed/merra2_soil_moisture_monthly_puget.zarr
"""

from __future__ import annotations

import argparse
import logging
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PUGET_BBOX_WGS84 = (-122.95, 47.05, -121.55, 48.15)
_VARS = ("RZMC", "SFMC")            # root-zone (depth-matched) + surface soil moisture (m³/m³)


def _month_of(granule) -> str | None:
    m = re.search(r"\.(\d{6})\.nc4?", str(granule["umm"]["GranuleUR"]))
    return m.group(1) if m else None


def _cache_month(granule, bbox, cache: Path) -> Path:
    """Lazily subset one MERRA-2 month to the pilot bbox and cache it locally (RZMC + SFMC)."""
    import earthaccess

    if cache.exists():
        return cache
    w, s, e, n = bbox
    ds = xr.open_dataset(earthaccess.open([granule])[0], engine="h5netcdf")
    sub = ds[list(_VARS)].sel(lat=slice(s, n), lon=slice(w, e)).load()
    ds.close()
    sub.to_netcdf(cache)
    return cache


def fetch_merra2_monthly(bbox, start, end, output: Path, raw_dir: Path) -> Path:
    import earthaccess

    for noisy in ("fsspec", "earthaccess", "h5netcdf", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    earthaccess.login(strategy="netrc")
    raw_dir.mkdir(parents=True, exist_ok=True)

    granules = earthaccess.search_data(short_name="M2TMNXLND",
                                       temporal=(f"{start}-01", f"{end}-28"), bounding_box=bbox)
    by_month = {}
    for g in granules:
        ym = _month_of(g)
        if ym and start.replace("-", "") <= ym <= end.replace("-", ""):
            by_month.setdefault(ym, g)
    logger.info("MERRA-2 M2TMNXLND months found: %d (%s..%s)", len(by_month),
                min(by_month) if by_month else "-", max(by_month) if by_month else "-")

    frames, times = [], []
    for ym in sorted(by_month):
        cache = raw_dir / f"merra2_{ym}.nc"
        try:
            _cache_month(by_month[ym], bbox, cache)
            sub = xr.open_dataset(cache)
        except Exception as exc:
            logger.warning("  skip %s (%s)", ym, str(exc)[:80]); continue
        frames.append(sub); times.append(pd.Timestamp(f"{ym[:4]}-{ym[4:]}-01"))
        logger.info("  %s: RZMC mean=%.3f  SFMC mean=%.3f  (%s cells)", ym,
                    float(sub["RZMC"].mean()), float(sub["SFMC"].mean()),
                    "x".join(map(str, sub["RZMC"].squeeze().shape)))

    if not frames:
        raise SystemExit("no MERRA-2 data retrieved.")
    lat = frames[0]["lat"].values; lon = frames[0]["lon"].values
    ds = xr.Dataset(
        {"theta_rz": (("time", "lat", "lon"), np.stack([f["RZMC"].squeeze(("time",), drop=True).values
                                                        if "time" in f["RZMC"].dims else f["RZMC"].values for f in frames])),
         "theta_sfc": (("time", "lat", "lon"), np.stack([f["SFMC"].squeeze(("time",), drop=True).values
                                                         if "time" in f["SFMC"].dims else f["SFMC"].values for f in frames]))},
        coords={"time": pd.DatetimeIndex(times), "lat": lat, "lon": lon},
    )
    ds["theta_rz"].attrs = {"units": "m3/m3", "long_name": "MERRA-2 root-zone soil moisture (~0–1 m)"}
    ds["theta_sfc"].attrs = {"units": "m3/m3", "long_name": "MERRA-2 surface soil moisture (0–5 cm)"}
    ds.attrs.update(source="MERRA-2 M2TMNXLND (NASA GMAO reanalysis)", native_resolution="0.5deg x 0.625deg",
                    role="independent reanalysis cross-check (root-zone depth-matched)", crs="EPSG:4326")

    output = Path(output)
    if output.exists():
        import shutil
        shutil.rmtree(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(output, mode="w", consolidated=True)
    logger.info("Wrote %s — %d months %s..%s (cache: %s)", output, ds.time.size,
                str(ds.time.values[0])[:7], str(ds.time.values[-1])[:7], raw_dir)
    return output


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"), default=PUGET_BBOX_WGS84)
    p.add_argument("--start", default="2024-01")
    p.add_argument("--end", default="2025-12")
    p.add_argument("--output", type=Path, default=Path("data/processed/merra2_soil_moisture_monthly_puget.zarr"))
    p.add_argument("--raw-dir", type=Path, default=Path("data/raw/merra2"))
    args = p.parse_args()
    fetch_merra2_monthly(tuple(args.bbox), args.start, args.end, args.output, args.raw_dir)


if __name__ == "__main__":
    main()
