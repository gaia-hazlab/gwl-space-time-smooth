# Intermediate Data-Staging Plan (pre-gaia-cli)

**Status:** active prototyping plan while the GAIA DataHub staging CLI milestone is in
development. Everything here is designed so the dev team can adopt the artifacts
*verbatim* into `gaia-cli` when it ships — these are not throwaway local hacks, they are
the reference implementations.

**Context for the rename:** this repository is being repositioned from a groundwater-only
product (`gwl-space-time-smooth`) to **`gaia-soil-hydromechanics`** — a coupled
subsurface-state estimator for hazard mechanics. GWL becomes one module under that
umbrella. See [Scope & positioning](#scope--positioning). The rename itself is deferred;
this plan and the lithology deliverable land first.

---

## 1. Raster vs. polygons — the decision

The models want **raster**. `hydrogeologic_domains.classify_domains()` requires the
lithology layer as a categorical array aligned cell-for-cell with HAND and `dist_coast`
on the canonical 90 m EPSG:5070 grid. Rasterization must happen upstream of the model.

But "store the raw archive in Zarr" needs a caveat for the DataHub team: **Zarr is an
array container; DNR geology is vector polygons.** Clean division of responsibility:

| Tier | Format | Content | Lives where |
|------|--------|---------|-------------|
| Raw archive | **GeoParquet / GeoPackage** (vector) | DNR 100K geology polygons, original unit codes — lossless, authoritative | DataHub object store (not Zarr) |
| Derived analysis layer | **categorical COG / Zarr** (raster, 90 m) | standardized lithology classes `0/1/2/3`, nodata `255` | `s3://cresst/lithology-stac/…`, what models read |
| Scientific crosswalk | **JSON** | DNR-unit → standardized-class mapping (human-curated) | versioned alongside both |

→ **Action for DataHub team:** confirm whether "raw in Zarr" meant the rasterized grid
(fine) or literally the vector polygons (use GeoParquet instead). Zarr should hold the
*derived raster*, not the polygons.

---

## 2. The lithology deliverable (shipped in this repo)

Built now, to unblock prototyping and to be lifted into gaia-cli later:

- **`src/data/rasterize_geology.py`** — local polygon→90 m categorical raster producer.
  Output is byte-compatible with `fetch_gaia.fetch_lithology` (uint8, EPSG:5070, nodata
  255), so it's a drop-in substitute. Has a `--list-units` discovery mode to build the
  crosswalk against the *real* attribute table, and `--like` to align exactly to an
  existing model input (e.g. `terrain_hand_90m.tif`).
- **`data/processed/lithology_crosswalk.json`** — the scientific mapping, as a clearly
  marked **starter** keyed on the WA DNR `LITHOLOGY` controlled vocabulary, with a
  `refine` pass to split Miocene basalt (CRBG, class 3) from younger volcanics (class 2).
  **Must be verified/extended against the real DNR extract before any hazard run** — it is
  a template, not an authoritative table.

This `rasterize_geology.py` + `lithology_crosswalk.json` pair *is* the intermediate step
gaia-cli adopts: the CLI's job becomes "run this crosswalk on the staged DNR archive and
publish the result to the `lithology-stac` collection."

### How to run it

```bash
# 1. discover the units present in your DNR extract
python -m src.data.rasterize_geology --geology data/raw/geology/wa_dnr_geol.gpkg --list-units

# 2. edit data/processed/lithology_crosswalk.json until coverage is complete

# 3. rasterize, aligned to an existing 90 m model input
python -m src.data.rasterize_geology \
    --geology data/raw/geology/wa_dnr_geol.gpkg \
    --crosswalk data/processed/lithology_crosswalk.json \
    --like data/processed/terrain_hand_90m.tif \
    --output data/processed/lithology_90m.tif

# 4. build domains exactly as before — no code change downstream
python -m src.features.hydrogeologic_domains --lithology data/processed/lithology_90m.tif
```

WA DNR source: *Digital 1:100,000-scale Geology of Washington State* (WA DNR Division of
Geology and Earth Resources). USGS SGMC supplements out-of-state edges.

---

## 3. Intermediate storage ladder (local → cloud → cli)

Each rung keeps the same consumer interface, so promotion is a config change, not a
rewrite. `fetch_gaia._load_layer` already tries STAC, then falls back to a direct s3 Zarr
read; the local rung sits below that.

1. **Local rasterized COG (do now).** Drop `data/processed/lithology_90m.tif` (and any
   other staged layer) into `data/processed/`. Models read directly via their `--<layer>`
   flags. Zero CLI dependency. *This is the recommended unblock today.*
2. **Local static STAC catalog (cleanest migration).** Write a `file://` `catalog.json`
   over local COGs. `_load_layer` works unchanged; promoting to production is a one-line
   change of `LITHOLOGY_STAC_URL`. Use this when you want the prototype interface-identical
   to prod.
3. **Personal s3 prefix.** Stage `lithology_wa.zarr` under your own bucket; point the s3
   fallback at it. Mirrors prod exactly; needs credentials.
4. **gaia-cli (target).** DataHub publishes the `lithology-stac` collection from the staged
   DNR archive using the crosswalk above. Consumer flips to the hosted catalog URL.

---

## 4. Scope & positioning

**`gaia-soil-hydromechanics`** — coupled subsurface state for hazard mechanics, deliberately
*complementary* to (not competing with) the hydrology teams (HydroShare / HydroFrame).
Three coupled state variables, each with a static and a dynamic source:

| State variable | Static source | Dynamic source |
|----------------|---------------|----------------|
| Soil moisture | SOLUS100 / POLARIS texture & hydraulics | reanalysis / remote sensing |
| Groundwater level (GWL module = this repo today) | obs-anchored RF baseline | climate-response / TFN dynamics |
| Soil mechanical properties | SOLUS / Vs30 (Sanger & Maurer) | **dv/v** (ambient-noise velocity change → pore-pressure / saturation proxy) |

The **dv/v** channel is the differentiator no hydrology product has — it turns the lab's
seismic-monitoring strength into a dynamic mechanical-state observable. That is the reason
this is a hazard-mechanics product, not a water-table product.

**Downstream digital twins:** liquefaction (Sanger), landslide (LandLab), and future flood.

### Rename checklist (deferred — do not execute yet)

When the rename is greenlit, touch: repo name, README + badges, the Quarto book URL
(`gaia-hazlab.github.io/gwl-space-time-smooth`), `gwl_*` output naming (GWL becomes a
submodule namespace), and the CI workflow. GWL outputs stay valid; they move under a
`gwl/` node of the soil-hydromechanics DataTree.
