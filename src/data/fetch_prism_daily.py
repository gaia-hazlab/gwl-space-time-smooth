"""PRISM **daily** precipitation + temperature, from the GAIA prism-stac catalog.

Mirrors ``gaia-hazlab/gaia-cli`` (``src/gaia_cli/prism.py``): the same STAC catalog, read with
``odc.stac``, staged to Zarr. Two differences:

  - gaia-cli loads only ``ppt``; the catalog also carries ``tmean``, which we need for the degree-day
    snow partition (a Cascade December is snow-dominated -- treating snowfall as rain would fabricate
    an immediate soil-moisture and Vs response that physically waits for melt).
  - we add Hargreaves-Samani PET **per day** (``fetch_prism_monthly.hargreaves_samani_pet_mm`` only
    returns monthly totals) from tmax/tmin/tmean fetched straight from the PRISM service (the STAC
    catalog only carries ppt/tmean) -- FAO-56's own recommended substitute for full Penman-Monteith
    reference ET when radiation/wind/humidity aren't measured -- which PRISM does not carry.

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
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from src.io.zarr_store import write_zarr

logger = logging.getLogger("fetch_prism_daily")

PRISM_STAC = ("https://raw.githubusercontent.com/gaia-hazlab/prism-stac/"
              "refs/heads/main/stac/catalog.json")
# Domain is defined ONCE in src.config.domain (issue #92). Do not re-declare a bbox here.
from src.config.domain import PUGET_CASCADES_BBOX  # noqa: E402

def hargreaves_samani_pet_per_day_mm(tmax_c, tmin_c, tmean_c, times, lat):
    """Hargreaves-Samani (1985) PET in **mm/day**, FAO-56 Eq. 52 (see fetch_prism_monthly for the
    monthly-total form and the rationale for using this rather than Hamon)."""
    from src.data.fetch_prism_monthly import extraterrestrial_radiation_mm

    tmax = np.asarray(tmax_c, dtype="float64")                 # (time, lat, lon)
    tmin = np.asarray(tmin_c, dtype="float64")
    tmean = np.asarray(tmean_c, dtype="float64")
    latg = np.broadcast_to(np.asarray(lat)[None, :, None], tmean.shape)
    doy = np.array([t.dayofyear for t in pd.DatetimeIndex(times)], dtype="float64")[:, None, None]

    ra_mm = extraterrestrial_radiation_mm(doy, latg)
    dtr = np.clip(tmax - tmin, 0.0, None)
    pet = 0.0023 * (tmean + 17.8) * np.sqrt(dtr) * ra_mm
    return np.clip(pet, 0.0, None).astype("float32")


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
    logger.info("fetching %d days of PRISM daily (ppt + tmax/tmin/tmean) from the PRISM service", len(days))
    ppt, tmn, tmx, tmi = [], [], [], []
    for i, d in enumerate(days):
        ppt.append(_fetch_prism_day("ppt", d, res, bbox, raw_dir))
        tmn.append(_fetch_prism_day("tmean", d, res, bbox, raw_dir))
        tmx.append(_fetch_prism_day("tmax", d, res, bbox, raw_dir))
        tmi.append(_fetch_prism_day("tmin", d, res, bbox, raw_dir))
        if (i + 1) % 30 == 0:
            logger.info("  %d/%d days", i + 1, len(days))
    ds = xr.Dataset({
        "precip_mm": xr.concat(ppt, dim=pd.Index(days, name="time")),
        "tmean_c": xr.concat(tmn, dim=pd.Index(days, name="time")),
        "tmax_c": xr.concat(tmx, dim=pd.Index(days, name="time")),
        "tmin_c": xr.concat(tmi, dim=pd.Index(days, name="time")),
    })
    return ds.rename({"x": "x", "y": "y"})


def open_prism_daily(start, end, bbox=PUGET_CASCADES_BBOX, catalog_url=PRISM_STAC, source="auto"):
    """Daily PRISM precip + tmean + Hargreaves-Samani PET, clipped to ``bbox``. Returns an xarray Dataset.

    ``source='auto'`` uses the gaia prism-stac catalog when it covers the window (it currently holds
    only 2025-12-01..12-31) and otherwise falls back to the PRISM service, which covers any window.
    The STAC catalog only carries ppt/tmean, so tmax/tmin (needed for Hargreaves-Samani PET) are
    always fetched from the PRISM service directly, regardless of which source supplied the rest.
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

    if "tmax_c" not in ds or "tmin_c" not in ds:
        days = pd.DatetimeIndex(ds["time"].values)
        raw_dir = Path("data/raw/prism_daily")
        tmx = xr.concat([_fetch_prism_day("tmax", d, "4km", bbox, raw_dir) for d in days],
                       dim=pd.Index(days, name="time"))
        tmi = xr.concat([_fetch_prism_day("tmin", d, "4km", bbox, raw_dir) for d in days],
                       dim=pd.Index(days, name="time"))
        ds["tmax_c"] = tmx.where(tmx > -9000)
        ds["tmin_c"] = tmi.where(tmi > -9000)

    lat = ds["y"].values
    pet = hargreaves_samani_pet_per_day_mm(ds["tmax_c"].values, ds["tmin_c"].values,
                                           ds["tmean_c"].values, ds["time"].values, lat)
    ds["pet_mm"] = (ds["tmean_c"].dims, pet)

    ds["precip_mm"].attrs.update(units="mm/day", long_name="PRISM daily precipitation")
    ds["tmean_c"].attrs.update(units="degC", long_name="PRISM daily mean temperature")
    ds["pet_mm"].attrs.update(units="mm/day",
                              long_name="Hargreaves-Samani (1985) reference ET (FAO-56 Eq. 52)")
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
