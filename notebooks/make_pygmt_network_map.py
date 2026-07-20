"""A PyGMT map of the ground sensor networks over the domain: NWIS wells, SNOTEL, and UW/CC
seismic stations, on shaded relief.

Run: ``pixi run pygmt-network-map``
"""
from __future__ import annotations

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


def main():
    from src.config.domain import DOMAIN

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

    region = [lon0, lon1, lat0, lat1]
    fig = pygmt.Figure()
    pygmt.config(FONT_TITLE="15p,Helvetica-Bold", FONT_ANNOT_PRIMARY="9p", FONT_LABEL="10p",
                MAP_FRAME_TYPE="plain")

    relief = pygmt.datasets.load_earth_relief(resolution="03s", region=region, registration="gridline")

    title = "Ground sensor networks — western Cascades domain"
    fig.basemap(region=region, projection="M14c", frame=["af", f"WSne+t{title}"])

    # A LINEAR land-only elevation ramp (not hillshade-driven): reserving most of the color range for
    # the Cascades/Mt Rainier (up to ~4400 m) and compressing the 0-300 m Puget lowland into a narrow,
    # near-uniform light band -- so the lowland's small-scale glacial-till texture doesn't visually
    # compete with the actual biggest topography in the domain. Shading intensity is deliberately weak
    # and the image is given some transparency, both requested fixes for a basemap that read too dark.
    pygmt.makecpt(cmap="oleron", series=[0, 4400], no_bg=True)
    shade = pygmt.grdgradient(grid=relief, radiance=[315, 45], normalize="t0.25")
    fig.grdimage(grid=relief, cmap=True, shading=shade, region=region, projection="M14c", transparency=50)

    # Paint water OVER the relief image with GMT's own coastline polygons -- simpler and more robust
    # than aligning a separate land/sea raster mask to the relief grid, and keeps Puget Sound, lakes,
    # and rivers a clean, uniform color instead of showing (mostly zero) bathymetry texture.
    fig.coast(region=region, projection="M14c", water="steelblue4", resolution="f", area_thresh=0,
             rivers="r/0.5p,steelblue4")
    fig.coast(shorelines="1/0.4p,gray30", borders="2/0.6p,gray40", area_thresh=100,
              region=region, projection="M14c", resolution="f")

    fig.plot(x=domain_lons, y=domain_lats, pen="1.4p,255/90/0,-", close=True)

    fig.plot(x=wells.lon, y=wells.lat, style="c0.09c", fill="38/106/166", pen="0.25p,white",
             transparency=15, label="NWIS wells")
    fig.plot(x=snotel.lon, y=snotel.lat, style="t0.24c", fill="59/178/115", pen="0.4p,black",
             label="SNOTEL")
    fig.plot(x=seis.lon, y=seis.lat, style="s0.22c", fill="232/72/85", pen="0.4p,black",
             label="Seismic (UW/CC)")

    fig.basemap(region=region, projection="M14c", map_scale="jBL+w50k+o0.6c/0.6c+f+lkm")
    fig.legend(position="JBR+jBR+o0.3c", box="+gwhite+p0.6p,black")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=300)
    import shutil
    shutil.copy(OUT, ASSETS / OUT.name)
    print(f"wrote {OUT}  ({len(wells)} wells, {len(snotel)} SNOTEL, {len(seis)} seismic stations)")


if __name__ == "__main__":
    main()
