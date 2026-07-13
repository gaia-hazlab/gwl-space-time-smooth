"""Fetch NOAA USCRN soil moisture as an additional in-situ soil-moisture source (beyond SNOTEL).

The U.S. Climate Reference Network (USCRN) provides research-grade soil moisture at 5/10/20/50/100 cm
from a small, well-maintained station set. It complements NRCS SNOTEL (mountain-focused) with valley
and lowland stations. Data are public flat files (no credentials): daily CRND0103 products at
``ncei.noaa.gov/pub/data/uscrn/products/daily01``.

Output matches the SNOTEL schema so the two ingest through one combiner
(``src/data/soil_moisture_stations.py``): columns network, station, name, lat, lon, elev_m, year,
month, date, theta_obs (root-zone volumetric, depth-weighted over 0-100 cm). Raw daily files are
cached locally so re-runs never re-hit the network.
"""

from __future__ import annotations

import argparse
import io
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("fetch_uscrn")

# Domain is defined ONCE in src.config.domain (issue #92). Do not re-declare a bbox here.
from src.config.domain import PUGET_CASCADES_BBOX  # noqa: E402

BASE = "https://www.ncei.noaa.gov/pub/data/uscrn/products"
CACHE = Path("data/cache/uscrn")
# CRND0103 daily soil-moisture columns (1-based 19-23) and their depths (cm).
_SM_COLS = {18: 5.0, 19: 10.0, 20: 20.0, 21: 50.0, 22: 100.0}
_LAYER = {5.0: 7.5, 10.0: 7.5, 20.0: 20.0, 50.0: 40.0, 100.0: 50.0}   # representative thickness (cm)


def _stations(bbox):
    import urllib.request
    with urllib.request.urlopen(f"{BASE}/stations.tsv") as r:
        df = pd.read_csv(io.BytesIO(r.read()), sep="\t")
    w, s, e, n = bbox
    df = df[(df.LONGITUDE >= w) & (df.LONGITUDE <= e) & (df.LATITUDE >= s) & (df.LATITUDE <= n)]
    df = df[df.STATUS.astype(str).str.upper().isin(["OPERATIONAL", "COMMISSIONED"])] if "STATUS" in df else df
    return df.reset_index(drop=True)


def _file_key(row):
    return f"{row.STATE}_{str(row.LOCATION).replace(' ', '_')}_{str(row.VECTOR).replace(' ', '_')}"


def _fetch_daily(name, year, cache=CACHE):
    """Download one station-year CRND0103 file; cache it. Returns the local path or None."""
    import urllib.error
    import urllib.request

    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"CRND0103-{year}-{name}.txt"
    if f.exists():
        return f
    url = f"{BASE}/daily01/{year}/CRND0103-{year}-{name}.txt"
    try:
        with urllib.request.urlopen(url) as r:
            f.write_bytes(r.read())
        return f
    except urllib.error.HTTPError:
        return None
    except Exception as exc:
        logger.warning("USCRN %s %s failed: %s", name, year, exc)
        return None


def _rootzone_theta(vals):
    """Depth-weighted 0-100 cm mean of the five soil-moisture sensors (missing = -99 -> NaN)."""
    v = np.where(np.asarray(vals, dtype="float64") <= -90, np.nan, vals)
    depths = list(_SM_COLS.values())
    w = np.array([_LAYER[d] for d in depths])
    ok = np.isfinite(v)
    return float(np.sum(v[ok] * w[ok]) / np.sum(w[ok])) if ok.any() else np.nan


def fetch_uscrn(bbox=PUGET_CASCADES_BBOX, start_year=2015, end_year=2025, cache=CACHE):
    """Monthly root-zone soil moisture for USCRN stations in ``bbox``; SNOTEL-compatible schema."""
    stn = _stations(bbox)
    if stn.empty:
        logger.warning("no USCRN stations in bbox %s", bbox)
        return pd.DataFrame(columns=["network", "station", "name", "lat", "lon", "elev_m",
                                     "year", "month", "date", "theta_obs"])
    rows = []
    for _, s in stn.iterrows():
        key = _file_key(s)
        recs = []
        for yr in range(start_year, end_year + 1):
            f = _fetch_daily(key, yr, cache)
            if f is None:
                continue
            d = pd.read_csv(f, sep=r"\s+", header=None, na_values=["-9999.0", "-99.000"])
            date = pd.to_datetime(d[1].astype(int).astype(str), format="%Y%m%d", errors="coerce")
            theta = d[list(_SM_COLS)].apply(lambda r: _rootzone_theta(r.values), axis=1)
            recs.append(pd.DataFrame({"date": date, "theta_obs": theta}).dropna())
        if not recs:
            continue
        ts = pd.concat(recs)
        ts["year"] = ts.date.dt.year; ts["month"] = ts.date.dt.month
        mon = (ts.groupby(["year", "month"]).theta_obs.mean().reset_index())
        mon["date"] = pd.to_datetime(dict(year=mon.year, month=mon.month, day=1))
        mon["network"] = "USCRN"; mon["station"] = key; mon["name"] = str(s.NAME)
        mon["lat"] = float(s.LATITUDE); mon["lon"] = float(s.LONGITUDE)
        mon["elev_m"] = float(s.ELEVATION) if "ELEVATION" in s and pd.notna(s.ELEVATION) else np.nan
        rows.append(mon)
        logger.info("USCRN %s: %d months", key, len(mon))
    if not rows:
        return pd.DataFrame(columns=["network", "station", "name", "lat", "lon", "elev_m",
                                     "year", "month", "date", "theta_obs"])
    return pd.concat(rows, ignore_index=True)[
        ["network", "station", "name", "lat", "lon", "elev_m", "year", "month", "date", "theta_obs"]]


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Fetch USCRN monthly soil moisture (SNOTEL-compatible).")
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"),
                   default=PUGET_CASCADES_BBOX)
    p.add_argument("--start-year", type=int, default=2015)
    p.add_argument("--end-year", type=int, default=2025)
    p.add_argument("--output", default="data/processed/uscrn_soil_moisture_monthly.parquet")
    args = p.parse_args()
    df = fetch_uscrn(tuple(args.bbox), args.start_year, args.end_year)
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    logger.info("Wrote %d USCRN monthly records (%d stations) to %s",
                len(df), df.station.nunique() if len(df) else 0, out)


if __name__ == "__main__":
    main()
