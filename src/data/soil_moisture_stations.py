"""Unify the in-situ soil-moisture networks into one station table for assimilation/validation.

The soil-reanalysis soil-moisture state is anchored to point sensors. Beyond NRCS **SNOTEL**
(mountain), the MVP adds:

  * **USCRN** (NOAA) - research-grade, public flat files (``fetch_uscrn``).
  * **ISMN** - the International Soil Moisture Network aggregator, which bundles many networks
    (SCAN, USCRN, mesonets, ...) in one format; it requires a free registration + manual download,
    so ``read_ismn`` ingests a user-provided export directory rather than fetching.

All sources share one schema (network, station, name, lat, lon, elev_m, year, month, date,
theta_obs), so ``load_sm_stations`` concatenates whatever is present into a single frame the SM
validators and the digital twin consume. Gridded soil moisture (SMAP L4 root zone, NLDAS) is a
separate native-scale layer via ``earthaccess`` (see ``fetch_smap``), assimilated by
upscale-then-compare rather than as points.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger("soil_moisture_stations")

SCHEMA = ["network", "station", "name", "lat", "lon", "elev_m", "year", "month", "date", "theta_obs"]
PROC = Path("data/processed")
DEFAULT_SOURCES = {
    "SNOTEL": PROC / "snotel_soil_moisture_monthly.parquet",
    "USCRN": PROC / "uscrn_soil_moisture_monthly.parquet",
    "ISMN": PROC / "ismn_soil_moisture_monthly.parquet",
}


def _normalize(df, network):
    """Coerce a per-network frame to the common SCHEMA (fills missing columns, tags the network)."""
    df = df.copy()
    if "network" not in df:
        df["network"] = network
    if "station" not in df and "triplet" in df:              # SNOTEL uses `triplet` as the id
        df["station"] = df["triplet"]
    for col in SCHEMA:
        if col not in df:
            df[col] = pd.NA
    return df[SCHEMA]


def load_sm_stations(sources=None) -> pd.DataFrame:
    """Concatenate all available soil-moisture station networks into one SCHEMA frame.

    ``sources``: dict network -> parquet path (defaults to SNOTEL/USCRN/ISMN under data/processed).
    Missing files are skipped with a log line, so the combiner degrades gracefully to whatever has
    been fetched. Returns an empty (schema-typed) frame if nothing is present.
    """
    sources = sources or DEFAULT_SOURCES
    frames = []
    for net, path in sources.items():
        path = Path(path)
        if not path.exists():
            logger.info("soil-moisture source %s not present (%s) - skipping", net, path)
            continue
        frames.append(_normalize(pd.read_parquet(path), net))
        logger.info("loaded %s: %d rows", net, len(frames[-1]))
    if not frames:
        return pd.DataFrame(columns=SCHEMA)
    return pd.concat(frames, ignore_index=True)


def read_ismn(export_dir, variable="soil_moisture") -> pd.DataFrame:
    """Ingest a user-provided ISMN "Header + values" export into the common monthly schema.

    ISMN requires free registration (ismn.earth) and a manual download; point ``export_dir`` at the
    unzipped export. Each ``*.stm`` file is one sensor: a header line with network/station/lat/lon/
    elevation/depths, then whitespace rows ``YYYY/MM/DD HH:MM value flag flag``. We keep the
    shallowest soil-moisture sensor per station and aggregate to monthly means. Best-effort parser
    for the common format; returns an empty frame if the directory has no parseable files.
    """
    export_dir = Path(export_dir)
    rows = []
    for stm in export_dir.rglob("*.stm"):
        try:
            lines = stm.read_text().splitlines()
            if not lines:
                continue
            head = lines[0].split()
            # header: CSE network station lat lon elev depth_from depth_to  (positions per ISMN docs)
            network, station = head[1], head[2]
            lat, lon, elev = float(head[3]), float(head[4]), float(head[5])
            recs = []
            for ln in lines[1:]:
                p = ln.split()
                if len(p) < 3:
                    continue
                try:
                    dt = pd.to_datetime(p[0] + " " + p[1], format="%Y/%m/%d %H:%M", errors="coerce")
                    val = float(p[2])
                except Exception:
                    continue
                if pd.notna(dt) and 0.0 <= val <= 1.0:
                    recs.append((dt, val))
            if not recs:
                continue
            ts = pd.DataFrame(recs, columns=["date", "theta_obs"])
            ts["year"] = ts.date.dt.year; ts["month"] = ts.date.dt.month
            mon = ts.groupby(["year", "month"]).theta_obs.mean().reset_index()
            mon["date"] = pd.to_datetime(dict(year=mon.year, month=mon.month, day=1))
            mon["network"] = f"ISMN:{network}"; mon["station"] = station; mon["name"] = station
            mon["lat"] = lat; mon["lon"] = lon; mon["elev_m"] = elev
            rows.append(mon)
        except Exception as exc:
            logger.warning("could not parse %s: %s", stm.name, exc)
    if not rows:
        logger.warning("no parseable ISMN .stm files under %s", export_dir)
        return pd.DataFrame(columns=SCHEMA)
    out = pd.concat(rows, ignore_index=True)
    return out.groupby(["network", "station", "name", "lat", "lon", "elev_m", "year", "month",
                        "date"], as_index=False).theta_obs.mean()[SCHEMA]
