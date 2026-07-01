"""Rasterize WA DNR (or any vector) surface geology to the standardized lithology grid.

This is the **intermediate / local** producer for the lithology layer while the GAIA
DataHub staging CLI is still in development. It does on your laptop exactly what the
DataHub ``Geology_Shoreline_Downloader`` notebook will eventually do on the server:

    raw polygons (DNR 100K geology)  ──crosswalk──►  lithology_90m.tif (categorical)

The output contract is identical to ``src.data.fetch_gaia.fetch_lithology`` so the two
are drop-in interchangeable: a categorical uint8 GeoTIFF on the canonical 90 m EPSG:5070
grid with classes ``0 unconsolidated / 1 fractured-bedrock / 2 young-volcanic / 3 CRBG``
and nodata ``255``. It is consumed directly by ``src.features.hydrogeologic_domains``
(``--lithology``) — no further regridding needed.

Because polygon→class is the *scientific* content, the crosswalk lives in a separate,
reviewable JSON (``lithology_crosswalk.json``). Hand that JSON + this script to the GAIA
dev team and they can fold the mapping into gaia-cli verbatim.

Workflow
--------
1. Discover the attribute values present in your DNR extract (so you can complete the
   crosswalk against the *real* table rather than guessing)::

       python -m src.data.rasterize_geology --geology data/raw/geology/wa_dnr_geol.gpkg \
           --list-units

2. Edit ``data/processed/lithology_crosswalk.json`` until every unit you care about maps
   to a class. Unmapped units become nodata (explicit, never silently misclassified).

3. Rasterize, aligned cell-for-cell to an existing 90 m model input (preferred — the
   domain classifier requires identical shapes)::

       python -m src.data.rasterize_geology \
           --geology data/raw/geology/wa_dnr_geol.gpkg \
           --crosswalk data/processed/lithology_crosswalk.json \
           --like data/processed/terrain_hand_90m.tif \
           --output data/processed/lithology_90m.tif

   …or to a bare EPSG:5070 bounding box when you don't have a reference raster yet::

       python -m src.data.rasterize_geology --geology ... --crosswalk ... \
           --bbox -2334000 2467000 -1103000 2998000
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

LITHO_NODATA = 255  # matches fetch_gaia.fetch_lithology nodata
TARGET_RES_M = 90.0

# Public legend, kept in lock-step with src.features.hydrogeologic_domains.LITHO_*.
CLASS_LEGEND = {
    0: "unconsolidated",     # alluvium, glacial drift / outwash, fill
    1: "fractured_bedrock",  # sedimentary / metamorphic / pre-Tertiary volcanics
    2: "young_volcanic",     # High Cascade basalt + stratovolcano edifices (Plio-Pleistocene+)
    3: "crbg",               # Columbia River Basalt Group (Miocene)
}


def _load_crosswalk(path: Path) -> dict:
    """Load and validate the geology→lithology crosswalk JSON.

    Schema (see data/processed/lithology_crosswalk.json):
        attribute_column : str           — vector column whose values `mapping` keys match
        mapping          : {value: int}  — attribute value → lithology class (0..3)
        refine           : [rule, ...]    — optional post-pass overrides, applied in order
            rule = {column, set_class, equals|contains}
                equals   : exact match (string-compared, case-insensitive)
                contains : substring / regex (case-insensitive) on the column value
    """
    cw = json.loads(Path(path).read_text())
    if "attribute_column" not in cw or "mapping" not in cw:
        raise ValueError(f"{path}: crosswalk must define 'attribute_column' and 'mapping'.")
    bad = {v for v in cw["mapping"].values() if v not in CLASS_LEGEND}
    if bad:
        raise ValueError(f"{path}: mapping has classes outside {sorted(CLASS_LEGEND)}: {bad}")
    return cw


def _norm(s) -> str:
    return "" if s is None else str(s).strip().lower()


def assign_classes(gdf, crosswalk: dict) -> np.ndarray:
    """Return an int array (len == len(gdf)) of lithology classes; LITHO_NODATA where unmapped."""
    col = crosswalk["attribute_column"]
    if col not in gdf.columns:
        raise KeyError(
            f"Column '{col}' not in geology layer. Available: {list(gdf.columns)}. "
            "Fix 'attribute_column' in the crosswalk (try --list-units)."
        )
    mapping = {_norm(k): int(v) for k, v in crosswalk["mapping"].items()}
    classes = np.array([mapping.get(_norm(v), LITHO_NODATA) for v in gdf[col]], dtype=np.int16)

    # Optional refinement pass — e.g. split generic "basalt" into CRBG vs young volcanic by age.
    for rule in crosswalk.get("refine", []):
        rcol, target = rule["column"], int(rule["set_class"])
        if rcol not in gdf.columns:
            logger.warning("refine rule skipped: column '%s' absent", rcol)
            continue
        vals = gdf[rcol].map(_norm).to_numpy()
        if "equals" in rule:
            hit = vals == _norm(rule["equals"])
        elif "contains" in rule:
            pat = re.compile(_norm(rule["contains"]))
            hit = np.array([bool(pat.search(v)) for v in vals])
        else:
            logger.warning("refine rule needs 'equals' or 'contains'; skipped: %s", rule)
            continue
        # only refine rows that the base mapping already classified (don't resurrect nodata)
        hit &= classes != LITHO_NODATA
        classes[hit] = target
        logger.info("refine: %s -> class %d on %d polygons", rule.get(rcol, rule), target, int(hit.sum()))
    return classes


def _grid_from_args(args):
    """Return (transform, width, height) for the target grid, from --like or --bbox."""
    if args.like:
        import rasterio
        with rasterio.open(args.like) as src:
            if src.crs is None or src.crs.to_epsg() != 5070:
                raise ValueError(f"--like raster CRS is {src.crs}; expected EPSG:5070.")
            return src.transform, src.width, src.height
    from rasterio.transform import from_bounds
    left, bottom, right, top = args.bbox
    width = int(round((right - left) / args.res))
    height = int(round((top - bottom) / args.res))
    return from_bounds(left, bottom, right, top, width, height), width, height


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--geology", type=Path, required=True,
                   help="Vector geology (GeoPackage/Shapefile/GeoParquet) — e.g. WA DNR 100K geology.")
    p.add_argument("--crosswalk", type=Path, default=Path("data/processed/lithology_crosswalk.json"))
    p.add_argument("--like", type=Path, default=None,
                   help="Reference 90 m EPSG:5070 raster to match exactly (preferred; e.g. terrain_hand_90m.tif).")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("L", "B", "R", "T"), default=None,
                   help="EPSG:5070 bounds (metres) if no --like raster is available.")
    p.add_argument("--res", type=float, default=TARGET_RES_M, help="Resolution (m) when using --bbox.")
    p.add_argument("--output", type=Path, default=Path("data/processed/lithology_90m.tif"))
    p.add_argument("--all-touched", action="store_true",
                   help="Burn every pixel a polygon touches (default: pixel-centre rule).")
    p.add_argument("--list-units", action="store_true",
                   help="Print unique attribute values + polygon counts for the crosswalk column, then exit.")
    args = p.parse_args()

    import geopandas as gpd  # imported late so --help works without the geo stack

    logger.info("Reading geology: %s", args.geology)
    gdf = gpd.read_file(args.geology) if args.geology.suffix != ".parquet" else gpd.read_parquet(args.geology)

    if args.list_units:
        # Best-effort: show counts for the crosswalk column if it exists, else every column's cardinality.
        col = None
        if args.crosswalk.exists():
            col = json.loads(args.crosswalk.read_text()).get("attribute_column")
        if col and col in gdf.columns:
            vc = gdf[col].value_counts(dropna=False)
            logger.info("Unique values of '%s' (%d distinct):", col, len(vc))
            for val, n in vc.items():
                logger.info("  %8d  %r", n, val)
        else:
            logger.info("Columns and cardinality (set 'attribute_column' to one of these):")
            for c in gdf.columns:
                if c != gdf.geometry.name:
                    logger.info("  %6d distinct  %s", gdf[c].nunique(dropna=False), c)
        return

    crosswalk = _load_crosswalk(args.crosswalk)
    if args.like is None and args.bbox is None:
        p.error("Provide --like (a reference 90 m raster) or --bbox (EPSG:5070 bounds).")

    if gdf.crs is None:
        raise ValueError("Geology layer has no CRS; cannot reproject. Define its CRS first.")
    gdf = gdf.to_crs(5070)

    classes = assign_classes(gdf, crosswalk)
    mapped = classes != LITHO_NODATA
    logger.info("Mapped %d / %d polygons (%.1f%%).", int(mapped.sum()), len(gdf),
                100 * mapped.mean() if len(gdf) else 0.0)
    if not mapped.any():
        raise ValueError("No polygons mapped — check 'attribute_column' / 'mapping' (see --list-units).")

    import rasterio
    from rasterio.features import rasterize

    transform, width, height = _grid_from_args(args)
    shapes = ((geom, int(c)) for geom, c, ok in zip(gdf.geometry, classes, mapped) if ok)
    arr = rasterize(
        shapes, out_shape=(height, width), transform=transform,
        fill=LITHO_NODATA, all_touched=args.all_touched, dtype="uint8",
    )

    counts = {CLASS_LEGEND[k]: int((arr == k).sum()) for k in CLASS_LEGEND}
    counts["nodata"] = int((arr == LITHO_NODATA).sum())
    logger.info("Lithology cell counts: %s", counts)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(
        driver="GTiff", height=height, width=width, count=1, dtype="uint8",
        crs="EPSG:5070", transform=transform, nodata=LITHO_NODATA,
        compress="LZW", tiled=True, blockxsize=256, blockysize=256,
    )
    with rasterio.open(args.output, "w", **profile) as dst:
        dst.write(arr, 1)
        dst.update_tags(**{f"CLASS_{k}": v for k, v in CLASS_LEGEND.items()})
        dst.update_tags(source="WA DNR surface geology (local rasterize_geology)",
                        crosswalk=str(args.crosswalk))
    logger.info("Lithology → %s", args.output)


if __name__ == "__main__":
    main()
