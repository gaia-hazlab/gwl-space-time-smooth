"""A PyGMT map of every ground/space observing network over the domain, employed and planned.

Run: ``pixi run pygmt-network-map``

Marker EDGE color is the convention: **black** = this repo's pipeline ingests real data from this
network today; **gray** = a real, located network with no fetcher/assimilation path here yet (see
``ObsStream.employed`` in ``src/models/observability.py``, the single source of truth this script
reads from for which is which). Two real networks fetched fresh for this figure (no fabricated
coordinates): USGS streamflow gauges (``data/processed/usgs_gauge_sites.parquet``, from the NWIS site
service) and GHCN-Daily weather stations + GNSS stations (``ghcn_weather_stations.parquet`` /
``gnss_stations.parquet``, from NOAA NCEI and the EarthScope/UNAVCO GAGE facility respectively).

Two networks are NOT point markers by construction and are noted in the caption/legend text instead:
Sentinel surface water (a time-lapse, geospatially DISTRIBUTED water-extent/height product, not a
station network -- its "sample points" are wherever the channel network is, at whatever cloud-free
pass happens weeks apart) and NOAA Stage IV radar precipitation (a 4 km CONUS-wide gridded analysis,
no station coordinates to plot at all).

Marker FILL color is a second convention, independent of the employed/planned edge: **blue** (shades)
for any network that observes water in some form -- wells (groundwater), USGS gauges (streamflow),
SNOTEL (SWE), GHCN-Daily (precipitation); **red/blue/purple** for a geophysical network *hosted by the
EarthScope Consortium* -- seismic dv/v (IRIS DMC) and GNSS-IR/TEC (the GAGE facility) -- using
EarthScope's own logo palette (red ``#ef3e42``, deep blue ``#22428d``, periwinkle-purple ``#8b9fc6``,
pulled from EarthScope's official logo SVG) rather than the water-blue family, even though GNSS-PWV
is itself a water-adjacent (atmospheric moisture) measurement -- the hosting-consortium convention
takes precedence for those two.
"""
from __future__ import annotations

import shutil
import sys
import warnings
from pathlib import Path

import pandas as pd
import pygmt
from pyproj import Transformer

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROC = Path("data/processed")
ASSETS = Path("docs/twin/assets")
OUT = Path("figures/demo/network_map_pygmt.png")
PAD_DEG = 0.15                          # a little air around the domain box on the map
EMPLOYED_PEN = "0.5p,black"              # currently ingested
PLANNED_PEN = "0.5p,gray45"              # real network, not yet ingested


def main():
    from src.config.domain import DOMAIN
    from src.models.observability import STREAMS

    employed = {s.name: s.employed for s in STREAMS}

    x0, y0, x1, y1 = DOMAIN.bounds()
    tf = Transformer.from_crs(DOMAIN.crs, "EPSG:4326", always_xy=True)
    lons, lats = tf.transform([x0, x1, x0, x1], [y0, y0, y1, y1])
    lon0, lon1 = min(lons) - PAD_DEG, max(lons) + PAD_DEG
    lat0, lat1 = min(lats) - PAD_DEG, max(lats) + PAD_DEG
    domain_lons = [min(lons), max(lons), max(lons), min(lons), min(lons)]
    domain_lats = [min(lats), min(lats), max(lats), max(lats), min(lats)]

    wells = pd.read_parquet(PROC / "nwis_sites_clean.parquet")
    seis = pd.read_parquet("data/cache/seismic/inventory_UW-CC.parquet")
    swe, sm = PROC / "snotel_swe_daily.parquet", PROC / "snotel_soil_moisture_monthly.parquet"
    snotel = pd.read_parquet(swe) if swe.exists() else pd.read_parquet(sm)
    snotel = snotel.drop_duplicates("triplet") if "triplet" in snotel.columns else snotel
    gauges = pd.read_parquet(PROC / "usgs_gauge_sites.parquet")
    ghcn = pd.read_parquet(PROC / "ghcn_weather_stations.parquet")
    ghcn = ghcn[ghcn.has_prcp & ghcn.active]
    gnss = pd.read_parquet(PROC / "gnss_stations.parquet")

    region = [lon0, lon1, lat0, lat1]
    fig = pygmt.Figure()
    pygmt.config(FONT_TITLE="15p,Helvetica-Bold", FONT_ANNOT_PRIMARY="9p", FONT_LABEL="10p",
                MAP_FRAME_TYPE="plain")

    # --- background: light, low-contrast GRAY relief (the sensors_and_dvv_support.png look), not a
    # colorful elevation ramp -- stations are the content here, the terrain is only orientation. ---
    relief = pygmt.datasets.load_earth_relief(resolution="03s", region=region, registration="gridline")
    title = "Observing networks — western Cascades domain (employed = black edge, planned = gray edge)"
    fig.basemap(region=region, projection="M14c", frame=["af", f"WSne+t{title}"])
    pygmt.makecpt(cmap="gray", series=[-1500, 4400], reverse=True)
    shade = pygmt.grdgradient(grid=relief, radiance=[315, 45], normalize="t0.2")
    fig.grdimage(grid=relief, cmap=True, shading=shade, region=region, projection="M14c", transparency=68)
    fig.coast(region=region, projection="M14c", water="gray75", resolution="f", area_thresh=0,
             rivers="r/0.4p,gray55")
    fig.coast(shorelines="1/0.4p,gray30", borders="2/0.6p,gray40", area_thresh=100,
              region=region, projection="M14c", resolution="f")
    fig.plot(x=domain_lons, y=domain_lats, pen="1.4p,255/90/0,-", close=True)

    def pen_for(stream_name):
        return EMPLOYED_PEN if employed.get(stream_name, True) else PLANNED_PEN

    # --- point/volume networks with real coordinates ------------------------------------------
    # Water-related networks: blue family (shape carries the distinction, not hue).
    fig.plot(x=wells.lon, y=wells.lat, style="c0.09c", fill="38/106/166", pen=pen_for("NWIS wells"),
             transparency=15, label=f"NWIS wells ({len(wells)})")
    fig.plot(x=snotel.lon, y=snotel.lat, style="t0.24c", fill="94/166/224",
             pen=pen_for("SNOTEL / SCAN θ"), label=f"SNOTEL ({len(snotel)})")
    fig.plot(x=gauges.lon, y=gauges.lat, style="i0.32c", fill="41/121/255", pen=pen_for("USGS gauges"),
             label=f"USGS gauges ({len(gauges)})")
    fig.plot(x=ghcn.lon, y=ghcn.lat, style="d0.16c", fill="179/229/252",
             pen=pen_for("GHCN-Daily weather stations"),
             label=f"GHCN-Daily stations ({len(ghcn)})")
    # Geophysical networks hosted by the EarthScope Consortium: its own logo palette, not water-blue.
    fig.plot(x=seis.lon, y=seis.lat, style="s0.22c", fill="239/62/66", pen=pen_for("Seismic dv/v"),
             label=f"Seismic dv/v ({len(seis)})")
    fig.plot(x=gnss.lon, y=gnss.lat, style="a0.30c", fill="139/159/198",
             pen=pen_for("GNSS-IR / GNSS-TEC precipitable water"),
             label=f"GNSS-IR/TEC PWV ({len(gnss)})")
    # Same physical stations as "Seismic dv/v" above -- a thin gray HALO marks the subset of them
    # that could ALSO serve as a streamflow proxy (Illien et al., seis-hydro-2-sed), not a new
    # point set. Deviation from the real gauge is expected to grow specifically during intense
    # atmospheric-river events, not gradually -- see the caption in 05-state-evaluation.qmd.
    fig.plot(x=seis.lon, y=seis.lat, style="s0.34c", fill=None, pen="0.9p,gray45,-",
             label="Seismic as streamgage proxy")

    fig.basemap(region=region, projection="M14c", map_scale="jBL+w50k+o0.6c/0.6c+f+lkm")

    # --- legend drawn OUTSIDE the map panel, in a dedicated strip to the right --------------------
    fig.shift_origin(xshift="14.6c")
    fig.basemap(region=[0, 1, 0, 1], projection="X7c/14c", frame="lrtb+gwhite")
    fig.legend(position="jTL+jTL+o0.2c/0.2c+w6.4c", box=False)
    fig.text(x=0.06, y=0.30, text="black edge = employed; gray edge = planned", font="9p,Helvetica-Bold",
             justify="TL", no_clip=True)
    fig.text(x=0.06, y=0.25, text="Not point networks (see caption):", font="10p,Helvetica-Bold",
             justify="TL", no_clip=True)
    fig.text(x=0.06, y=0.21, text="• Sentinel surface water — distributed", font="9p", justify="TL",
             no_clip=True)
    fig.text(x=0.10, y=0.18, text="water extent/height, ~weeks repeat", font="9p", justify="TL",
             no_clip=True)
    fig.text(x=0.06, y=0.13, text="• NOAA Stage IV radar precip —", font="9p", justify="TL",
             no_clip=True)
    fig.text(x=0.10, y=0.10, text="4 km gridded, domain-wide", font="9p", justify="TL", no_clip=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=300)
    shutil.copy(OUT, ASSETS / OUT.name)
    print(f"wrote {OUT}  ({len(wells)} wells, {len(snotel)} SNOTEL, {len(seis)} seismic, "
          f"{len(gauges)} gauges, {len(ghcn)} GHCN, {len(gnss)} GNSS)")


if __name__ == "__main__":
    main()
