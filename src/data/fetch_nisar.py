"""Fetch NISAR L3 soil moisture (SME2, Beta v1) → monthly θ over the pilot, on a native ~200 m grid.

NISAR (NASA-ISRO SAR, launched mid-2025) estimates surface volumetric soil moisture from L-band
backscatter at ~200 m, ~2×/12 days — a satellite **observation independent of the SOLUS texture
and TerraClimate/PRISM forcing** that drive our model, and roughly 45× finer than SMAP's 9 km. It
plays the same role SMAP/MERRA-2 do here: an honest native-scale θ cross-check (upscale-then-
compare, not downscaling to 90 m), never a training anchor.

Two hard caveats, both enforced below, both the reason this module ships *ahead* of its use:
  1. **Temporal.** The SME2 product begins **2025-10-01** — there is no NISAR θ before then. Any
     requested window is clamped to the mission start, and a window entirely before it errors out.
  2. **Beta.** ASF labels this release *"not intended for use in scientific research."* This module
     stages and validates the data; **wiring NISAR θ into the actual analysis is deferred to the
     master plan** (ROADMAP milestones / GH issues), not done here.

Access: ASF DAAC via ``earthaccess`` (needs ~/.netrc with urs.earthdata.nasa.gov — same login as
SMAP/MERRA-2). Granules are regional HDF5 frames; each month's frames are cached under
``data/raw/nisar_sm/`` (re-runs only fetch what's missing) and binned onto a fixed ~200 m
geographic target grid over the bbox. The internal SME2 variable/coordinate names are resolved by
introspection (``find_var``) with ``--sm-var/--lat-var/--lon-var`` overrides, and the granule tree
is logged if resolution fails — so the layout is confirmed against a real granule when the data is
wired in, never fabricated here.

Product: short_name ``NISAR_L3_SME2_BETA_V1`` · concept ``C2850265000-ASF`` · DOI 10.5067/NIL3SME2-B1.

Usage:
  python -m src.data.fetch_nisar --start 2025-10 --end 2026-06 \
      --output data/processed/nisar_soil_moisture_monthly_puget.zarr
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Western-Cascades pilot (matches SMAP/MERRA-2 fetchers): W, S, E, N.
PUGET_BBOX_WGS84 = (-122.95, 47.05, -121.55, 48.15)

SHORT_NAME = "NISAR_L3_SME2_BETA_V1"          # ASF concept C2850265000-ASF
DOI = "10.5067/NIL3SME2-B1"
NISAR_SME2_START = pd.Timestamp("2025-10-01")  # product does not exist before this date
RES_DEG = 0.002                                # ~200 m target grid, NISAR's native SME2 scale

# Introspective name patterns for the (unverified-until-real-granule) SME2 HDF5 layout.
SM_PATTERNS = (r"soil.?moisture",)
LAT_PATTERNS = (r"(^|/)lat(itude)?$", r"latitude")
LON_PATTERNS = (r"(^|/)lon(gitude)?$", r"longitude")


def guard_temporal_window(start: str, end: str):
    """Clamp the request to the SME2 mission start; error if it lies entirely before it.

    Returns ``(start_period, end_period)`` as monthly ``pd.Period``. This is the load-bearing
    reason the module is safe to ship early: it refuses to silently return an empty product for
    the many pre-2025-10 dates in the project's 2000→present extent.
    """
    s = pd.Period(start, freq="M")
    e = pd.Period(end, freq="M")
    if e < NISAR_SME2_START.to_period("M"):
        raise SystemExit(
            f"NISAR SME2 begins {NISAR_SME2_START.date()}; requested window {start}..{end} is "
            "entirely before launch — no NISAR soil moisture exists for these dates."
        )
    smin = NISAR_SME2_START.to_period("M")
    if s < smin:
        logger.warning("start %s precedes NISAR SME2 (%s); clamping to %s", start, smin, smin)
        s = smin
    return s, e


def bbox_to_wkt(bbox) -> str:
    """WGS84 bbox (W, S, E, N) → closed CCW polygon WKT (asf_search ``intersectsWith`` form)."""
    w, s, e, n = bbox
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


def find_var(node, patterns) -> str | None:
    """First HDF5 dataset path under ``node`` whose name matches any regex in ``patterns``."""
    import h5py

    rx = re.compile("|".join(patterns), re.IGNORECASE)
    hits: list[str] = []

    def _visit(name, obj):
        if isinstance(obj, h5py.Dataset) and rx.search(name):
            hits.append(name)

    node.visititems(_visit)
    return hits[0] if hits else None


def make_target_grid(bbox, res=RES_DEG):
    """Fixed cell-centre lon/lat vectors for a regular ~``res``° grid over the bbox."""
    w, s, e, n = bbox
    lon_c = np.arange(w + res / 2, e, res)
    lat_c = np.arange(s + res / 2, n, res)
    return lon_c, lat_c


def bin_to_grid(lat, lon, vals, lon_c, lat_c):
    """nan-aware mean of scattered (lat, lon, vals) onto the (lat_c × lon_c) target grid.

    Points off-grid or non-finite are dropped; empty cells are NaN. Pure numpy so it is unit
    tested offline without any granule.
    """
    lat = np.asarray(lat).ravel()
    lon = np.asarray(lon).ravel()
    vals = np.asarray(vals, dtype="float64").ravel()
    ny, nx = lat_c.size, lon_c.size
    dx = lon_c[1] - lon_c[0] if nx > 1 else 1.0
    dy = lat_c[1] - lat_c[0] if ny > 1 else 1.0
    ci = np.round((lon - lon_c[0]) / dx).astype(int)
    ri = np.round((lat - lat_c[0]) / dy).astype(int)
    ok = np.isfinite(vals) & (ci >= 0) & (ci < nx) & (ri >= 0) & (ri < ny)
    ssum = np.zeros((ny, nx))
    scnt = np.zeros((ny, nx))
    np.add.at(ssum, (ri[ok], ci[ok]), vals[ok])
    np.add.at(scnt, (ri[ok], ci[ok]), 1.0)
    return np.where(scnt > 0, ssum / np.maximum(scnt, 1.0), np.nan)


def _dump_tree(node) -> None:
    import h5py

    logger.error("NISAR granule contents:")
    node.visititems(lambda name, obj: logger.error("  %s%s", name,
                    f"  {obj.shape}" if isinstance(obj, h5py.Dataset) else "/"))


def _read_granule(path, sm_var=None, lat_var=None, lon_var=None):
    """Read (θ, lat, lon) from one SME2 frame, resolving variable names by introspection."""
    import h5py

    with h5py.File(path, "r") as f:
        sm_var = sm_var or find_var(f, SM_PATTERNS)
        lat_var = lat_var or find_var(f, LAT_PATTERNS)
        lon_var = lon_var or find_var(f, LON_PATTERNS)
        if not (sm_var and lat_var and lon_var):
            _dump_tree(f)
            raise SystemExit(
                "could not locate soil-moisture / lat / lon in the NISAR granule (see tree above); "
                "pass --sm-var/--lat-var/--lon-var once the SME2 layout is confirmed."
            )
        sm = np.asarray(f[sm_var][...], dtype="float64")
        lat = np.asarray(f[lat_var][...], dtype="float64")
        lon = np.asarray(f[lon_var][...], dtype="float64")
    if lat.ndim == 1 and lon.ndim == 1 and sm.ndim == 2:
        lon, lat = np.meshgrid(lon, lat)
    sm = np.where((sm >= 0.0) & (sm <= 1.0), sm, np.nan)   # physical θ range (m³/m³)
    return sm, lat, lon


def fetch_nisar_monthly(bbox, start, end, output: Path, raw_dir: Path,
                        res=RES_DEG, sm_var=None, lat_var=None, lon_var=None) -> Path:
    import earthaccess

    for noisy in ("fsspec", "earthaccess", "h5py", "urllib3", "s3fs"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    s, e = guard_temporal_window(start, end)
    earthaccess.login(strategy="netrc")
    raw_dir = Path(raw_dir)
    lon_c, lat_c = make_target_grid(bbox, res)
    ny, nx = lat_c.size, lon_c.size
    logger.info("NISAR SME2 target grid %dx%d @ ~%.0f m over %s", ny, nx, res * 111_000, bbox)

    stack, times = [], []
    for m in pd.period_range(s, e, freq="M"):
        t0 = m.to_timestamp().strftime("%Y-%m-%d")
        t1 = m.to_timestamp("M").strftime("%Y-%m-%d")
        granules = earthaccess.search_data(short_name=SHORT_NAME, temporal=(t0, t1), bounding_box=bbox)
        if not granules:
            logger.info("  %s: no granules", m)
            continue
        month_cache = raw_dir / str(m)
        month_cache.mkdir(parents=True, exist_ok=True)
        paths = earthaccess.download(granules, str(month_cache))

        gsum = np.zeros((ny, nx))
        gcnt = np.zeros((ny, nx))
        for p in paths:
            try:
                sm, lat, lon = _read_granule(p, sm_var, lat_var, lon_var)
                g = bin_to_grid(lat, lon, sm, lon_c, lat_c)
            except SystemExit:
                raise
            except Exception as exc:  # transient / malformed granule
                logger.warning("  skip granule %s (%s)", Path(p).name, str(exc)[:80])
                continue
            ok = np.isfinite(g)
            gsum[ok] += g[ok]
            gcnt[ok] += 1
        theta = np.where(gcnt > 0, gsum / np.maximum(gcnt, 1.0), np.nan)
        if not np.isfinite(theta).any():
            logger.info("  %s: %d granules, no valid θ on grid", m, len(paths))
            continue
        stack.append(theta.astype("float32"))
        times.append(m.to_timestamp())
        logger.info("  %s: %d granules, %d valid cells, mean θ=%.3f", m, len(paths),
                    int(np.isfinite(theta).sum()), float(np.nanmean(theta)))

    if not stack:
        raise SystemExit("no NISAR SME2 data retrieved for bbox/period.")
    ds = xr.Dataset(
        {"theta_nisar": (("time", "lat", "lon"), np.stack(stack, 0))},
        coords={"time": pd.DatetimeIndex(times), "lat": lat_c.astype("float32"),
                "lon": lon_c.astype("float32")},
    )
    ds["theta_nisar"].attrs = {"units": "m3/m3",
                               "long_name": "NISAR SME2 surface soil moisture (Beta)"}
    ds.attrs.update(
        source=f"NISAR L3 SME2 Beta v1 (ASF DAAC), short_name={SHORT_NAME}, doi={DOI}",
        native_resolution="~200 m", grid=f"regular WGS84 ~{res}deg over pilot bbox", crs="EPSG:4326",
        role="independent satellite θ for native-scale validation (upscale-then-compare)",
        maturity="BETA — not for scientific research; inclusion in analysis deferred to ROADMAP milestones",
    )
    output = Path(output)
    if output.exists():
        import shutil
        shutil.rmtree(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(output, mode="w", consolidated=True)
    logger.info("Wrote %s — %d months %s..%s, %dx%d (cache: %s)", output, ds.time.size,
                str(ds.time.values[0])[:7], str(ds.time.values[-1])[:7], ny, nx, raw_dir)
    return output


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"), default=PUGET_BBOX_WGS84)
    p.add_argument("--start", default="2025-10")
    p.add_argument("--end", default="2026-06")
    p.add_argument("--res-deg", type=float, default=RES_DEG, help="target grid resolution (deg)")
    p.add_argument("--sm-var", default=None, help="override soil-moisture HDF5 path")
    p.add_argument("--lat-var", default=None, help="override latitude HDF5 path")
    p.add_argument("--lon-var", default=None, help="override longitude HDF5 path")
    p.add_argument("--output", type=Path,
                   default=Path("data/processed/nisar_soil_moisture_monthly_puget.zarr"))
    p.add_argument("--raw-dir", type=Path, default=Path("data/raw/nisar_sm"))
    args = p.parse_args()
    fetch_nisar_monthly(tuple(args.bbox), args.start, args.end, args.output, args.raw_dir,
                        args.res_deg, args.sm_var, args.lat_var, args.lon_var)


if __name__ == "__main__":
    main()
