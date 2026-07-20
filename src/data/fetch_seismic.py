"""Fetch UW + CC seismic stations and ambient-noise waveforms for dv/v monitoring.

The dv/v state variable needs continuous ambient-noise waveforms from Pacific Northwest
stations. Two Cascadia-region FDSN networks are used:

  * **UW** - Pacific Northwest Seismic Network (University of Washington regional network).
  * **CC** - USGS Cascades Volcano Observatory (Cascade Chain volcano-monitoring network).

Data access is through **seisfetch** (Denolle-Lab), a cloud-first client that reads the
EarthScope / SCEDC / NCEDC S3 archives and falls back to FDSN, decoding miniSEED to numpy
without ObsPy in the hot path. Waveform routing per the project decision:

    UW -> s3_auth   (EarthScope S3; fast, needs earthscope-sdk credentials)
    CC -> fdsn      (open FDSN; CC is not on the EarthScope S3 archive)

overridable with ``--backend``. Station **metadata** always goes through the open
fdsnws-station service (no credentials), so ``fetch_inventory`` runs anywhere.

Everything is cached locally so we never re-hit the network for the same request (the compute
constraint): metadata as parquet, waveforms as one raw-miniSEED file per station-day.

Downstream: ``src/models/dvv.py`` turns waveforms into daily cross-correlations and a banded dv/v(t)
(processing-ensemble Cd), then separates that into groundwater level (deep, low-freq) and soil
moisture (shallow, high-freq) at the water-table depth; ``notebooks/make_dvv_figures.py`` wires it.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger("fetch_seismic")

# Same Puget + Cascades pilot window used by the SNOTEL / TerraClimate fetchers.
# Domain is defined ONCE in src.config.domain (issue #92). Do not re-declare a bbox here.
from src.config.domain import PUGET_CASCADES_BBOX  # noqa: E402

NETWORKS = ("UW", "CC")
# Vertical channels only (single-component autocorrelation / cross-correlation dv/v): broadband
# (BH), high-sample-rate broadband (HH), short-period (EH), and strong-motion accelerometer (HN) --
# HN was previously omitted, silently dropping every accelerometer-only station (common at CC's
# volcano-monitoring sites, e.g. near Rainier) from the inventory.
CHANNELS = "BHZ,HHZ,EHZ,HNZ"
# Per-network waveform backend (metadata is always open fdsnws, independent of this).
WAVEFORM_BACKEND = {"UW": "s3_auth", "CC": "fdsn"}
CACHE = Path("data/cache/seismic")


def fetch_inventory(bbox=PUGET_CASCADES_BBOX, networks=NETWORKS, channels=CHANNELS,
                    start="2024-01-01", end="2025-12-31", cache=CACHE):
    """Return a station-level DataFrame for the requested networks within ``bbox``.

    Metadata only, via the open fdsnws-station service (no credentials). Cached as parquet;
    bbox filtering is client-side because ``get_stations`` queries by network/channel.
    """
    from seisfetch import SeisfetchClient

    import hashlib

    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    tag = "-".join(networks)
    # Cache key includes the query parameters so a different bbox/channels/window is not served a
    # stale frame; a short hash keeps the filename readable.
    key = hashlib.md5(f"{bbox}|{channels}|{start}|{end}".encode()).hexdigest()[:8]
    pq = cache / f"inventory_{tag}_{key}.parquet"
    if pq.exists():
        logger.info("Loaded cached inventory %s", pq)
        return pd.read_parquet(pq)

    w, s, e, n = bbox
    cl = SeisfetchClient(backend="fdsn")           # metadata client: no auth needed
    rows = []
    for net in networks:
        try:
            chans = cl.get_stations(net, channel=channels, starttime=start, endtime=end)
        except Exception as exc:                    # service hiccup - keep other networks
            logger.warning("Network %s metadata query failed: %s", net, exc)
            continue
        for c in chans:
            lat, lon = float(c["Latitude"]), float(c["Longitude"])
            if not (w <= lon <= e and s <= lat <= n):
                continue
            rows.append(dict(network=c["Network"], station=c["Station"], channel=c["Channel"],
                             location=c.get("Location", "") or "", lat=lat, lon=lon,
                             elev_m=float(c["Elevation"]),
                             start=c.get("StartTime", ""), end=c.get("EndTime", "")))
        logger.info("Network %s: %d channels in bbox", net, sum(r["network"] == net for r in rows))

    if not rows:
        return pd.DataFrame(columns=["network", "station", "lat", "lon", "elev_m",
                                     "channels", "location"])
    ch = pd.DataFrame(rows)
    # Collapse channels to one row per station (keep the channel list).
    agg = (ch.groupby(["network", "station"])
             .agg(lat=("lat", "first"), lon=("lon", "first"), elev_m=("elev_m", "first"),
                  channels=("channel", lambda s: ",".join(sorted(set(s)))),
                  location=("location", "first"))
             .reset_index())
    agg.to_parquet(pq)
    logger.info("Cached %d stations to %s", len(agg), pq)
    return agg


def fetch_waveforms(network, station, channel_priority=("BHZ", "HHZ", "EHZ", "HNZ"),
                    start="2024-06-01", days=30, backend=None, cache=CACHE):
    """Download daily vertical-component miniSEED for one station; cache one file per day.

    Returns cached day-file paths. The waveform backend is chosen per network
    (``WAVEFORM_BACKEND``) unless ``backend`` overrides it. Missing days are skipped and
    logged, not retried, so a partial outage never aborts the run. seisfetch is imported and
    the client built lazily so the metadata path needs no S3/auth setup.
    """
    from datetime import datetime, timedelta

    from seisfetch import SeisfetchClient

    backend = backend or WAVEFORM_BACKEND.get(network, "fdsn")
    cl = SeisfetchClient(backend=backend)
    cache = Path(cache) / f"{network}.{station}"
    cache.mkdir(parents=True, exist_ok=True)
    t0 = datetime.fromisoformat(start)
    out = []
    for d in range(days):
        day = t0 + timedelta(days=d)
        nxt = day + timedelta(days=1)
        stamp = f"{day.year}{day.timetuple().tm_yday:03d}"
        f = cache / f"{network}.{station}.{stamp}.mseed"
        if f.exists():
            out.append(f)
            continue
        got = False
        for ch in channel_priority:
            try:
                raw = cl.get_raw(network, station, starttime=day.isoformat(),
                                 endtime=nxt.isoformat(), channel=ch)
            except Exception:
                continue
            if raw:
                f.write_bytes(raw)
                out.append(f)
                got = True
                break
        if not got:
            logger.debug("no data %s.%s %s", network, station, stamp)
    logger.info("%s.%s [%s]: cached %d/%d days under %s",
                network, station, backend, len(out), days, cache)
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Fetch UW+CC station metadata (and optionally waveforms).")
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"),
                   default=PUGET_CASCADES_BBOX)
    p.add_argument("--networks", nargs="+", default=list(NETWORKS))
    p.add_argument("--start", default="2024-01-01")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--waveforms", action="store_true",
                   help="also download a short waveform window per station (compute-heavy)")
    p.add_argument("--backend", default=None,
                   help="override the per-network waveform backend (s3_auth|fdsn|s3_open|obspy_fdsn)")
    p.add_argument("--wf-start", default="2024-06-01")
    p.add_argument("--wf-days", type=int, default=30)
    p.add_argument("--max-stations", type=int, default=8,
                   help="cap stations for the waveform download (compute)")
    p.add_argument("--output", default="data/processed/seismic_stations.parquet")
    args = p.parse_args()

    df = fetch_inventory(tuple(args.bbox), tuple(args.networks), start=args.start, end=args.end)
    if df.empty:
        raise SystemExit("no UW/CC stations found for the bbox.")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    logger.info("Wrote %d stations to %s", len(df), out)

    prov = dict(source="seisfetch (EarthScope/FDSN)", networks=list(args.networks),
                bbox=list(args.bbox), period=[args.start, args.end], channels=CHANNELS,
                waveform_backend=(args.backend or WAVEFORM_BACKEND),
                n_stations=int(len(df)),
                stations_by_network=df.network.value_counts().to_dict())
    if args.waveforms:
        cached = {}
        for _, r in df.head(args.max_stations).iterrows():
            files = fetch_waveforms(r.network, r.station, start=args.wf_start,
                                    days=args.wf_days, backend=args.backend)
            cached[f"{r.network}.{r.station}"] = len(files)
        prov["waveforms"] = dict(start=args.wf_start, days=args.wf_days, day_files=cached)

    Path("data/processed/seismic_provenance.json").write_text(json.dumps(prov, indent=2))
    logger.info("Wrote provenance data/processed/seismic_provenance.json")


if __name__ == "__main__":
    main()
