"""Fetch monthly PRISM precipitation + temperature (alternative soil-moisture forcing).

PRISM (Daly et al., Oregon State) is a station-interpolated, observation-based monthly
climate product for the CONUS at ~4 km (and 800 m). It is an alternative **dynamic forcing**
for the gaia-soil-hydromechanics soil-moisture bucket, complementing TerraClimate:

  * PRISM precipitation is observation-based (station-anchored), not a reanalysis, and is
    available at higher native resolution — a more independent forcing.
  * PRISM ships temperature but **no reference ET**, so PET is derived here from monthly
    tmax/tmin/tmean via the Hargreaves–Samani (1985) equation — keeping the forcing fully
    observation-driven. This is FAO-56's own recommended substitute for full Penman-Monteith
    reference ET when radiation, wind, and humidity are not measured (Allen et al. 1998, FAO
    Irrigation and Drainage Paper 56, Ch. 3) — the formulation actually used for reference ET in
    Shi et al. 2026 (agroseismology) is full FAO-56 Penman-Monteith, which additionally needs net
    radiation, soil heat flux, wind speed, and vapor pressure deficit; PRISM does not carry any
    of those, so full Penman-Monteith is not computable from this forcing alone (tracked in #58).
    Hargreaves-Samani needs only Tmax/Tmin/Tmean + latitude, and is the standard, far more widely
    validated choice for that data-limited case than the previously used Hamon (1961) method,
    which needs temperature alone and is comparatively rarely used outside Thornthwaite-family
    monthly water-balance schemes.

Running the same Thornthwaite–Mather bucket under both PRISM and TerraClimate yields a
**forcing ensemble**: the spread across forcings is an explicit *forcing-uncertainty* term for
the soil-moisture budget (bootstrapping / UQ). Because PRISM precipitation is independent of
TerraClimate's, a PRISM-forced estimate also makes the TerraClimate ``soil`` cross-check more
genuinely independent.

Access: the public PRISM web service (services.nacse.org) serves one GeoTIFF per element per
month — same host family already used by ``src.data.fetch_public`` for the ppt normals.

Usage:
  python -m src.data.fetch_prism_monthly --start 2000-01 --end 2023-12 \
      --output data/processed/prism_monthly_puget.zarr
"""

from __future__ import annotations

import argparse
import io
import logging
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import rioxarray  # noqa: F401
import xarray as xr

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PUGET_BBOX_WGS84 = (-122.95, 47.05, -121.55, 48.15)
_PRISM_URL = "https://services.nacse.org/prism/data/get/us/{res}/{elem}/{yyyymm}"


def _fetch_month_element(elem: str, yyyymm: str, res: str, bbox, raw_dir: Path) -> xr.DataArray:
    """Download one PRISM element/month GeoTIFF, clip to bbox → DataArray (lat, lon)."""
    import requests

    cache = raw_dir / f"prism_{elem}_{res}_{yyyymm}.tif"
    if not cache.exists():
        url = _PRISM_URL.format(res=res, elem=elem, yyyymm=yyyymm)
        resp = requests.get(url, timeout=90)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            tif_name = next(n for n in zf.namelist() if n.endswith(".tif") and "aux" not in n)
            cache.write_bytes(zf.read(tif_name))
        time.sleep(0.15)  # courtesy to the PRISM service

    da = rioxarray.open_rasterio(cache, masked=True).squeeze("band", drop=True)
    da = da.rio.clip_box(*bbox)
    return da.rename({"x": "lon", "y": "lat"}) if "x" in da.dims else da


def extraterrestrial_radiation_mm(doy: np.ndarray, lat_deg: np.ndarray) -> np.ndarray:
    r"""Daily extraterrestrial radiation :math:`R_a`, in mm/day equivalent (FAO-56 Eq. 21).

    ``doy`` and ``lat_deg`` broadcast against each other (typically ``doy`` shaped ``(time, 1, 1)``
    and ``lat_deg`` shaped ``(1, lat, 1)``). :math:`R_a` is converted from MJ m\ :sup:`-2` day\
    :sup:`-1` to mm/day via the 0.408 mm/MJ latent-heat-of-vaporisation factor, matching the units
    ``hargreaves_samani_pet_mm`` expects.
    """
    phi = np.radians(lat_deg)
    dr = 1.0 + 0.033 * np.cos(2 * np.pi * doy / 365.0)                       # inverse Earth-Sun distance
    decl = 0.409 * np.sin(2 * np.pi * doy / 365.0 - 1.39)                    # solar declination
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(decl), -1.0, 1.0))          # sunset hour angle
    gsc = 0.0820                                                            # solar constant, MJ m^-2 min^-1
    ra_mj = ((24.0 * 60.0 / np.pi) * gsc * dr
             * (ws * np.sin(phi) * np.sin(decl) + np.cos(phi) * np.cos(decl) * np.sin(ws)))
    return 0.408 * ra_mj                                                    # mm/day


def hargreaves_samani_pet_mm(tmax_c: xr.DataArray, tmin_c: xr.DataArray, tmean_c: xr.DataArray,
                             times: pd.DatetimeIndex, lat: np.ndarray) -> np.ndarray:
    r"""Monthly Hargreaves–Samani (1985) reference ET (mm), FAO-56 Eq. 52.

    :math:`ET_0 = 0.0023\,(T_{mean} + 17.8)\,\sqrt{T_{max} - T_{min}}\;R_a`, with :math:`R_a` the
    extraterrestrial radiation in mm/day equivalent. FAO-56 (Allen et al. 1998, Ch. 3) recommends
    this specific equation as the substitute for full Penman-Monteith reference ET when radiation,
    wind, and humidity are not measured — which is the case for PRISM (temperature + precipitation
    only). Monthly total = per-day :math:`ET_0` (evaluated once at the month's mean Tmax/Tmin/Tmean
    and mid-month day-of-year) times days-in-month. Vectorised over (time, lat, lon).
    """
    tmax = np.asarray(tmax_c.values, dtype="float64")          # (time, lat, lon)
    tmin = np.asarray(tmin_c.values, dtype="float64")
    tmean = np.asarray(tmean_c.values, dtype="float64")
    latg = np.broadcast_to(lat[None, :, None], tmean.shape)    # latitude per cell (deg)
    doy = np.array([t.dayofyear for t in times], dtype="float64")[:, None, None]
    days = np.array([t.days_in_month for t in times], dtype="float64")

    ra_mm = extraterrestrial_radiation_mm(doy, latg)           # latg in degrees; converted inside
    dtr = np.clip(tmax - tmin, 0.0, None)                      # diurnal temperature range, >= 0
    pet_day = 0.0023 * (tmean + 17.8) * np.sqrt(dtr) * ra_mm
    pet_month = np.where(tmean > -273.0, pet_day, 0.0) * days[:, None, None]
    return np.clip(pet_month, 0.0, None).astype("float32")


def fetch_prism_monthly(bbox, start: str, end: str, res: str, output: Path, raw_dir: Path) -> Path:
    months = pd.period_range(start=start, end=end, freq="M")
    ppt_list, tmean_list, tmax_list, tmin_list = [], [], [], []
    for i, m in enumerate(months):
        ym = f"{m.year}{m.month:02d}"
        ppt_list.append(_fetch_month_element("ppt", ym, res, bbox, raw_dir))
        tmean_list.append(_fetch_month_element("tmean", ym, res, bbox, raw_dir))
        tmax_list.append(_fetch_month_element("tmax", ym, res, bbox, raw_dir))
        tmin_list.append(_fetch_month_element("tmin", ym, res, bbox, raw_dir))
        if i % 24 == 0:
            logger.info("PRISM %s (%d/%d)", ym, i + 1, len(months))

    times = pd.DatetimeIndex([m.to_timestamp() for m in months])
    lat = ppt_list[0].lat.values
    lon = ppt_list[0].lon.values
    precip = np.stack([d.values for d in ppt_list], axis=0).astype("float32")
    tmean = np.stack([d.values for d in tmean_list], axis=0).astype("float32")
    tmax = np.stack([d.values for d in tmax_list], axis=0).astype("float32")
    tmin = np.stack([d.values for d in tmin_list], axis=0).astype("float32")

    ds = xr.Dataset(
        {"precip_mm": (("time", "lat", "lon"), precip),
         "tmean_c": (("time", "lat", "lon"), tmean),
         "tmax_c": (("time", "lat", "lon"), tmax),
         "tmin_c": (("time", "lat", "lon"), tmin)},
        coords={"time": times, "lat": lat, "lon": lon},
    )
    ds["pet_mm"] = (("time", "lat", "lon"),
                    hargreaves_samani_pet_mm(ds["tmax_c"], ds["tmin_c"], ds["tmean_c"], times, lat))
    ds["precip_mm"].attrs = {"units": "mm/month", "source": "PRISM (services.nacse.org)"}
    ds["pet_mm"].attrs = {"units": "mm/month",
                          "method": "Hargreaves-Samani (1985), FAO-56 Eq. 52, from PRISM tmax/tmin/tmean"}
    ds.attrs.update(source="PRISM monthly (Daly et al.)", native_resolution=res,
                    role="alternative dynamic forcing for soil moisture (ensemble member)",
                    pet_method="Hargreaves-Samani temperature-radiation (FAO-56 substitute for "
                               "Penman-Monteith when radiation/wind/humidity are not measured)")

    output = Path(output)
    if output.exists():
        import shutil
        shutil.rmtree(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(output, mode="w", consolidated=True)
    logger.info("Wrote %s — %d months %s..%s grid=%s", output, ds.time.size,
                str(times[0])[:7], str(times[-1])[:7], dict(ds.precip_mm.isel(time=0).sizes))
    return output


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"), default=PUGET_BBOX_WGS84)
    p.add_argument("--start", default="2000-01")
    p.add_argument("--end", default="2023-12")
    p.add_argument("--res", default="4km", choices=["4km", "800m"])
    p.add_argument("--output", type=Path, default=Path("data/processed/prism_monthly_puget.zarr"))
    p.add_argument("--raw-dir", type=Path, default=Path("data/raw/prism"))
    args = p.parse_args()
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    fetch_prism_monthly(tuple(args.bbox), args.start, args.end, args.res, args.output, args.raw_dir)


if __name__ == "__main__":
    main()
