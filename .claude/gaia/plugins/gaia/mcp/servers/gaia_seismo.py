# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2", "httpx>=0.27"]
# ///
"""gaia-seismo — MCP server for seismic data discovery (keyless FDSN / USGS).

Tools (no API key, no ObsPy — direct FDSN/USGS web services over HTTP):

  - query_events(...)           USGS earthquake catalog (time/magnitude/region)
  - station_metadata(...)       FDSN station service: which stations/channels exist
  - waveform_availability(...)  FDSN availability service: is data actually there?

Serves the Data Engineer (data discovery & QC planning) and the Study Designer
(station/instrument planning). It finds and describes data; it does not download
waveforms — that belongs to the Data Engineer's pipeline (ObsPy in the project env).

FDSN data center is GAIA_FDSN_BASE (default EarthScope/IRIS). Run standalone:
  uv run --script gaia_seismo.py
"""

from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

USGS_EVENT = "https://earthquake.usgs.gov/fdsnws/event/1/query"
FDSN_BASE = os.environ.get("GAIA_FDSN_BASE", "https://service.iris.edu")
TIMEOUT = float(os.environ.get("GAIA_SEISMO_TIMEOUT", "30"))

mcp = FastMCP("seismo")


@mcp.tool()
def query_events(
    starttime: str,
    endtime: str,
    minmagnitude: float | None = None,
    minlatitude: float | None = None,
    maxlatitude: float | None = None,
    minlongitude: float | None = None,
    maxlongitude: float | None = None,
    limit: int = 50,
) -> list[dict]:
    """Query the USGS earthquake catalog.

    Args:
        starttime, endtime: ISO-8601, e.g. '2024-01-01' or '2024-01-01T00:00:00'.
        minmagnitude: optional magnitude floor.
        min/maxlatitude, min/maxlongitude: optional bounding box.
        limit: max events (1-500), largest magnitude first.

    Returns compact event records (time, magnitude, place, lat, lon, depth_km, id).
    """
    params: dict[str, str | float | int] = {
        "format": "geojson",
        "starttime": starttime,
        "endtime": endtime,
        "limit": max(1, min(int(limit), 500)),
        "orderby": "magnitude",
    }
    for k, v in (
        ("minmagnitude", minmagnitude),
        ("minlatitude", minlatitude),
        ("maxlatitude", maxlatitude),
        ("minlongitude", minlongitude),
        ("maxlongitude", maxlongitude),
    ):
        if v is not None:
            params[k] = v
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.get(USGS_EVENT, params=params)
        if r.status_code == 204:
            return []
        r.raise_for_status()
        feats = r.json().get("features", [])
    out = []
    for f in feats:
        p = f.get("properties", {})
        g = (f.get("geometry") or {}).get("coordinates") or [None, None, None]
        out.append(
            {
                "id": f.get("id"),
                "time_utc": p.get("time"),  # epoch ms; convert in-agent if needed
                "magnitude": p.get("mag"),
                "magtype": p.get("magType"),
                "place": p.get("place"),
                "longitude": g[0],
                "latitude": g[1],
                "depth_km": g[2],
            }
        )
    return out


def _parse_fdsn_text(text: str) -> list[dict]:
    """Parse an FDSN text response (header line starts with '#', '|'-delimited)."""
    rows: list[dict] = []
    header: list[str] | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            header = [h.strip().lower() for h in line.lstrip("#").split("|")]
            continue
        cells = [c.strip() for c in line.split("|")]
        if header and len(cells) == len(header):
            rows.append(dict(zip(header, cells)))
        else:
            rows.append({"raw": line})
    return rows


@mcp.tool()
def station_metadata(
    network: str,
    station: str = "*",
    channel: str = "*",
    level: str = "station",
) -> list[dict]:
    """Look up station/channel metadata from the FDSN station service.

    Args:
        network: network code, e.g. 'UW', 'IU' (wildcards ok).
        station: station code or '*'.
        channel: channel code or '*' (e.g. 'BH?', 'HHZ').
        level: 'network' | 'station' | 'channel' | 'response' (text format omits
               response detail; use 'channel' for sample rates & coordinates).

    Returns one record per matching row (codes, coordinates, dates, etc.).
    """
    params = {
        "net": network,
        "sta": station,
        "cha": channel,
        "level": level if level in ("network", "station", "channel") else "station",
        "format": "text",
        "nodata": "204",
    }
    url = f"{FDSN_BASE}/fdsnws/station/1/query"
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.get(url, params=params)
        if r.status_code == 204:
            return []
        r.raise_for_status()
        return _parse_fdsn_text(r.text)


@mcp.tool()
def waveform_availability(
    network: str,
    station: str,
    location: str = "*",
    channel: str = "*",
    starttime: str | None = None,
    endtime: str | None = None,
) -> list[dict]:
    """Check whether waveform data actually exists for a station/channel/window.

    Uses the FDSN availability service. Returns the time spans that are present —
    so the Data Engineer can spot gaps before planning a download or QC pass.

    Args:
        network, station: codes (required).
        location, channel: codes or '*'.
        starttime, endtime: ISO-8601 window (optional but recommended).
    """
    params: dict[str, str] = {
        "net": network,
        "sta": station,
        "loc": location,
        "cha": channel,
        "format": "text",
        "nodata": "204",
    }
    if starttime:
        params["starttime"] = starttime
    if endtime:
        params["endtime"] = endtime
    url = f"{FDSN_BASE}/fdsnws/availability/1/query"
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.get(url, params=params)
        if r.status_code == 204:
            return [{"note": "no data available for this request (HTTP 204)"}]
        if r.status_code == 404:
            return [{"error": "availability service not offered by this FDSN data center"}]
        r.raise_for_status()
        return _parse_fdsn_text(r.text)


if __name__ == "__main__":
    mcp.run()
