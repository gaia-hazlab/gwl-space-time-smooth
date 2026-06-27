"""Foundational hydrogeologic-domain mask for the PNW GWL framework (issue #2).

PNW groundwater lives in physically distinct flow systems that a single statistical
surface — and a single pooled error metric — cannot span. This module classifies every
90 m cell into one of six **hydrogeologic domains**. Everything downstream (the Stage 1
prior, the per-domain validation gates of #3, the variogram-driven confidence mask of
#4, and the LandLab/geotech coupling of #12) strata on this layer.

Governing principle (from the groundwater-hydrologist review): the HAND-based prior and a
shallow-water-table assumption are valid in unconsolidated valley fill, but fail in
fractured uplands, deep spring-fed volcanic terrain, and pumped confined basalt. Classify
the domain *before* modelling, validating, or masking.

Domains
-------
0 unconsolidated_valley_fill : alluvial/glacial fill, low HAND — the well-dense, shallow,
                               liquefaction-relevant core (water table ≈ subdued topography).
1 unconsolidated_basin       : alluvial/glacial, higher HAND (terraces, broad basins).
2 fractured_upland           : consolidated bedrock with relief — Western Cascades /
                               Olympic cores. Shallow fracture flow; sparse wells. The
                               landslide/road (LandLab) regime.
3 volcanic_deep              : young High-Cascade basalt + stratovolcano edifices. Deep,
                               spring-fed, decoupled from topography. **Out of domain** for
                               a shallow water-table product — masked downstream.
4 confined_basalt            : Columbia River Basalt Group (CRBG) layered confined aquifers,
                               heavily pumped. Not a shallow water table — masked downstream.
5 coastal                    : near-shore cells where the water table is pinned near sea
                               level (boundary-condition zone; see #10).

Classification is a documented, priority-ordered rule set (see ``classify_domains``).
The messy, dataset-specific step — mapping raw WA DNR / USGS geology unit codes to the
four standardized lithology classes — is isolated in ``lithology_from_geology`` behind a
crosswalk JSON, so the core logic stays clean and testable.

Usage
-----
    python -m src.features.hydrogeologic_domains \
        --hand data/processed/terrain_hand_90m.tif \
        --slope data/processed/terrain_slope_90m.tif \
        --lithology data/processed/lithology_90m.tif \
        --dist-coast data/processed/dist_coast_90m.tif \
        --output-dir data/processed
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import rasterio

logger = logging.getLogger(__name__)

NODATA = -9999.0
DOMAIN_NODATA = 255  # uint8 nodata for the categorical output

# Domain code → name (the public legend).
DOMAINS: dict[int, str] = {
    0: "unconsolidated_valley_fill",
    1: "unconsolidated_basin",
    2: "fractured_upland",
    3: "volcanic_deep",
    4: "confined_basalt",
    5: "coastal",
}

# Standardized lithology classes consumed by classify_domains().
LITHO_UNCONSOLIDATED = 0   # alluvium, glacial drift/outwash
LITHO_BEDROCK = 1          # sedimentary/metamorphic/old volcanics (fractured)
LITHO_VOLCANIC_YOUNG = 2   # High-Cascade basalt, stratovolcano edifices
LITHO_CRBG = 3             # Columbia River Basalt Group

# ── Classification thresholds (documented; tune per region) ──────────────────
COAST_BUFFER_M = 2000.0    # cells within this distance of the shoreline ...
COAST_HAND_MAX = 10.0      # ... and this low above drainage are coastal boundary cells
VALLEY_HAND_MAX = 8.0      # unconsolidated cells at/below this HAND are valley fill
# (slope and depth-to-bedrock are accepted for future refinement / fallback heuristics)


def classify_domains(
    hand_m: np.ndarray,
    lithology: np.ndarray,
    dist_coast_m: np.ndarray,
    slope_deg: np.ndarray | None = None,
    dtb_m: np.ndarray | None = None,
    *,
    coast_buffer_m: float = COAST_BUFFER_M,
    coast_hand_max: float = COAST_HAND_MAX,
    valley_hand_max: float = VALLEY_HAND_MAX,
) -> np.ndarray:
    """Classify each cell into a hydrogeologic domain (priority-ordered rules).

    Exactly one label per cell. Priority (first match wins):

    1. **coastal** — within ``coast_buffer_m`` of the shoreline *and* HAND ≤
       ``coast_hand_max`` (the sea-level boundary zone; overrides valley fill at the
       immediate shore).
    2. **confined_basalt** — lithology = CRBG.
    3. **volcanic_deep** — lithology = young volcanics (High Cascade / edifice).
    4. **fractured_upland** — lithology = consolidated bedrock.
    5. **unconsolidated_valley_fill** — unconsolidated *and* HAND ≤ ``valley_hand_max``.
    6. **unconsolidated_basin** — remaining unconsolidated.

    Cells with NaN/nodata lithology are returned as ``DOMAIN_NODATA``.

    Returns a ``uint8`` array of domain codes (``DOMAINS`` legend).
    """
    hand_m = np.asarray(hand_m, dtype=np.float32)
    lithology = np.asarray(lithology, dtype=np.float32)  # float to carry NaN
    dist_coast_m = np.asarray(dist_coast_m, dtype=np.float32)
    if not (hand_m.shape == lithology.shape == dist_coast_m.shape):
        raise ValueError("hand, lithology, dist_coast must share one shape")

    valid = ~np.isnan(lithology)
    is_coastal = (dist_coast_m <= coast_buffer_m) & (hand_m <= coast_hand_max)
    is_crbg = lithology == LITHO_CRBG
    is_volcanic = lithology == LITHO_VOLCANIC_YOUNG
    is_bedrock = lithology == LITHO_BEDROCK
    is_uncon = lithology == LITHO_UNCONSOLIDATED
    is_valley = is_uncon & (hand_m <= valley_hand_max)

    # np.select applies conditions in priority order.
    conditions = [is_coastal, is_crbg, is_volcanic, is_bedrock, is_valley, is_uncon]
    choices = [5, 4, 3, 2, 0, 1]
    domain = np.select(conditions, choices, default=DOMAIN_NODATA).astype(np.uint8)
    domain[~valid] = DOMAIN_NODATA
    return domain


def lithology_from_geology(
    geology_codes: np.ndarray, crosswalk: dict[str, int]
) -> np.ndarray:
    """Map raw geology unit codes (e.g. WA DNR surficial geology) to lithology classes.

    ``crosswalk`` maps the *string* of each raw unit code to one of the ``LITHO_*``
    classes. Unmapped codes become NaN (and therefore ``DOMAIN_NODATA`` downstream), so
    coverage gaps are explicit rather than silently misclassified.

    This crosswalk is the dataset-specific, human-curated artifact; ship the real WA DNR /
    USGS-hydrogeologic-unit table as ``lithology_crosswalk.json`` (see ``--crosswalk``).
    """
    out = np.full(geology_codes.shape, np.nan, dtype=np.float32)
    for raw, litho in crosswalk.items():
        out[geology_codes == float(raw)] = litho
    return out


def _read(path: Path) -> tuple[np.ndarray, dict]:
    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float32)
        arr[arr == src.nodata] = np.nan
        if NODATA is not None:
            arr[arr == NODATA] = np.nan
        return arr, src.profile.copy()


def _write_categorical(domain: np.ndarray, profile: dict, path: Path) -> None:
    p = profile.copy()
    p.update({"dtype": "uint8", "count": 1, "nodata": DOMAIN_NODATA,
              "compress": "LZW", "tiled": True, "blockxsize": 256, "blockysize": 256})
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **p) as dst:
        dst.write(domain, 1)
        # embed the legend so the categorical raster is self-describing
        dst.update_tags(**{f"DOMAIN_{k}": v for k, v in DOMAINS.items()})
    logger.info("Domain mask written: %s", path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the PNW hydrogeologic-domain mask (issue #2).")
    parser.add_argument("--hand", type=Path, default=Path("data/processed/terrain_hand_90m.tif"))
    parser.add_argument("--slope", type=Path, default=Path("data/processed/terrain_slope_90m.tif"))
    parser.add_argument("--lithology", type=Path, default=Path("data/processed/lithology_90m.tif"),
                        help="Standardized lithology classes (0 uncon, 1 bedrock, 2 young-volcanic, 3 CRBG).")
    parser.add_argument("--geology", type=Path, default=None,
                        help="Raw geology unit-code raster; mapped via --crosswalk if --lithology absent.")
    parser.add_argument("--crosswalk", type=Path, default=Path("data/processed/lithology_crosswalk.json"),
                        help="JSON mapping raw geology codes -> lithology classes.")
    parser.add_argument("--dist-coast", type=Path, default=Path("data/processed/dist_coast_90m.tif"))
    parser.add_argument("--dtb", type=Path, default=Path("data/processed/depth_to_bedrock_90m.tif"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    hand, profile = _read(args.hand)
    dist_coast, _ = _read(args.dist_coast)
    slope = _read(args.slope)[0] if args.slope and Path(args.slope).exists() else None
    dtb = _read(args.dtb)[0] if args.dtb and Path(args.dtb).exists() else None

    # Lithology: prefer the standardized raster; otherwise crosswalk a raw geology raster.
    if args.lithology and Path(args.lithology).exists():
        lithology = _read(args.lithology)[0]
    elif args.geology and Path(args.geology).exists():
        crosswalk = json.loads(Path(args.crosswalk).read_text())
        lithology = lithology_from_geology(_read(args.geology)[0], crosswalk)
    else:
        raise FileNotFoundError(
            "Provide --lithology (standardized) or --geology + --crosswalk. Domains cannot "
            "distinguish volcanic_deep / confined_basalt without a geology input."
        )

    domain = classify_domains(hand, lithology, dist_coast, slope_deg=slope, dtb_m=dtb)

    out_dir = Path(args.output_dir)
    out_path = out_dir / "hydrogeologic_domain_90m.tif"
    _write_categorical(domain, profile, out_path)

    # Legend + per-domain cell counts (used by #3/#4 reporting).
    counts = {DOMAINS[k]: int((domain == k).sum()) for k in DOMAINS}
    counts["nodata"] = int((domain == DOMAIN_NODATA).sum())
    (out_dir / "hydrogeologic_domain_legend.json").write_text(
        json.dumps({"legend": DOMAINS, "cell_counts": counts}, indent=2)
    )
    logger.info("Domain cell counts: %s", counts)

    # STAC provenance (acceptance criterion).
    try:
        from src.io.stac_publish import make_stac_item, save_stac_item
        item = make_stac_item(
            product_path=out_path, product_id="hydrogeologic_domain_wa_90m",
            source="WA-DNR-geology + USGS-hydrogeologic-units + 3DEP-HAND + coastline",
            measurement="hydrogeologic domain class (categorical)",
            resolution_m=90,
            extra_properties={"gaia:legend": DOMAINS},
        )
        save_stac_item(item, out_dir)
    except Exception as exc:  # provenance is best-effort; never block the product
        logger.warning("STAC item not written (%s).", exc)


if __name__ == "__main__":
    main()
