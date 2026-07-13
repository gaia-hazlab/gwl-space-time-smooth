"""Fetch NRCS SNOTEL soil-moisture stations (independent in-situ θ anchors).

SNOTEL stations carry capacitance soil-moisture sensors (element ``SMS``, volumetric %) at
several depths, concentrated in the mountains — exactly the sparse *upland* regime where the
terrain/climate soil-moisture model is weakest. Because these are direct field measurements,
they are **independent of the SOLUS texture and TerraClimate/PRISM forcing** that drive the
model, so they provide the project's first genuinely independent θ validation (unlike the
TerraClimate ``soil`` cross-check, which shares forcing).

Access: the public NRCS AWDB REST API (no auth). Quirk: soil moisture must be requested with a
depth suffix, ``SMS:{depth_in_inches}`` (bare ``SMS`` returns nothing).

Output: ``snotel_soil_moisture_monthly.parquet`` — per station/month, a QC'd, depth-weighted
root-zone θ (m³/m³) comparable to the model's 0–1 m bucket, plus station metadata.

Usage:
  python -m src.data.fetch_snotel --start 2000-01 --end 2023-12 \
      --output data/processed/snotel_soil_moisture_monthly.parquet
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_BASE = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
# Puget lowland pilot + adjacent Cascades (where the SMS stations live).
# Domain is defined ONCE in src.config.domain (issue #92). Do not re-declare a bbox here.
from src.config.domain import PUGET_CASCADES_BBOX  # noqa: E402

CANDIDATE_DEPTHS_IN = (-2, -4, -8, -20, -40)   # SNOTEL SMS sensor depths (inches)
IN_TO_M = 0.0254


def find_sms_stations(bbox, network="SNTL") -> pd.DataFrame:
    """Return SNOTEL stations within ``bbox`` that report soil moisture (element SMS)."""
    import requests

    w, s, e, n = bbox
    # 1) All stations (metadata only — the element list can't be returned for all at once).
    allst = requests.get(f"{_BASE}/stations", timeout=90).json()
    inbox = [st for st in allst if st.get("networkCode") == network and st.get("latitude")
             and w <= st["longitude"] <= e and s <= st["latitude"] <= n]
    triplets = [st["stationTriplet"] for st in inbox]
    # 2) Element lists for just those triplets → keep those reporting soil moisture (SMS).
    meta = {st["stationTriplet"]: st for st in inbox}
    r = requests.get(f"{_BASE}/stations", params={"stationTriplets": ",".join(triplets),
                     "returnStationElements": "true"}, timeout=90)
    r.raise_for_status()
    rows = []
    for st in r.json():
        if any(el.get("elementCode") == "SMS" for el in st.get("stationElements", [])):
            m = meta[st["stationTriplet"]]
            rows.append({"triplet": st["stationTriplet"], "name": m["name"],
                         "lat": m["latitude"], "lon": m["longitude"], "elev_ft": m.get("elevation")})
    df = pd.DataFrame(rows)
    logger.info("Found %d SNOTEL soil-moisture stations in %s (of %d SNOTEL in bbox)",
                len(df), bbox, len(inbox))
    return df


def _fetch_series(triplet: str, element: str, start: str, end: str) -> pd.Series:
    """Daily series for one element (e.g. 'SMS:-8') → pandas Series indexed by date (or empty)."""
    import requests

    r = requests.get(f"{_BASE}/data", params={"stationTriplets": triplet, "elements": element,
                     "duration": "DAILY", "beginDate": start, "endDate": end}, timeout=90)
    if not r.ok or not r.json() or not r.json()[0].get("data"):
        return pd.Series(dtype="float64")
    vals = r.json()[0]["data"][0]["values"]
    idx = pd.to_datetime([v["date"] for v in vals])
    return pd.Series([v.get("value") for v in vals], index=idx, dtype="float64")


def fetch_station_theta(triplet: str, start: str, end: str) -> pd.DataFrame | None:
    """Depth-weighted, QC'd, monthly root-zone θ (m³/m³) for one station.

    QC: drop physically impossible values (<0 or >60 %); mask months where the shallowest soil
    temperature is ≤ 0 °C (frozen → capacitance θ unreliable). Root-zone θ is the depth-interval
    -weighted mean of the available shallow sensors (≤ ~0.5 m), converted % → m³/m³.
    """
    sms, sto = {}, {}
    for d in CANDIDATE_DEPTHS_IN:
        s = _fetch_series(triplet, f"SMS:{d}", start, end)
        if not s.empty:
            sms[d] = s.where((s >= 0) & (s <= 60))          # % QC
            sto[d] = _fetch_series(triplet, f"STO:{d}", start, end)  # soil temp for frozen mask
    if not sms:
        return None

    # Use shallow sensors (≤ 20 in ≈ 0.5 m) to match the root-zone bucket; depth-interval weights.
    use = [d for d in sms if abs(d) <= 20]
    if not use:
        use = list(sms)
    frame = pd.DataFrame({d: sms[d] for d in use})
    weights = np.array([abs(d) for d in use], dtype="float64")
    weights = weights / weights.sum()
    theta_daily = (frame * weights).sum(axis=1, min_count=1) / 100.0   # % → m³/m³

    # Frozen mask from shallowest soil temperature, if present.
    shallow = min(use, key=abs)
    if shallow in sto and not sto[shallow].empty:
        frozen = sto[shallow].reindex(theta_daily.index) <= 0.0
        theta_daily = theta_daily.mask(frozen)

    df = theta_daily.to_frame("theta_obs").dropna()
    if df.empty:
        return None
    df["year"] = df.index.year
    df["month"] = df.index.month
    monthly = df.groupby(["year", "month"]).theta_obs.agg(["mean", "size"]).reset_index()
    monthly = monthly.rename(columns={"mean": "theta_obs", "size": "n_days"})
    monthly = monthly[monthly.n_days >= 10]                 # ≥10 valid days/month
    monthly["depths_in"] = ",".join(str(d) for d in sorted(use))
    return monthly


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"), default=PUGET_CASCADES_BBOX)
    p.add_argument("--start", default="2000-01")
    p.add_argument("--end", default="2023-12")
    p.add_argument("--output", type=Path, default=Path("data/processed/snotel_soil_moisture_monthly.parquet"))
    args = p.parse_args()

    stations = find_sms_stations(tuple(args.bbox))
    start = f"{args.start}-01"
    end = pd.Period(args.end, "M").to_timestamp("M").strftime("%Y-%m-%d")

    out = []
    for _, st in stations.iterrows():
        m = fetch_station_theta(st.triplet, start, end)
        if m is None:
            logger.info("  %s (%s): no usable SMS", st.triplet, st["name"])
            continue
        for c in ("triplet", "name", "lat", "lon", "elev_ft"):
            m[c] = st[c]
        out.append(m)
        logger.info("  %s (%s): %d station-months, θ %.2f–%.2f", st.triplet, st["name"], len(m),
                    m.theta_obs.min(), m.theta_obs.max())

    if not out:
        raise SystemExit("no SNOTEL soil-moisture data retrieved for the bbox/period.")
    df = pd.concat(out, ignore_index=True)
    df["date"] = pd.to_datetime(dict(year=df.year, month=df.month, day=1))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output)
    logger.info("Wrote %s — %d station-months from %d stations", args.output, len(df), df.triplet.nunique())


if __name__ == "__main__":
    main()
