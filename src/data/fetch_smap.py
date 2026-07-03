"""Fetch SMAP L3 enhanced soil moisture (SPL3SMP_E) → monthly θ over the pilot, on the SMAP grid.

SMAP (NASA, launched 2015) retrieves surface (0–5 cm) volumetric soil moisture from L-band
radiometry — a satellite **observation independent of the SOLUS texture and TerraClimate/PRISM
forcing** that drive our model. Comparing our θ to SMAP at **SMAP's native 9 km EASE-Grid 2.0
resolution** (upscale-then-compare, not downscaling SMAP to 90 m) is the honest independent
validation over the lowland pilot that SNOTEL could not give (SNOTEL sits only in the uplands,
and after bias-correction it became training data).

Access: NASA Earthdata via ``earthaccess`` (needs ~/.netrc with urs.earthdata.nasa.gov). Each
daily granule is a ~650 MB global HDF5, so we never download them — the EASE-Grid 2.0 (EPSG:6933)
pilot row/col window is fixed, so we lazily read just that hyperslab (AM ``soil_moisture`` +
PM ``soil_moisture_pm``) and average the month's overpasses to a monthly θ field.

Usage:
  python -m src.data.fetch_smap --start 2016-01 --end 2022-12 --max-per-month 6 \
      --output data/processed/smap_soil_moisture_monthly_puget.zarr
"""

from __future__ import annotations

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from pyproj import Transformer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PUGET_BBOX_WGS84 = (-122.95, 47.05, -121.55, 48.15)
# EASE-Grid 2.0 global M09 (9 km) definition.
_CELL = 9008.055210146
_NC, _NR = 3856, 1624
_X0, _Y0 = -_NC / 2 * _CELL, _NR / 2 * _CELL
_GRP_VAR = {"Soil_Moisture_Retrieval_Data_AM": "soil_moisture",
            "Soil_Moisture_Retrieval_Data_PM": "soil_moisture_pm"}


def _ease_window(bbox):
    """Fixed EASE-Grid 2.0 M09 row/col window covering the WGS84 bbox."""
    tf = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
    w, s, e, n = bbox
    xs, ys = tf.transform([w, e, w, e], [n, n, s, s])   # all four corners
    rows = [int((_Y0 - y) // _CELL) for y in ys]
    cols = [int((x - _X0) // _CELL) for x in xs]
    return min(rows), max(rows) + 1, min(cols), max(cols) + 1


def _grid_coords(r0, r1, c0, c1):
    """Projected (EPSG:6933) cell-centre x/y and geographic lat/lon for the window."""
    ys = _Y0 - (np.arange(r0, r1) + 0.5) * _CELL
    xs = _X0 + (np.arange(c0, c1) + 0.5) * _CELL
    xg, yg = np.meshgrid(xs, ys)
    inv = Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True)
    lon, lat = inv.transform(xg, yg)
    return xs, ys, lat, lon


def fetch_smap_monthly(bbox, start, end, max_per_month, output: Path) -> Path:
    import earthaccess
    import h5py

    # fsspec/HDF5-over-https is chatty and re-auths per open; quiet the logs and reuse a session.
    for noisy in ("fsspec", "earthaccess", "s3fs", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    earthaccess.login(strategy="netrc")
    r0, r1, c0, c1 = _ease_window(bbox)
    xs, ys, lat, lon = _grid_coords(r0, r1, c0, c1)
    ny, nx = r1 - r0, c1 - c0
    logger.info("Pilot EASE M09 window rows %d:%d cols %d:%d (%dx%d @ 9 km)", r0, r1, c0, c1, ny, nx)

    months = pd.period_range(start, end, freq="M")
    stack, times = [], []
    for m in months:
        t0 = m.to_timestamp().strftime("%Y-%m-%d")
        t1 = m.to_timestamp("M").strftime("%Y-%m-%d")
        granules = earthaccess.search_data(short_name="SPL3SMP_E", version="006",
                                           temporal=(t0, t1), bounding_box=bbox)
        if not granules:
            continue
        step = max(1, len(granules) // max_per_month)
        picked = granules[::step][:max_per_month]
        ssum = np.zeros((ny, nx)); scnt = np.zeros((ny, nx))
        handles = earthaccess.open(picked)              # one shared session for the month

        def _read(fh):
            """Read AM+PM pilot hyperslab from one granule → (values, valid-mask) sum/count."""
            out = np.zeros((ny, nx)); cnt = np.zeros((ny, nx))
            f = h5py.File(fh, "r")
            for grp, var in _GRP_VAR.items():
                sm = np.asarray(f[grp][var][r0:r1, c0:c1], dtype="float64")
                ok = (sm >= 0) & (sm <= 1)
                out[ok] += sm[ok]; cnt[ok] += 1
            return out, cnt

        # HDF5-over-https reads are network-bound, so read the month's granules concurrently.
        with ThreadPoolExecutor(max_workers=min(12, len(handles))) as ex:
            for fut in as_completed([ex.submit(_read, fh) for fh in handles]):
                try:
                    out, cnt = fut.result()
                    ssum += out; scnt += cnt
                except Exception as exc:  # transient network / granule read errors
                    logger.warning("  skip granule (%s)", str(exc)[:80])
        theta = np.where(scnt > 0, ssum / np.maximum(scnt, 1), np.nan)
        stack.append(theta.astype("float32")); times.append(m.to_timestamp())
        logger.info("  %s: %d granules, %d valid cells, mean θ=%.3f", m, len(picked),
                    int(np.isfinite(theta).sum()), float(np.nanmean(theta)))

    if not stack:
        raise SystemExit("no SMAP data retrieved for bbox/period.")
    ds = xr.Dataset(
        {"theta_smap": (("time", "y", "x"), np.stack(stack, 0)),
         "lat": (("y", "x"), lat.astype("float32")), "lon": (("y", "x"), lon.astype("float32"))},
        coords={"time": pd.DatetimeIndex(times), "y": ys, "x": xs},
    )
    ds["theta_smap"].attrs = {"units": "m3/m3", "long_name": "SMAP L3 enhanced surface soil moisture (0–5 cm)"}
    ds.attrs.update(source="SMAP SPL3SMP_E v006 (NASA NSIDC)", grid="EASE-Grid 2.0 M09 (EPSG:6933, 9 km)",
                    role="independent satellite θ for native-scale validation", crs="EPSG:6933")
    output = Path(output)
    if output.exists():
        import shutil
        shutil.rmtree(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(output, mode="w", consolidated=True)
    logger.info("Wrote %s — %d months %s..%s, %dx%d @ 9 km", output, ds.time.size,
                str(ds.time.values[0])[:7], str(ds.time.values[-1])[:7], ny, nx)
    return output


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"), default=PUGET_BBOX_WGS84)
    p.add_argument("--start", default="2016-01")
    p.add_argument("--end", default="2022-12")
    p.add_argument("--max-per-month", type=int, default=6)
    p.add_argument("--output", type=Path, default=Path("data/processed/smap_soil_moisture_monthly_puget.zarr"))
    args = p.parse_args()
    fetch_smap_monthly(tuple(args.bbox), args.start, args.end, args.max_per_month, args.output)


if __name__ == "__main__":
    main()
