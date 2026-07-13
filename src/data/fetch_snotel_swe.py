"""SNOTEL snow-water-equivalent (element WTEQ) — the calibration target for the snow module (D8, #100).

We already ingest SNOTEL soil moisture; **SWE has always been the gap**, and it is now the thing that
matters most: the snowpack, not the unsaturated zone, is what lags the water table. TerraClimate SWE
over the Cascade-inclusive domain shows melt release peaking in **April** and the observed water table
peaking in **April**; our degree-day snow module exists but has never been exercised (the old lowland
domain is rain-dominated) and its parameters -- ddf, t_snow_hi/lo, t_melt -- have never been fitted.

SNOTEL stations sit at exactly the elevations where the snow actually is, which is why they, and not
the 4 km PRISM grid, are the right calibration target: the rain/snow line is sharp and a 4 km cell
straddling it smears the partition.

    python -m src.data.fetch_snotel_swe --start 2025-09-01 --end 2026-06-30
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd
import requests

from src.config.domain import DOMAIN
from src.data.fetch_snotel import _BASE, _fetch_series

logger = logging.getLogger("snotel_swe")


def find_swe_stations(bbox=None, network="SNTL"):
    """SNOTEL stations inside the domain that report SWE (WTEQ).

    Two-step, as in ``fetch_snotel.find_sms_stations``: the API only returns element lists when it is
    given explicit station triplets, so fetch all stations, filter by bbox, then ask for elements.
    """
    bbox = bbox or DOMAIN.bbox_4326
    w, s, e, n = bbox
    allst = requests.get(f"{_BASE}/stations", timeout=90).json()
    inbox = [st for st in allst if st.get("networkCode") == network and st.get("latitude")
             and w <= st["longitude"] <= e and s <= st["latitude"] <= n]
    if not inbox:
        raise ValueError(f"no {network} stations in {bbox}")
    meta = {st["stationTriplet"]: st for st in inbox}
    r = requests.get(f"{_BASE}/stations",
                     params={"stationTriplets": ",".join(meta), "returnStationElements": "true"},
                     timeout=90)
    r.raise_for_status()
    rows = []
    for st in r.json():
        if any(el.get("elementCode") == "WTEQ" for el in st.get("stationElements", [])):
            m = meta[st["stationTriplet"]]
            rows.append({"triplet": st["stationTriplet"], "name": m["name"],
                         "lat": m["latitude"], "lon": m["longitude"],
                         "elev_m": (m.get("elevation") or 0) * 0.3048})
    df = pd.DataFrame(rows)
    logger.info("SNOTEL stations with SWE inside the domain: %d (of %d SNOTEL in bbox)",
                len(df), len(inbox))
    return df


def fetch_swe(start, end, bbox=None, out="data/processed/snotel_swe_daily.parquet"):
    st = find_swe_stations(bbox)
    frames = []
    for _, r in st.iterrows():
        swe = _fetch_series(r.triplet, "WTEQ", start, end)        # inches
        tavg = _fetch_series(r.triplet, "TAVG", start, end)       # degF
        prcp = _fetch_series(r.triplet, "PRCP", start, end)       # inches (daily increment)
        if swe.empty:
            continue
        d = pd.DataFrame({"swe_mm": swe * 25.4,
                          "tmean_c": (tavg - 32.0) * 5.0 / 9.0 if not tavg.empty else pd.NA,
                          "precip_mm": prcp * 25.4 if not prcp.empty else pd.NA})
        d["triplet"], d["name"], d["elev_m"] = r.triplet, r["name"], r.elev_m
        d.index.name = "date"
        frames.append(d.reset_index())
        logger.info("  %-28s %5.0f m  peak SWE %6.0f mm", str(r["name"])[:28], r.elev_m,
                    float(d.swe_mm.max()))
    if not frames:
        raise ValueError("no SNOTEL SWE retrieved")
    df = pd.concat(frames, ignore_index=True)
    df.to_parquet(out, index=False)
    logger.info("wrote %s (%d rows, %d stations)", out, len(df), df.triplet.nunique())
    return df


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="SNOTEL SWE (WTEQ) for the snow-module calibration.")
    p.add_argument("--start", default="2025-09-01")
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--out", default="data/processed/snotel_swe_daily.parquet")
    a = p.parse_args()
    fetch_swe(a.start, a.end, out=a.out)


if __name__ == "__main__":
    main()
