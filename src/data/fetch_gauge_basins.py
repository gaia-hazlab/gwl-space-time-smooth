"""Drainage-basin polygons for the USGS gauges, from the USGS NLDI service.

Why this exists (issue #90): the seasonal budget compared **domain-mean** PRISM against **gauge**
discharge and got Q (1639 mm) > P (1510 mm). That is not a mass violation -- the gauge basins are
Cascade *headwater* catchments that receive far more orographic precipitation than the domain mean.
Until precipitation is averaged over each gauge's OWN watershed, the mm columns are not comparable
and the water budget cannot honestly be closed.

The basin polygon is what makes the comparison legitimate: it lets us average P, and the model's
fluxes, over exactly the area the gauge integrates.

    python -m src.data.fetch_gauge_basins
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import requests

from src.data.fetch_usgs_discharge import PUGET_GAGES

logger = logging.getLogger("fetch_gauge_basins")

NLDI_BASIN = "https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-{gage}/basin"


def fetch_basins(gages=None, out=Path("data/processed/gauge_basins.gpkg")):
    """Basin polygon per gauge (EPSG:4326 from NLDI, reprojected to the analysis CRS EPSG:5070)."""
    rows = []
    for g in list(gages or PUGET_GAGES):
        r = requests.get(NLDI_BASIN.format(gage=g), timeout=60)
        if r.status_code != 200:
            logger.warning("%s: NLDI returned %s; skipping", g, r.status_code)
            continue
        gdf = gpd.GeoDataFrame.from_features(r.json()["features"], crs="EPSG:4326")
        gdf["site_no"] = g
        gdf["name"] = PUGET_GAGES.get(g, g)
        rows.append(gdf[["site_no", "name", "geometry"]])
    if not rows:
        raise ValueError("no basins retrieved from NLDI")

    basins = gpd.GeoDataFrame(gpd.pd.concat(rows, ignore_index=True), crs="EPSG:4326")
    basins = basins.to_crs("EPSG:5070")
    basins["area_km2"] = basins.area / 1e6
    out.parent.mkdir(parents=True, exist_ok=True)
    basins.to_file(out, driver="GPKG")
    for _, b in basins.iterrows():
        logger.info("%s %-28s %7.0f km2", b.site_no, b["name"], b.area_km2)
    logger.info("wrote %s", out)
    return basins


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="USGS gauge drainage basins from NLDI.")
    p.add_argument("--out", type=Path, default=Path("data/processed/gauge_basins.gpkg"))
    a = p.parse_args()
    fetch_basins(out=a.out)


if __name__ == "__main__":
    main()
