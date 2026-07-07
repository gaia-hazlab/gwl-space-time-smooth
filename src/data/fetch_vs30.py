"""Vs30 (time-averaged shear-wave velocity, top 30 m) for the near-surface stiffness product.

Replaces the earlier synthetic HAND ramp (issue #54) with defensible Vs30 from three sources:

  1. **Wald-Allen slope proxy (default, always available).** Wald & Allen (2007) / Allen & Wald
     (2009) map topographic slope to Vs30 -- steeper terrain (bedrock outcrop, thin soil) is stiffer,
     flat valley fill is soft. This is the standard terrain proxy behind the USGS global Vs30 model,
     applied here to the native 90 m 3DEP slope. The Pacific Northwest (Cascadia) is active-tectonic,
     so the active-tectonic bins are used by default.
  2. **USGS global Vs30 grid** (the official product; a large ~30 arc-second GMT grid). Fetched and
     clipped where reachable; falls back to the slope proxy.
  3. **Sanger-Maurer parametric Vs30** (GAIA vs-STAC) -- a geology + geomorphon model. Placeholder
     that delegates to :func:`src.data.fetch_gaia.fetch_vs30`; the STAC is not always reachable.

Output: ``data/processed/vs30_90m.tif`` (EPSG:5070, 90 m). Unlike the HAND ramp, this is a real
site-condition estimate suitable (with its uncertainty) for NEHRP site class -- see the geotechnical
review in ``docs/peer_review.md``.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger("fetch_vs30")

PUGET_CASCADES_BBOX = (-123.3, 46.8, -120.8, 48.5)
USGS_GLOBAL_VS30_GRD = "https://apps.usgs.gov/shakemap_geodata/vs30/global_vs30.grd"

# Wald & Allen (2007) topographic-slope -> Vs30. Slope as gradient (m/m); Vs30 in m/s. Bins map to
# NEHRP classes E(180) / D(240-360) / C(490-620) / B(760). ACTIVE-TECTONIC table (Cascadia). Lower
# bin edges (exclusive-upper) and the Vs30 assigned at/above each edge. Verify against OFR 2007-1357.
_WA_ACTIVE_EDGES = np.array([2.2e-3, 6.3e-3, 0.018, 0.050, 0.10, 0.138])
_WA_ACTIVE_VS30 = np.array([180.0, 240.0, 300.0, 360.0, 490.0, 620.0, 760.0])
# Stable-continental bins are steeper for a given Vs30; not used for the PNW (kept for completeness).
_WA_STABLE_EDGES = np.array([2.0e-5, 2.0e-3, 4.0e-3, 7.2e-3, 0.013, 0.018])
_WA_STABLE_VS30 = np.array([180.0, 240.0, 300.0, 360.0, 490.0, 620.0, 760.0])


def wald_allen_vs30(slope_deg, region="active"):
    """Vs30 (m/s) from topographic slope (degrees) via the Wald-Allen binned proxy.

    ``region`` is ``"active"`` (default; Cascadia) or ``"stable"``. Slope is converted to gradient
    (tan of the angle) and binned. NaN slope -> NaN Vs30.
    """
    edges, vs30 = ((_WA_ACTIVE_EDGES, _WA_ACTIVE_VS30) if region == "active"
                   else (_WA_STABLE_EDGES, _WA_STABLE_VS30))
    s = np.asarray(slope_deg, dtype="float64")
    grad = np.tan(np.deg2rad(s))
    idx = np.digitize(grad, edges)                      # 0..len(edges) -> vs30 bin
    out = vs30[np.clip(idx, 0, len(vs30) - 1)]
    return np.where(np.isfinite(s), out, np.nan).astype("float32")


# NEHRP / ASCE 7 site-class Vs30 boundaries (m/s), soft -> stiff, and the classes they separate:
# E < 180 < D < 360 < C < 760 < B < 1500 < A. A design engineer reads P(class) and P(crossing a
# boundary), not a raw percent sigma -- issue #53.
NEHRP_BOUNDS = np.array([180.0, 360.0, 760.0, 1500.0])
NEHRP_CLASSES = ("E", "D", "C", "B", "A")


def nehrp_class_probabilities(vs30_mean, vs30_std, lognormal=False):
    """P(NEHRP site class) from a Vs30 estimate and its 1-sigma.

    Returns probabilities ``P(E, D, C, B, A)`` that the *true* Vs30 falls in each ASCE 7 / NEHRP
    class, with a trailing axis of length 5. Scalars return a length-5 vector; arrays broadcast over
    the input shape (so a whole Vs30 field maps to a per-cell class-probability stack). This turns the
    Vs30 uncertainty into the quantity a geotechnical design consumer needs -- P(class) and, by
    differencing the CDF, P(Vs30 crossing 180 / 360 / 760 m/s) -- rather than a raw percent sigma.

    ``lognormal=True`` treats ``vs30_std`` as the sigma of ln(Vs30) (the field-standard multiplicative
    error model, and requires ``vs30_mean > 0``); otherwise ``vs30_std`` is a linear m/s sigma
    (matching the dv/v-propagated 1-sigma). A zero sigma collapses to a one-hot class assignment
    (the deterministic bin of the mean). ``vs30_std`` must be non-negative.
    """
    from scipy.stats import norm

    mu = np.asarray(vs30_mean, dtype="float64")
    sd = np.asarray(vs30_std, dtype="float64")
    if np.any(sd < 0):
        raise ValueError("vs30_std must be non-negative")
    if lognormal and np.any(mu <= 0):
        raise ValueError("lognormal=True requires vs30_mean > 0")
    mu, sd = np.broadcast_arrays(mu, sd)                   # common shape so the zero-sd mask lines up
    with np.errstate(divide="ignore", invalid="ignore"):
        loc = np.log(mu)[..., None] if lognormal else mu[..., None]
        bnd = np.log(NEHRP_BOUNDS) if lognormal else NEHRP_BOUNDS
        cdf = norm.cdf((bnd - loc) / sd[..., None])        # P(Vs30 <= each boundary), shape (..., 4)
    lower = np.concatenate([np.zeros(cdf.shape[:-1] + (1,)), cdf], axis=-1)
    upper = np.concatenate([cdf, np.ones(cdf.shape[:-1] + (1,))], axis=-1)
    probs = upper - lower                                  # P in (E, D, C, B, A), shape (..., 5)
    zero = sd == 0                                         # sd==0 -> 0/0 NaN on an exact boundary
    if np.any(zero):
        onehot = np.eye(len(NEHRP_CLASSES))[np.digitize(mu, NEHRP_BOUNDS)]
        probs = np.where(zero[..., None], onehot, probs)
    return probs


def most_likely_nehrp_class(vs30_mean, vs30_std, lognormal=False):
    """(class_label, probability) of the most probable NEHRP class for a *scalar* Vs30 estimate."""
    p = nehrp_class_probabilities(vs30_mean, vs30_std, lognormal=lognormal)
    i = int(np.argmax(p))
    return NEHRP_CLASSES[i], float(p[i])


def vs30_from_slope(slope_tif, region="active"):
    """Apply the Wald-Allen proxy to a slope raster (degrees); returns a Vs30 DataArray (m/s)."""
    import rioxarray as rxr

    slope = rxr.open_rasterio(slope_tif, masked=True).squeeze("band", drop=True)
    vs = wald_allen_vs30(slope.values, region=region)
    return slope.copy(data=vs).rio.write_crs(slope.rio.crs)


def fetch_usgs_vs30(bbox=PUGET_CASCADES_BBOX, like=None, cache=Path("data/cache/vs30")):
    """Download + clip the USGS global Vs30 grid; returns a DataArray or None if unreachable.

    The global grid is a large (~600 MB) 30 arc-second GMT file; this attempts the documented URL,
    clips to ``bbox``, and (if ``like`` given) reprojects to that grid. On any failure it logs and
    returns None so the caller falls back to the slope proxy. Cached once downloaded.
    """
    import rioxarray as rxr

    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    local = cache / "global_vs30.grd"
    try:
        if not local.exists():
            import urllib.request
            logger.info("Downloading USGS global Vs30 grid (large) from %s ...", USGS_GLOBAL_VS30_GRD)
            urllib.request.urlretrieve(USGS_GLOBAL_VS30_GRD, local)
        w, s, e, n = bbox
        vs = rxr.open_rasterio(local, masked=True).squeeze("band", drop=True)
        vs = vs.rio.clip_box(w, s, e, n)
        return vs.rio.reproject_match(like) if like is not None else vs
    except Exception as exc:
        logger.warning("USGS Vs30 fetch unavailable (%s); use the slope proxy.", exc)
        return None


def fetch_sanger_maurer_vs30(bbox=PUGET_CASCADES_BBOX, output_dir=Path("data/processed")):
    """Placeholder: pull the Sanger-Maurer parametric Vs30 from the GAIA vs-STAC.

    Delegates to :func:`src.data.fetch_gaia.fetch_vs30` (the GAIA vs-STAC catalog). The STAC is not
    always reachable; returns the written path or None. Wired here so the pipeline can prefer the
    parametric product once the catalog is live.
    """
    try:
        from src.data.fetch_gaia import fetch_vs30 as _gaia_vs30

        return _gaia_vs30(tuple(bbox), Path(output_dir))
    except Exception as exc:
        logger.warning("Sanger-Maurer (GAIA vs-STAC) Vs30 not available yet (%s).", exc)
        return None


def get_vs30(bbox=PUGET_CASCADES_BBOX, source="wald_allen",
             slope_tif=Path("data/processed/terrain_slope_90m.tif"), like=None, region="active"):
    """Unified Vs30 accessor. ``source`` in {wald_allen, usgs, sanger_maurer}; falls back to the
    always-available slope proxy. Returns a Vs30 DataArray (m/s)."""
    if source == "wald_allen":
        return vs30_from_slope(slope_tif, region=region)
    if source == "usgs":
        vs = fetch_usgs_vs30(bbox, like=like)
        return vs if vs is not None else vs30_from_slope(slope_tif, region=region)
    if source == "sanger_maurer":
        p = fetch_sanger_maurer_vs30(bbox)
        if p is not None and Path(p).exists():
            import rioxarray as rxr
            return rxr.open_rasterio(p, masked=True).squeeze("band", drop=True)
        logger.info("Falling back to the Wald-Allen slope proxy for Vs30.")
        return vs30_from_slope(slope_tif, region=region)
    raise ValueError(f"unknown Vs30 source {source!r}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Produce a 90 m Vs30 raster (Wald-Allen slope proxy by default).")
    p.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"),
                   default=PUGET_CASCADES_BBOX)
    p.add_argument("--source", choices=["wald_allen", "usgs", "sanger_maurer"], default="wald_allen")
    p.add_argument("--slope", type=Path, default=Path("data/processed/terrain_slope_90m.tif"))
    p.add_argument("--region", choices=["active", "stable"], default="active")
    p.add_argument("--output", type=Path, default=Path("data/processed/vs30_90m.tif"))
    args = p.parse_args()

    vs = get_vs30(tuple(args.bbox), source=args.source, slope_tif=args.slope, region=args.region)
    if vs.rio.crs is None:
        vs = vs.rio.write_crs("EPSG:5070")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    vs.rio.to_raster(args.output)
    finite = np.isfinite(vs.values)
    logger.info("Wrote Vs30 (%s) to %s | range %.0f-%.0f m/s, median %.0f",
                args.source, args.output, float(np.nanmin(vs.values)), float(np.nanmax(vs.values)),
                float(np.nanmedian(vs.values[finite])))


if __name__ == "__main__":
    main()
