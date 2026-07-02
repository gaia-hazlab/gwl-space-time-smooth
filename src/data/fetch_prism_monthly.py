"""Fetch monthly PRISM precipitation + temperature (alternative soil-moisture forcing).

PRISM (Daly et al., Oregon State) is a station-interpolated, observation-based monthly
climate product for the CONUS at ~4 km (and 800 m). It is an alternative **dynamic forcing**
for the gaia-soil-hydromechanics soil-moisture bucket, complementing TerraClimate:

  * PRISM precipitation is observation-based (station-anchored), not a reanalysis, and is
    available at higher native resolution — a more independent forcing.
  * PRISM ships temperature but **no reference ET**, so PET is derived here from monthly mean
    temperature via the Hamon (1961) temperature–daylength method — keeping the forcing fully
    observation-driven. (Hargreaves is available when tmin/tmax are fetched.)

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


def hamon_pet_mm(tmean_c: xr.DataArray, times: pd.DatetimeIndex, lat: np.ndarray) -> np.ndarray:
    """Monthly Hamon (1961) potential ET (mm) from mean temperature + daylength.

    PET_day = 0.1651 * (N/12) * rho_sat * K, with rho_sat the saturated vapour density
    (g m^-3) at tmean, N the mean daylight hours (from latitude + day-of-year), K≈1.2.
    Monthly total = PET_day * days_in_month. Vectorised over (time, lat, lon).
    """
    T = np.asarray(tmean_c.values, dtype="float64")            # (time, lat, lon)
    latg = np.broadcast_to(lat[None, :, None], T.shape)        # latitude per cell (deg)
    doy = np.array([t.dayofyear for t in times], dtype="float64")
    days = np.array([t.days_in_month for t in times], dtype="float64")

    # Daylight hours N from solar declination + sunset hour angle.
    phi = np.radians(latg)
    decl = 0.409 * np.sin(2 * np.pi * doy[:, None, None] / 365.0 - 1.39)
    x = np.clip(-np.tan(phi) * np.tan(decl), -1.0, 1.0)
    N = 24.0 / np.pi * np.arccos(x)                            # daylight hours

    # Saturated vapour density (g/m^3): e_s (hPa) via Tetens, then ideal-gas.
    es = 6.108 * np.exp(17.27 * T / (T + 237.3))               # hPa
    rho_sat = 216.7 * es / (T + 273.3)                         # g/m^3

    pet_day = 0.1651 * (N / 12.0) * rho_sat * 1.2
    pet_month = np.where(T > 0.0, pet_day, 0.0) * days[:, None, None]  # no PET below freezing
    return np.clip(pet_month, 0.0, None).astype("float32")


def fetch_prism_monthly(bbox, start: str, end: str, res: str, output: Path, raw_dir: Path) -> Path:
    months = pd.period_range(start=start, end=end, freq="M")
    ppt_list, tmean_list = [], []
    for i, m in enumerate(months):
        ym = f"{m.year}{m.month:02d}"
        ppt_list.append(_fetch_month_element("ppt", ym, res, bbox, raw_dir))
        tmean_list.append(_fetch_month_element("tmean", ym, res, bbox, raw_dir))
        if i % 24 == 0:
            logger.info("PRISM %s (%d/%d)", ym, i + 1, len(months))

    times = pd.DatetimeIndex([m.to_timestamp() for m in months])
    lat = ppt_list[0].lat.values
    lon = ppt_list[0].lon.values
    precip = np.stack([d.values for d in ppt_list], axis=0).astype("float32")
    tmean = np.stack([d.values for d in tmean_list], axis=0).astype("float32")

    ds = xr.Dataset(
        {"precip_mm": (("time", "lat", "lon"), precip),
         "tmean_c": (("time", "lat", "lon"), tmean)},
        coords={"time": times, "lat": lat, "lon": lon},
    )
    ds["pet_mm"] = (("time", "lat", "lon"), hamon_pet_mm(ds["tmean_c"], times, lat))
    ds["precip_mm"].attrs = {"units": "mm/month", "source": "PRISM (services.nacse.org)"}
    ds["pet_mm"].attrs = {"units": "mm/month", "method": "Hamon (1961) from PRISM tmean"}
    ds.attrs.update(source="PRISM monthly (Daly et al.)", native_resolution=res,
                    role="alternative dynamic forcing for soil moisture (ensemble member)",
                    pet_method="Hamon temperature-daylength")

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
