"""PRISM **daily** precipitation + temperature, from the GAIA prism-stac catalog.

Mirrors ``gaia-hazlab/gaia-cli`` (``src/gaia_cli/prism.py``): the same STAC catalog, read with
``odc.stac``, staged to Zarr. Two differences:

  - gaia-cli loads only ``ppt``; the catalog also carries ``tmean``, which we need for the degree-day
    snow partition (a Cascade December is snow-dominated -- treating snowfall as rain would fabricate
    an immediate soil-moisture and Vs response that physically waits for melt).
  - we add Hamon PET **per day** (``fetch_prism_monthly.hamon_pet_mm`` only returns monthly totals).

This is the *observed* daily forcing, so it gives us two things the AI forecast cannot yet:
a **hindcast** (drive the soil state with what actually fell -- a perfect-forcing baseline that
isolates the physics from the weather-forecast error), and later the **verification truth** to score
FuXi's precipitation against.

    python -m src.data.fetch_prism_daily --start 2025-12-01 --end 2025-12-31 \
        --out data/processed/prism_daily_puget.zarr
"""

from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd
import xarray as xr

from src.io.zarr_store import write_zarr

logger = logging.getLogger("fetch_prism_daily")

PRISM_STAC = ("https://raw.githubusercontent.com/gaia-hazlab/prism-stac/"
              "refs/heads/main/stac/catalog.json")
# Domain is defined ONCE in src.config.domain (issue #92). Do not re-declare a bbox here.
from src.config.domain import PUGET_CASCADES_BBOX  # noqa: E402

def hamon_pet_per_day_mm(tmean_c, times, lat):
    """Hamon (1961) PET in **mm/day** (the same formula as fetch_prism_monthly, without x days)."""
    T = np.asarray(tmean_c, dtype="float64")                   # (time, lat, lon)
    latg = np.broadcast_to(np.asarray(lat)[None, :, None], T.shape)
    doy = np.array([t.dayofyear for t in pd.DatetimeIndex(times)], dtype="float64")

    phi = np.radians(latg)
    decl = 0.409 * np.sin(2 * np.pi * doy[:, None, None] / 365.0 - 1.39)
    x = np.clip(-np.tan(phi) * np.tan(decl), -1.0, 1.0)
    N = 24.0 / np.pi * np.arccos(x)                            # daylight hours

    es = 6.108 * np.exp(17.27 * T / (T + 237.3))               # hPa (Tetens)
    rho_sat = 216.7 * es / (T + 273.3)                         # g/m^3
    pet = 0.1651 * (N / 12.0) * rho_sat * 1.2
    return np.clip(np.where(T > 0.0, pet, 0.0), 0.0, None).astype("float32")   # no PET below freezing


PRISM_SERVICE = "https://services.nacse.org/prism/data/get/us/{res}/{elem}/{yyyymmdd}"


def _fetch_prism_day(elem, day, res, bbox, raw_dir):
    """One daily PRISM grid straight from the PRISM service (same endpoint fetch_prism_monthly uses,
    which also accepts yyyymmdd). Cached, since the service is rate-limited by courtesy."""
    import io
    import zipfile

    import requests
    import rioxarray

    raw_dir.mkdir(parents=True, exist_ok=True)
    ymd = day.strftime("%Y%m%d")
    cache = raw_dir / f"prism_{elem}_{ymd}_{res}.tif"
    if not cache.exists():
        r = requests.get(PRISM_SERVICE.format(res=res, elem=elem, yyyymmdd=ymd), timeout=120)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            name = next(n for n in zf.namelist() if n.endswith((".bil", ".tif")))
            zf.extractall(raw_dir)
            (raw_dir / name).rename(cache) if name.endswith(".tif") else None
            if not cache.exists():                          # .bil -> read and re-save as tif
                da = rioxarray.open_rasterio(raw_dir / name, masked=True).squeeze("band", drop=True)
                da.rio.to_raster(cache)
    da = rioxarray.open_rasterio(cache, masked=True).squeeze("band", drop=True)
    return da.rio.clip_box(*bbox)


def open_prism_daily_service(start, end, bbox=PUGET_CASCADES_BBOX, res="4km",
                             raw_dir=None):
    """Daily PRISM direct from the PRISM service — covers ANY window, unlike the STAC catalog."""
    from pathlib import Path as _P

    raw_dir = _P(raw_dir or "data/raw/prism_daily")
    days = pd.date_range(start, end, freq="D")
    logger.info("fetching %d days of PRISM daily (ppt + tmean) from the PRISM service", len(days))
    ppt, tmn = [], []
    for i, d in enumerate(days):
        ppt.append(_fetch_prism_day("ppt", d, res, bbox, raw_dir))
        tmn.append(_fetch_prism_day("tmean", d, res, bbox, raw_dir))
        if (i + 1) % 30 == 0:
            logger.info("  %d/%d days", i + 1, len(days))
    ds = xr.Dataset({
        "precip_mm": xr.concat(ppt, dim=pd.Index(days, name="time")),
        "tmean_c": xr.concat(tmn, dim=pd.Index(days, name="time")),
    })
    return ds.rename({"x": "x", "y": "y"})


def open_prism_daily(start, end, bbox=PUGET_CASCADES_BBOX, catalog_url=PRISM_STAC, source="auto"):
    """Daily PRISM precip + tmean + Hamon PET, clipped to ``bbox``. Returns an xarray Dataset.

    ``source='auto'`` uses the gaia prism-stac catalog when it covers the window (it currently holds
    only 2025-12-01..12-31) and otherwise falls back to the PRISM service, which covers any window.
    """
    import odc.stac
    import pystac

    ds = None
    if source in ("auto", "stac"):
        odc.stac.configure_rio(cloud_defaults=True)
        cat = pystac.Catalog.from_file(catalog_url)
        items = [i for i in cat.get_all_items()
                 if i.datetime and start <= i.datetime.strftime("%Y-%m-%d") <= end]
        covers = len(items) >= len(pd.date_range(start, end, freq="D"))
        if items and (covers or source == "stac"):
            w, s, e, n = bbox
            ds = odc.stac.load(items, bands=["ppt", "tmean"], bbox=[w, s, e, n], chunks={})
            ds = ds.rename({"ppt": "precip_mm", "tmean": "tmean_c"})
        elif source == "auto":
            logger.info("prism-stac covers only part of %s..%s; using the PRISM service instead",
                        start, end)
    if ds is None:
        ds = open_prism_daily_service(start, end, bbox)

    # PRISM nodata is -9999; make it NaN so it cannot be summed as rainfall
    ds = ds.where(ds.precip_mm > -9000).where(ds.tmean_c > -9000)
    ds = ds.sortby("time").load()

    lat = ds["y"].values
    pet = hamon_pet_per_day_mm(ds["tmean_c"].values, ds["time"].values, lat)
    ds["pet_mm"] = (ds["tmean_c"].dims, pet)

    ds["precip_mm"].attrs.update(units="mm/day", long_name="PRISM daily precipitation")
    ds["tmean_c"].attrs.update(units="degC", long_name="PRISM daily mean temperature")
    ds["pet_mm"].attrs.update(units="mm/day", long_name="Hamon (1961) potential ET")
    ds.attrs.update(source="PRISM daily via gaia-hazlab/prism-stac", dt_days=1.0,
                    role="OBSERVED forcing -- hindcast / verification truth, not a forecast",
                    catalog=catalog_url)
    return ds


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Stage PRISM daily precip/tmean/PET as Zarr.")
    p.add_argument("--start", default="2025-12-01")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--bbox", type=float, nargs=4, default=PUGET_CASCADES_BBOX)
    p.add_argument("--out", default="data/processed/prism_daily_puget.zarr",
                   help="Local .zarr or s3://gaia/soil-twin/forcing/... on Kopah.")
    a = p.parse_args()

    ds = open_prism_daily(a.start, a.end, tuple(a.bbox))
    tot = float(ds["precip_mm"].mean(dim=[d for d in ds["precip_mm"].dims if d != "time"]).sum())
    logger.info("PRISM daily %s..%s: %d days, grid %s, %.0f mm total (area mean)",
                a.start, a.end, ds.sizes["time"], tuple(ds.sizes[d] for d in ("y", "x")), tot)
    write_zarr(ds, a.out)


if __name__ == "__main__":
    main()
