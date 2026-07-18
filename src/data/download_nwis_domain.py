"""Download live NWIS groundwater levels for the active domain (not CONUS).

The CONUS pull (`download_nwis.py`) is a periodic snapshot and goes stale; the wells inside the western
Cascades domain DO report (100 sites have 2025-26 field measurements), they were just absent from the
last snapshot. This module refreshes only the domain: it queries the USGS Water Data OGC API
field-measurements collection (parameter 72019, depth-to-water below land surface, ft) by bounding box
and date, clips to the analysis grid, QCs disturbed readings, and writes a monthly table in the schema
the twin consumes -- **without** touching the CONUS `nwis_gwlevels_monthly.parquet`.

    pixi run download-nwis-domain                     # full history, for the site-mean baseline
    python -m src.data.download_nwis_domain --start 2000-01-01

Output:
    data/raw/nwis_domain/gwlevels_domain.parquet          raw field measurements, clipped to domain
    data/processed/nwis_gwlevels_domain_monthly.parquet   site x month medians (site_no, dtw_m, ...)

Set USGS_API_KEY to avoid anonymous throttling (free key: https://api.waterdata.usgs.gov/signup/).
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import pandas as pd
import requests
from pyproj import Transformer

from src.data.download_nwis import _get_with_backoff   # shared retry/backoff for 429/503/timeouts

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_FM_ITEMS = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements/items"
_GW_PARAM = "72019"        # depth to water below land surface, ft
_FT_TO_M = 0.3048
_PAGE = 1000
# qualifier strings that mark a disturbed / non-static reading -> drop (mirrors download_nwis.py)
_DROP_QUALIFIERS = {"pumping", "dry", "flowing", "obstructed", "recently pumped",
                    "recently flowing nearby", "nearby recently flowing", "injecting", "foreign substance"}


def _fetch_bbox(bbox: str, start: str, api_key: str | None) -> list[dict]:
    """Paginate the OGC field-measurements collection over a bbox from ``start`` to present."""
    params = {"f": "json", "bbox": bbox, "parameter_code": _GW_PARAM,
              "datetime": f"{start}/..", "limit": str(_PAGE)}
    if api_key:
        params["api_key"] = api_key
    feats: list[dict] = []
    url, p = _FM_ITEMS, params
    with requests.Session() as sess:
        sess.headers.update({"Accept": "application/geo+json"})
        while url is not None:
            r = _get_with_backoff(sess, url, p)   # retries 429/503/timeouts, raises other 4xx/5xx
            j = r.json()
            feats.extend(j.get("features", []))
            url, p = None, None
            for lnk in j.get("links", []):
                if lnk.get("rel") == "next":
                    url = lnk["href"]
                    break
    return feats


def run(start: str, out_raw: Path, out_monthly: Path) -> pd.DataFrame:
    from src.config.domain import DOMAIN

    api_key = os.environ.get("USGS_API_KEY")
    w, s, e, n = DOMAIN.bbox_4326
    logger.info("querying NWIS field-measurements for bbox %s from %s ...", (w, s, e, n), start)
    feats = _fetch_bbox(f"{w},{s},{e},{n}", start, api_key)
    logger.info("  %d raw records in bbox", len(feats))

    tf = Transformer.from_crs("EPSG:4326", DOMAIN.crs, always_xy=True)
    x0, y0, x1, y1 = DOMAIN.bounds()
    rows = []
    for f in feats:
        c = (f.get("geometry") or {}).get("coordinates")
        if not c:
            continue
        xm, ym = tf.transform(c[0], c[1])
        if not (x0 <= xm <= x1 and y0 <= ym <= y1):          # clip to the analysis rectangle
            continue
        pr = f["properties"]
        quals = [q.lower() for q in (pr.get("qualifier") or [])]
        if any(q in _DROP_QUALIFIERS for q in quals):        # drop disturbed readings
            continue
        val = pr.get("value")
        if val in (None, ""):
            continue
        mid = pr.get("monitoring_location_id", "")
        rows.append({
            "site_no": mid.split("-", 1)[1] if "-" in mid else mid,
            "date": pr.get("time", "")[:10],
            "lat": c[1], "lon": c[0],
            "dtw_m": float(val) * _FT_TO_M,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("no in-domain NWIS records returned; nothing written")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "dtw_m"])
    df = df[df["dtw_m"] >= 0]                                 # depth-to-water is non-negative
    out_raw.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_raw, index=False)

    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    monthly = (df.groupby(["site_no", "year", "month"])
               .agg(lat=("lat", "first"), lon=("lon", "first"),
                    dtw_m=("dtw_m", "median"), n_obs=("dtw_m", "size"))
               .reset_index())
    out_monthly.parent.mkdir(parents=True, exist_ok=True)
    monthly.to_parquet(out_monthly, index=False)

    recent = monthly[((monthly.year == 2025) & (monthly.month >= 9)) | (monthly.year == 2026)]
    logger.info("wrote %s  (%d site-months, %d sites; %d raw obs)",
                out_monthly, len(monthly), monthly.site_no.nunique(), len(df))
    logger.info("  IN-WINDOW (2025-09..2026): %d site-months across %d sites",
                len(recent), recent.site_no.nunique())
    return monthly


def main():
    ap = argparse.ArgumentParser(description="Download live in-domain NWIS groundwater levels")
    ap.add_argument("--start", default="2000-01-01", help="earliest date to fetch (default 2000-01-01)")
    ap.add_argument("--out-raw", type=Path, default=Path("data/raw/nwis_domain/gwlevels_domain.parquet"))
    ap.add_argument("--out-monthly", type=Path,
                    default=Path("data/processed/nwis_gwlevels_domain_monthly.parquet"))
    a = ap.parse_args()
    run(a.start, a.out_raw, a.out_monthly)


if __name__ == "__main__":
    main()
