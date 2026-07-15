"""In-situ soil moisture from EVERY AWDB network in the domain (SNOTEL, SCAN), unified (#SM-networks).

`fetch_snotel.py` pulls SNOTEL (SNTL) only. The USDA AWDB REST API serves several soil-moisture
networks through the same endpoint -- SNOTEL, SCAN (Soil Climate Analysis Network), SNOWLITE -- so a
single generic fetch picks up all of them, and SCAN stations appear automatically as the domain grows
into agricultural terrain (there are none in the mountainous v0.4 footprint; SNOTEL is the only in-situ
soil-moisture source here, which is itself the observing-system finding).

Two things this staging is built to do, per the gaia conventions:
  - stage as **Zarr** through `src.io.zarr_store` (local or Kopah), like every other stream;
  - carry the **temporal metadata** (hourly cadence) so the space-time observability design
    (`src.models.observability`) can weight it against a weekly satellite.

    python -m src.data.fetch_insitu_sm --start 2025-09-01 --end 2026-03-31
"""

from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd
import requests

from src.config.domain import DOMAIN
from src.data.fetch_snotel import CANDIDATE_DEPTHS_IN, _BASE, _fetch_series

logger = logging.getLogger("fetch_insitu_sm")

SM_NETWORKS = ("SNTL", "SCAN", "SNLT")     # AWDB soil-moisture networks (SNOWLITE = SNLT)


def find_sm_stations(bbox=None, networks=SM_NETWORKS):
    """Every AWDB station in ``bbox`` reporting soil moisture (element SMS), across all networks."""
    bbox = bbox or DOMAIN.bbox_4326
    w, s, e, n = bbox
    allst = requests.get(f"{_BASE}/stations", timeout=90).json()
    inbox = [st for st in allst if st.get("networkCode") in networks and st.get("latitude")
             and w <= st["longitude"] <= e and s <= st["latitude"] <= n]
    if not inbox:
        return pd.DataFrame(columns=["triplet", "network", "name", "lat", "lon"])
    meta = {st["stationTriplet"]: st for st in inbox}
    r = requests.get(f"{_BASE}/stations",
                     params={"stationTriplets": ",".join(meta), "returnStationElements": "true"},
                     timeout=90)
    r.raise_for_status()
    rows = []
    for st in r.json():
        if any(el.get("elementCode") == "SMS" for el in st.get("stationElements", [])):
            m = meta[st["stationTriplet"]]
            rows.append({"triplet": st["stationTriplet"], "network": m["networkCode"],
                         "name": m["name"], "lat": m["latitude"], "lon": m["longitude"]})
    df = pd.DataFrame(rows)
    logger.info("in-situ SM stations in domain: %d (%s)", len(df),
                dict(df.network.value_counts()) if len(df) else {})
    return df


def fetch_insitu_sm(start, end, bbox=None, out="data/processed/insitu_sm_daily.zarr"):
    """Daily root-zone θ per station, staged as Zarr with (station, time) coords + lat/lon/network."""
    from src.io.zarr_store import write_zarr
    import xarray as xr

    st = find_sm_stations(bbox)
    if not len(st):
        raise ValueError("no in-situ soil-moisture stations in the domain")
    series = {}
    for _, r in st.iterrows():
        depths = {}
        for d in CANDIDATE_DEPTHS_IN:
            s = _fetch_series(r.triplet, f"SMS:{d}", start, end)
            if not s.empty:
                depths[d] = s.where((s >= 0) & (s <= 60))
        if not depths:
            continue
        use = [d for d in depths if abs(d) <= 20] or list(depths)     # shallow (root-zone) sensors
        wts = np.array([abs(d) for d in use], float); wts /= wts.sum()
        theta = (pd.DataFrame({d: depths[d] for d in use}) * wts).sum(axis=1, min_count=1) / 100.0
        series[r.triplet] = theta.resample("D").mean()
        logger.info("  %-10s %-26s %d days", r.network, str(r["name"])[:26], theta.notna().sum())
    if not series:
        raise ValueError("no SMS data returned for the window")

    frame = pd.DataFrame(series)
    frame.index.name = "time"
    meta = st.set_index("triplet").loc[frame.columns]
    ds = xr.Dataset(
        {"theta": (("time", "station"), frame.values.astype("float32"))},
        coords={"time": frame.index.values, "station": frame.columns.values,
                "lat": ("station", meta.lat.values), "lon": ("station", meta.lon.values),
                "network": ("station", meta.network.values)},
    )
    ds["theta"].attrs.update(units="m3/m3", long_name="root-zone volumetric soil moisture")
    ds.attrs.update(source="USDA AWDB (SNOTEL/SCAN), element SMS", cadence="hourly->daily",
                    revisit_days=0.04, role="in-situ soil-moisture OBSERVATION (measurement)")
    write_zarr(ds, out)
    return ds


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Unified in-situ soil moisture (SNOTEL+SCAN) -> Zarr.")
    p.add_argument("--start", default="2025-09-01")
    p.add_argument("--end", default="2026-03-31")
    p.add_argument("--out", default="data/processed/insitu_sm_daily.zarr")
    a = p.parse_args()
    ds = fetch_insitu_sm(a.start, a.end, out=a.out)
    logger.info("staged %d stations x %d days -> %s", ds.sizes["station"], ds.sizes["time"], a.out)


if __name__ == "__main__":
    main()
