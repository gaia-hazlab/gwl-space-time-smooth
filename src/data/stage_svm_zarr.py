"""Stage the SVM / CVM17 shallow-Vs grid as chunked Zarr (local or Kopah).

The USGS release ships ``CVM17_L01.nc`` as a **6.2 GB netCDF that must be downloaded in full** before
a single Vs30 value can be read -- and it is captcha-gated, so it cannot even be scripted. Staged once
as chunked Zarr on Kopah, every downstream consumer reads only the bytes it needs (the Puget/Cascades
window, the shallow depth levels) straight over the network. That is the point of the gaia-cli staging
pattern, and it is why this is worth doing once.

    # one-off, from a machine that has the netCDF (see scripts/stage_svm.zsh):
    python -m src.data.stage_svm_zarr --nc data/raw/CVM17_L01.nc \
        --out s3://gaia/soil-twin/static/svm_cvm17.zarr

    # thereafter, anywhere, with no 6.2 GB download:
    python -m src.data.fetch_vs30 --source svm \
        --svm-zarr s3://gaia/soil-twin/static/svm_cvm17.zarr

Only ``vs`` is staged (``vp`` doubles the size and nothing here uses it). Chunks are spatial tiles
with the full depth axis, because every read is "a window, all depths" -- the shape of the Vs30
travel-time integral.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import xarray as xr

from src.io.zarr_store import write_zarr

logger = logging.getLogger("stage_svm_zarr")

# (utme, utmn, z) tiles: 256*256*22*4 B ~ 5.8 MB, close to the 10 MB gaia-cli target
CHUNKS = {"utme": 256, "utmn": 256, "z": -1}


def stage(nc, out, vs_var="vs", drop_vp=True):
    ds = xr.open_dataset(nc, chunks={})                     # lazy: never loads the 6.2 GB
    keep = [vs_var] if drop_vp else list(ds.data_vars)
    ds = ds[keep]
    ds = ds.chunk({k: v for k, v in CHUNKS.items() if k in ds.dims})
    ds[vs_var].attrs.update(
        units="m/s",
        long_name="shear-wave velocity (SVM shallow soils + CVM)",
        depth_datum=("z=0 is the GROUND SURFACE (terrain-following), NOT sea level -- verified: the "
                     "shallowest sample has median Vs ~206 m/s, i.e. soil, not rock at sea level. The "
                     "FGDC metadata's 'depth below sea level' is boilerplate."),
    )
    ds.attrs.update(
        title="SVM / CVM17 shallow Vs (Cascadia), staged for the GAIA soil twin",
        article_doi="10.26443/seismica.v4i2.1672",
        data_release_doi="10.5066/P14HJ3IC",
        source_file=Path(nc).name,
        crs="EPSG:32610",
        note="Vs30 = travel-time average of the 30 m below each column's own ground surface.",
    )
    logger.info("staging %s -> %s (chunks %s)", nc, out, CHUNKS)
    return write_zarr(ds, out)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Stage the SVM shallow-Vs netCDF as chunked Zarr.")
    p.add_argument("--nc", type=Path, default=Path("data/raw/CVM17_L01.nc"))
    p.add_argument("--out", default="data/processed/svm_cvm17.zarr",
                   help="Local .zarr path or s3://gaia/soil-twin/static/svm_cvm17.zarr on Kopah.")
    p.add_argument("--vs-var", default="vs")
    a = p.parse_args()
    if not a.nc.exists():
        raise SystemExit(f"{a.nc} not found -- stage it first with scripts/stage_svm.zsh")
    stage(a.nc, a.out, a.vs_var)


if __name__ == "__main__":
    main()
